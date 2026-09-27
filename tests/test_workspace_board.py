"""Phase 6 private board read contract, using the existing synthetic demo."""

import json
from pathlib import Path

import jsonschema
import pytest

import opportunity_discovery.workspace_actions as workspace_actions
from opportunity_discovery.cli import main
from opportunity_discovery.workspace_actions import (
    change_workspace_opportunity,
    list_workspace_history,
    mark_workspace_opportunity,
)
from opportunity_discovery.workspace_board import list_workspace_board
from opportunity_discovery.workspace_state import (
    WorkspaceStateError,
    apply_workspace_feedback,
    apply_workspace_review,
)
from tests.test_workspace_state import (
    FEEDBACK_FIXTURE,
    make_generation,
    make_workspace,
    materialize_review,
    seed_user_state,
)

SCHEMA = Path(__file__).parent.parent / "schemas" / "workspace-board-page.schema.json"
HISTORY_SCHEMA = Path(__file__).parent.parent / "schemas" / "workspace-history-page.schema.json"
SCENARIO = json.loads(
    (Path(__file__).parent / "fixtures" / "demo" / "phase6-board-scenario.json").read_text(encoding="utf-8")
)
PROMOTED_ID = SCENARIO["opportunity_ids"]["promoted"]
RESEARCH_ID = SCENARIO["opportunity_ids"]["research"]


def test_board_page_filters_paginates_and_preserves_private_provenance(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    feedback = tmp_path / "feedback.json"
    feedback.write_bytes(FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, feedback)

    page = list_workspace_board(root, view="all", offset=1, limit=2)
    jsonschema.validate(page, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert page["total"] == SCENARIO["after_phase4_feedback"]["all"]
    assert page["next_offset"] == 3
    assert [item["opportunity_id"] for item in page["items"]] == sorted(
        item["opportunity_id"] for item in page["items"]
    )
    assert list_workspace_board(root, view="active")["total"] == SCENARIO["after_phase4_feedback"]["active"]
    assert (
        list_workspace_board(root, view="history", user_status="done")["total"]
        == SCENARIO["after_phase4_feedback"]["history"]
    )
    assert (
        list_workspace_board(root, view="dismissed")["total"]
        == SCENARIO["after_phase4_feedback"]["dismissed"]
    )
    found = list_workspace_board(root, view="all", search="Firmware", availability="open")
    assert found["total"] == 2
    item = next(
        item for item in found["items"] if item["opportunity_id"] == "opp_239f53013db5046110ffb26dfb5c5188"
    )
    assert item["official_url"] == "https://synthetic.example/official/intern-open"
    assert item["review"]["packet_generation_id"] == "a" * 64
    assert item["updated_at"] == "2026-09-11T09:00:00Z"
    assert item["provenance"][0]["source_id"] == "synthetic-demo"
    assert item["collector_custom"] == {"collector-extension": "preserved-snapshot"}
    assert item["user_state"]["feedback"]["reason_code"] == "future-cycle-monitored"


def test_board_read_is_nonmutating_and_rejects_invalid_pagination(tmp_path, capsys):
    root = make_workspace(tmp_path)
    assert list_workspace_board(root)["items"] == []
    assert not (root / ".opdisc" / "board.json").exists()
    with pytest.raises(WorkspaceStateError, match="limit"):
        list_workspace_board(root, limit=201)
    assert main(["--json", "workspace-board", str(root), "--view", "all"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 0


def test_direct_done_preserves_submitted_pipeline_and_can_restore(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    seed_user_state(root)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)

    result = mark_workspace_opportunity(
        root, PROMOTED_ID, "done", reason_code="monitoring", prefer=("firmware",)
    )
    item = list_workspace_board(root, view="history")["items"][0]
    assert item["opportunity_id"] == PROMOTED_ID
    assert item["user_status"] == "done"
    assert item["pipeline_state"] == "submitted"
    assert list_workspace_board(root, view="waiting")["total"] == 0
    assert item["user_state"]["custom"] == {"private-extension": "keep"}
    assert item["custom"] == {"board-extension": "keep"}
    assert result["event"]["before"]["pipeline_state"] == "submitted"
    preferences = json.loads((root / "knowledge" / "PREFERENCES.json").read_text(encoding="utf-8"))
    assert preferences["signals"]["firmware"]["prefer_count"] == 1

    change_workspace_opportunity(root, PROMOTED_ID, "restore")
    restored = list_workspace_board(root, view="waiting")["items"][0]
    assert restored["user_status"] == "submitted"
    assert restored["pipeline_state"] == "submitted"
    assert restored["review"]["packet_generation_id"] == "a" * 64

    history = list_workspace_history(root, opportunity_id=PROMOTED_ID, limit=1)
    jsonschema.validate(history, json.loads(HISTORY_SCHEMA.read_text(encoding="utf-8")))
    assert history["total"] == 2
    assert history["next_offset"] == 1
    assert history["events"][0]["action"] == "restore"
    all_history = list_workspace_history(root)
    assert all_history["total"] == 3  # review report, Done, restore; no duplicate feedback report


def test_delete_restore_pipeline_wait_resume_and_purge(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    artifact = root / "opportunities" / RESEARCH_ID / "note.txt"
    artifact.parent.mkdir()
    artifact.write_text("synthetic note", encoding="utf-8")
    application = root / "applications" / RESEARCH_ID / "draft.txt"
    application.parent.mkdir()
    application.write_text("synthetic draft", encoding="utf-8")

    mark_workspace_opportunity(root, RESEARCH_ID, "delete", reason_text="Synthetic mismatch")
    assert list_workspace_board(root, view="dismissed", user_status="delete")["total"] == 1
    change_workspace_opportunity(root, RESEARCH_ID, "restore")
    assert list_workspace_board(root, view="active", search="Robotics")["total"] == 1

    change_workspace_opportunity(root, RESEARCH_ID, "pipeline", pipeline_state="preparing")
    change_workspace_opportunity(
        root,
        RESEARCH_ID,
        "wait",
        wait_reason=SCENARIO["waiting_example"]["reason"],
        wait_until=SCENARIO["waiting_example"]["until"],
    )
    waiting = list_workspace_board(root, view="waiting")["items"][0]
    assert waiting["waiting"]["until"] == SCENARIO["waiting_example"]["until"]
    assert waiting["pipeline_state"] == "preparing"
    change_workspace_opportunity(root, RESEARCH_ID, "done")
    assert list_workspace_board(root, view="history", user_status="done")["total"] == 1
    assert list_workspace_board(root, view="waiting")["total"] == 0
    change_workspace_opportunity(root, RESEARCH_ID, "restore")
    assert list_workspace_board(root, view="waiting")["total"] == 1
    change_workspace_opportunity(root, RESEARCH_ID, "resume")
    assert list_workspace_board(root, view="active", pipeline_state="preparing")["total"] == 1

    result = change_workspace_opportunity(root, RESEARCH_ID, "purge")
    assert result["removed_artifacts"] == [
        f"opportunities/{RESEARCH_ID}",
        f"applications/{RESEARCH_ID}",
    ]
    assert not artifact.exists()
    assert not application.exists()
    assert list_workspace_board(root, view="all")["total"] == 3
    assert list_workspace_history(root, opportunity_id=RESEARCH_ID)["total"] == 0


def test_purge_refuses_symlinked_artifacts_before_board_changes(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    try:
        (root / "opportunities" / RESEARCH_ID).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    board_path = root / ".opdisc" / "board.json"
    before = board_path.read_bytes()
    with pytest.raises(WorkspaceStateError, match="symlink component"):
        change_workspace_opportunity(root, RESEARCH_ID, "purge")
    assert board_path.read_bytes() == before
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_done_without_reason_preserves_legacy_submitted_state_without_learning(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    seed_user_state(root)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    board_path = root / ".opdisc" / "board.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["opportunities"][PROMOTED_ID]["user_state"]["last_action"] = {"custom": {"user-extension": "keep"}}
    board_path.write_text(json.dumps(board), encoding="utf-8")
    mark_workspace_opportunity(root, PROMOTED_ID, "done")
    history = list_workspace_board(root, view="history")["items"][0]
    assert history["pipeline_state"] == "submitted"
    assert history["user_status"] == "done"
    assert history["user_state"]["last_action"]["custom"] == {"user-extension": "keep"}
    assert list_workspace_board(root, view="waiting")["total"] == 0
    assert not (root / "knowledge" / "PREFERENCES.json").exists()
    change_workspace_opportunity(root, PROMOTED_ID, "restore")
    assert list_workspace_board(root, view="waiting")["items"][0]["user_status"] == "submitted"


def test_imported_feedback_cannot_reverse_later_direct_delete(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    first = tmp_path / "first-feedback.json"
    first.write_bytes(FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, first)

    monkeypatch.setattr(workspace_actions, "_now", lambda: "2026-09-12T10:00:00Z")
    change_workspace_opportunity(root, PROMOTED_ID, "delete")
    incoming = json.loads(first.read_text(encoding="utf-8"))
    incoming["recorded_at"] = "2026-09-12T09:30:00Z"
    incoming["feedback"] = [incoming["feedback"][0]]
    incoming["feedback"][0]["feedback_id"] = "synthetic-between-actions"
    path = tmp_path / "between-actions.json"
    path.write_text(json.dumps(incoming), encoding="utf-8")

    tracked = [
        root / ".opdisc" / "board.json",
        root / "knowledge" / "PREFERENCES.json",
        root / ".opdisc" / "checkpoint.json",
    ]
    before = [path.read_bytes() for path in tracked]
    with pytest.raises(WorkspaceStateError, match="older than the stored user decision"):
        apply_workspace_feedback(root, path)
    assert [path.read_bytes() for path in tracked] == before
    dismissed = list_workspace_board(root, view="dismissed", user_status="delete")
    assert PROMOTED_ID in {item["opportunity_id"] for item in dismissed["items"]}


def test_later_review_preserves_user_action_and_monotonic_update_time(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    mark_workspace_opportunity(root, PROMOTED_ID, "done")
    board_path = root / ".opdisc" / "board.json"
    before = json.loads(board_path.read_text(encoding="utf-8"))

    def advance_review(document):
        document["reviewed_at"] = "2026-09-13T12:00:00Z"

    later_review = materialize_review(tmp_path, advance_review, name="later-review.json")
    apply_workspace_review(root, later_review, manifest_path=manifest)
    after = json.loads(board_path.read_text(encoding="utf-8"))
    assert after["updated_at"] == before["updated_at"]
    assert (
        after["opportunities"][PROMOTED_ID]["updated_at"]
        == before["opportunities"][PROMOTED_ID]["updated_at"]
    )
    assert after["opportunities"][PROMOTED_ID]["user_state"]["status"] == "done"
    assert after["opportunities"][PROMOTED_ID]["review"]["reviewed_at"] == "2026-09-13T12:00:00Z"


def test_cli_board_actions_and_validation_failures(tmp_path, capsys):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    assert main(["workspace-done", str(root), PROMOTED_ID, "--prefer", "firmware"]) == 2
    assert "require a reason" in capsys.readouterr().err
    assert main(["workspace-done", str(root), PROMOTED_ID, "--reason-code", "   "]) == 2
    assert "non-blank" in capsys.readouterr().err
    assert main(["workspace-done", str(root), PROMOTED_ID]) == 0
    capsys.readouterr()
    assert not (root / "knowledge" / "PREFERENCES.json").exists()
    assert main(["workspace-restore", str(root), PROMOTED_ID]) == 0
    capsys.readouterr()
    assert main(["--json", "workspace-done", str(root), PROMOTED_ID, "--reason-code", "reviewed"]) == 0
    assert json.loads(capsys.readouterr().out)["event"]["action"] == "done"
    assert main(["--json", "workspace-history", str(root), "--opportunity-id", PROMOTED_ID]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 3
    assert main(["workspace-wait", str(root), PROMOTED_ID, "--reason", "pending", "--until", "bad"]) == 2
    assert "ISO date" in capsys.readouterr().err
