"""Phase 4 external private-board and adaptive-knowledge contracts."""

import hashlib
import json
from pathlib import Path

import pytest

from opportunity_discovery.cli import main
from opportunity_discovery.workspace import initialize_workspace
from opportunity_discovery.workspace_state import (
    WorkspaceStateError,
    apply_workspace_feedback,
    apply_workspace_review,
    validate_workspace_feedback,
    validate_workspace_review,
)

DEMO_DIR = Path(__file__).parent / "fixtures" / "demo"
REVIEW_FIXTURE = DEMO_DIR / "phase4-workspace-review.json"
FEEDBACK_FIXTURE = DEMO_DIR / "phase4-feedback.json"
LATER_FEEDBACK_FIXTURE = DEMO_DIR / "phase4-later-feedback.json"
GENERATION_ID = "a" * 64


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "Opportunity-Workspace"
    engine = tmp_path / "engine-checkout"
    engine.mkdir()
    initialize_workspace(root, engine_path=engine)
    return root


def candidate(identifier: str, title: str, *, routing_state: str = "included") -> dict:
    return {
        "opportunity_id": identifier,
        "lead_state": "unverified-lead",
        "title": title,
        "canonical_url": f"https://synthetic.example/leads/{identifier}",
        "provenance": [
            {"source_id": "synthetic-demo", "source_url": f"https://synthetic.example/leads/{identifier}"}
        ],
        "routing_state": routing_state,
        "reason_codes": [],
        "custom": {"collector-extension": "preserved-snapshot"},
    }


def make_generation(tmp_path: Path) -> Path:
    output = tmp_path / "public-output"
    output.mkdir()
    candidates = [
        candidate("opp_239f53013db5046110ffb26dfb5c5188", "Embedded Firmware Intern"),
        candidate(
            "opp_62275629da8a983b921695cc4ce53996",
            "Robotics Technical Opportunity",
            routing_state="research_needed",
        ),
        candidate("opp_5f0b35733254ca79f838f299b22d48c5", "Expired Student Event"),
        candidate("opp_dadec78eb76bb2e6078c9f729d396c50", "Firmware Internship Copy"),
        candidate("opp_3cf744c778c9ceccceb50d064383d337", "Embedded Firmware Internship"),
    ]
    payload = "".join(json.dumps(item, sort_keys=True) + "\n" for item in candidates).encode()
    (output / "candidates.jsonl").write_bytes(payload)
    manifest = {
        "schema_version": "1.0",
        "generation_id": GENERATION_ID,
        "files": [
            {
                "filename": "candidates.jsonl",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    (output / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return output / "export_manifest.json"


def materialize_review(tmp_path: Path, mutate=None, *, name: str = "workspace-review.json") -> Path:
    document = json.loads(REVIEW_FIXTURE.read_text(encoding="utf-8"))
    document["packet_generation_id"] = GENERATION_ID
    if mutate:
        mutate(document)
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def seed_user_state(root: Path) -> None:
    board = {
        "schema_version": "1.0",
        "updated_at": "2026-09-01T00:00:00Z",
        "opportunities": {
            "opp_239f53013db5046110ffb26dfb5c5188": {
                "opportunity_id": "opp_239f53013db5046110ffb26dfb5c5188",
                "board_state": "research_needed",
                "verified_facts": {"availability": "unknown", "custom": {"local-fact": 7}},
                "eligibility": {"conclusion": "unknown", "custom": {"local-eligibility": 9}},
                "user_state": {
                    "status": "submitted",
                    "submitted_at": "2026-09-01T00:00:00Z",
                    "custom": {"private-extension": "keep"},
                },
                "custom": {"board-extension": "keep"},
            }
        },
        "custom": {"board-owner-extension": "keep"},
    }
    (root / ".opdisc" / "board.json").write_text(json.dumps(board), encoding="utf-8")


def test_workspace_review_applies_all_demo_decisions_and_preserves_user_state(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    review = materialize_review(tmp_path)
    seed_user_state(root)

    result = apply_workspace_review(root, review, manifest_path=manifest)

    assert (result.promoted, result.research_needed, result.dismissed, result.duplicates) == (1, 1, 1, 1)
    board = json.loads((root / ".opdisc" / "board.json").read_text(encoding="utf-8"))
    records = board["opportunities"]
    promoted = records["opp_239f53013db5046110ffb26dfb5c5188"]
    assert promoted["board_state"] == "active"
    assert promoted["verified_facts"]["availability"] == "open"
    assert promoted["verified_facts"]["exact_deadline"] == "2027-03-15"
    assert promoted["verified_facts"]["custom"] == {"local-fact": 7}
    assert promoted["eligibility"]["conclusion"] == "no-known-hard-failure"
    assert promoted["user_state"]["status"] == "submitted"
    assert promoted["user_state"]["custom"] == {"private-extension": "keep"}
    assert promoted["custom"] == {"board-extension": "keep"}
    assert promoted["collector_snapshot"]["custom"] == {"collector-extension": "preserved-snapshot"}
    assert records["opp_62275629da8a983b921695cc4ce53996"]["board_state"] == "research_needed"
    assert records["opp_5f0b35733254ca79f838f299b22d48c5"]["board_state"] == "dismissed"
    duplicate = records["opp_dadec78eb76bb2e6078c9f729d396c50"]
    assert duplicate["board_state"] == "duplicate"
    assert duplicate["duplicate_of"] == "opp_3cf744c778c9ceccceb50d064383d337"
    assert board["custom"] == {"board-owner-extension": "keep"}

    knowledge = json.loads((root / "knowledge" / "AUTOMATED.json").read_text(encoding="utf-8"))
    assert knowledge["claims"]["synthetic-open-cycle"]["custom"] == {"demo": True}
    assert "Automated review knowledge" in (root / "knowledge" / "CATALOG.md").read_text()
    proposals = json.loads((root / ".opdisc" / "proposals.json").read_text(encoding="utf-8"))
    assert proposals["proposals"]["synthetic-hard-filter-proposal"]["status"] == "proposed"
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "complete"
    assert checkpoint["operation"] == "apply-review"
    snapshots = list((root / ".opdisc" / "history" / "knowledge").glob("*/manifest.json"))
    assert len(snapshots) == 1
    snapshot = json.loads(snapshots[0].read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in snapshot["files"]}
    assert by_path["knowledge/AUTOMATED.json"]["existed"] is False
    assert by_path["knowledge/CATALOG.md"]["existed"] is True
    assert result.report_path.is_file()
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["custom"] == {"synthetic_run_label": "phase-4-demo"}


def test_promote_below_threshold_stays_research_needed(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)

    def mutate(document):
        decision = document["decisions"][0]
        decision["verification"]["supports_current_opportunity"] = False
        decision["eligibility"]["conclusion"] = "unknown"

    review = materialize_review(tmp_path, mutate)
    result = apply_workspace_review(root, review, manifest_path=manifest)

    assert result.promoted == 0
    assert result.research_needed == 2
    board = json.loads((root / ".opdisc" / "board.json").read_text(encoding="utf-8"))
    failures = board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]["review"][
        "promotion_threshold_failures"
    ]
    assert failures == ["current-opportunity-not-supported", "hard-eligibility-not-cleared"]


def test_invalid_workspace_review_is_rejected_before_private_mutation(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)

    def mutate(document):
        document["decisions"][0]["surprise"] = "must be under custom"

    review = materialize_review(tmp_path, mutate)
    with pytest.raises(WorkspaceStateError, match="under custom"):
        apply_workspace_review(root, review, manifest_path=manifest)
    assert not (root / ".opdisc" / "board.json").exists()
    assert not (root / ".opdisc" / "checkpoint.json").exists()


def test_reasoned_feedback_updates_only_soft_preferences_and_is_idempotent(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    feedback = tmp_path / "feedback.json"
    feedback.write_bytes(FEEDBACK_FIXTURE.read_bytes())

    first = apply_workspace_feedback(root, feedback)
    second = apply_workspace_feedback(root, feedback)

    assert first.preference_signals_updated == 2
    assert second.preference_signals_updated == 0
    board = json.loads((root / ".opdisc" / "board.json").read_text(encoding="utf-8"))
    assert board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]["user_state"]["status"] == "done"
    assert board["opportunities"]["opp_62275629da8a983b921695cc4ce53996"]["user_state"]["status"] == "delete"
    preferences = json.loads((root / "knowledge" / "PREFERENCES.json").read_text(encoding="utf-8"))
    assert preferences["signals"]["embedded-firmware"]["prefer_count"] == 1
    assert preferences["signals"]["ambiguous-engagement"]["avoid_count"] == 1
    assert len(preferences["signals"]["embedded-firmware"]["evidence"]) == 1
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["hard_configuration_changed"] is False


def test_older_feedback_replay_cannot_reverse_newer_user_decision(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    first = tmp_path / "first-feedback.json"
    first.write_bytes(FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, first)

    later = json.loads(LATER_FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    later_path = tmp_path / "later-feedback.json"
    later_path.write_bytes(LATER_FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, later_path)

    board_path = root / ".opdisc" / "board.json"
    preferences_path = root / "knowledge" / "PREFERENCES.json"
    checkpoint_path = root / ".opdisc" / "checkpoint.json"
    before = (board_path.read_bytes(), preferences_path.read_bytes(), checkpoint_path.read_bytes())
    with pytest.raises(WorkspaceStateError, match="older than the stored user decision"):
        apply_workspace_feedback(root, first)
    assert (board_path.read_bytes(), preferences_path.read_bytes(), checkpoint_path.read_bytes()) == before
    opportunities = json.loads(board_path.read_text(encoding="utf-8"))["opportunities"]
    record = opportunities[later["feedback"][0]["opportunity_id"]]
    assert record["user_state"]["status"] == "delete"


def test_feedback_for_another_record_does_not_regress_global_timestamps(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    later_path = tmp_path / "later-feedback.json"
    later_path.write_bytes(LATER_FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, later_path)

    other = json.loads(FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    other["feedback"] = [other["feedback"][1]]
    other_path = tmp_path / "other-feedback.json"
    other_path.write_text(json.dumps(other), encoding="utf-8")
    apply_workspace_feedback(root, other_path)

    board = json.loads((root / ".opdisc" / "board.json").read_text(encoding="utf-8"))
    preferences = json.loads((root / "knowledge" / "PREFERENCES.json").read_text(encoding="utf-8"))
    assert board["updated_at"] == "2026-09-12T09:00:00Z"
    assert preferences["updated_at"] == "2026-09-12T09:00:00Z"


def test_equal_time_feedback_conflict_and_duplicate_target_are_rejected(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    first = tmp_path / "feedback.json"
    first.write_bytes(FEEDBACK_FIXTURE.read_bytes())
    apply_workspace_feedback(root, first)
    board_path = root / ".opdisc" / "board.json"
    before = board_path.read_bytes()

    changed = json.loads(first.read_text(encoding="utf-8"))
    changed["feedback"][0]["reason_code"] = "different-reason"
    changed_path = tmp_path / "changed-feedback.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(WorkspaceStateError, match="conflicts at the stored recorded_at"):
        apply_workspace_feedback(root, changed_path)
    assert board_path.read_bytes() == before

    changed["feedback"][1]["opportunity_id"] = changed["feedback"][0]["opportunity_id"]
    with pytest.raises(WorkspaceStateError, match="appears more than once"):
        validate_workspace_feedback(changed)


def test_feedback_without_reason_is_rejected():
    document = json.loads(FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    document["feedback"][0].pop("reason_code")
    with pytest.raises(WorkspaceStateError, match="requires reason_code or reason_text"):
        validate_workspace_feedback(document)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda entry: entry.pop("preference_signals"), "preference_signals is required"),
        (lambda entry: entry.__setitem__("reason_code", ""), "reason_code must be a non-empty string"),
        (lambda entry: entry.__setitem__("reason_code", "   "), "reason_code must be a non-empty string"),
        (lambda entry: entry.__setitem__("reason_code", 7), "reason_code must be a non-empty string"),
        (lambda entry: entry.__setitem__("reason_text", ""), "reason_text must be a non-empty string"),
        (lambda entry: entry.__setitem__("reason_text", []), "reason_text must be a non-empty string"),
    ],
)
def test_feedback_runtime_validator_matches_required_reason_contract(mutation, error):
    document = json.loads(FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    mutation(document["feedback"][0])
    with pytest.raises(WorkspaceStateError, match=error):
        validate_workspace_feedback(document)


def test_review_staleness_rejects_older_and_equal_conflicts_without_partial_mutation(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    newer = materialize_review(
        tmp_path,
        lambda document: document.__setitem__("reviewed_at", "2026-09-12T12:00:00Z"),
        name="newer.json",
    )
    apply_workspace_review(root, newer, manifest_path=manifest)
    protected_paths = [
        root / ".opdisc" / "board.json",
        root / "knowledge" / "AUTOMATED.json",
        root / ".opdisc" / "proposals.json",
        root / ".opdisc" / "checkpoint.json",
    ]
    before = {path: path.read_bytes() for path in protected_paths}
    history_before = sorted(path.as_posix() for path in (root / ".opdisc" / "history").rglob("*"))
    reports_before = sorted(path.name for path in (root / ".opdisc" / "reports").glob("*.json"))

    older = materialize_review(
        tmp_path,
        lambda document: document.__setitem__("reviewed_at", "2026-09-11T12:00:00Z"),
        name="older.json",
    )
    with pytest.raises(WorkspaceStateError, match="older than the stored review"):
        apply_workspace_review(root, older, manifest_path=manifest)
    assert {path: path.read_bytes() for path in protected_paths} == before
    assert sorted(path.as_posix() for path in (root / ".opdisc" / "history").rglob("*")) == history_before
    assert sorted(path.name for path in (root / ".opdisc" / "reports").glob("*.json")) == reports_before

    conflicting = materialize_review(
        tmp_path,
        lambda document: (
            document.__setitem__("reviewed_at", "2026-09-12T12:00:00Z"),
            document["decisions"][0]["reason_codes"].append("conflicting-content"),
        ),
        name="conflicting.json",
    )
    with pytest.raises(WorkspaceStateError, match="only an exact input replay is allowed"):
        apply_workspace_review(root, conflicting, manifest_path=manifest)
    assert {path: path.read_bytes() for path in protected_paths} == before
    assert sorted(path.name for path in (root / ".opdisc" / "reports").glob("*.json")) == reports_before


def test_review_exact_replay_is_allowed_and_records_input_identity(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    review = materialize_review(tmp_path)
    expected_digest = hashlib.sha256(review.read_bytes()).hexdigest()

    first = apply_workspace_review(root, review, manifest_path=manifest)
    second = apply_workspace_review(root, review, manifest_path=manifest)

    assert second.to_dict() == first.to_dict()
    assert json.loads(first.report_path.read_text(encoding="utf-8"))["input_sha256"] == expected_digest
    board = json.loads((root / ".opdisc" / "board.json").read_text(encoding="utf-8"))
    for decision in json.loads(review.read_text(encoding="utf-8"))["decisions"]:
        assert board["opportunities"][decision["opportunity_id"]]["review"]["input_sha256"] == expected_digest


@pytest.mark.parametrize(
    ("relative", "document", "error"),
    [
        ("knowledge/AUTOMATED.json", {"schema_version": "1.0", "claims": []}, "claims must be an object"),
        (".opdisc/proposals.json", {"schema_version": "1.0", "proposals": []}, "proposals must be an object"),
    ],
)
def test_review_preflights_all_existing_state_before_board_mutation(tmp_path, relative, document, error):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    target = root / relative
    target.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(WorkspaceStateError, match=error):
        apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)

    assert not (root / ".opdisc" / "board.json").exists()
    assert not (root / ".opdisc" / "checkpoint.json").exists()


def test_reapplying_proposal_and_records_preserves_user_and_nested_custom_state(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    seed_user_state(root)
    board_path = root / ".opdisc" / "board.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    existing = board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]
    existing["review"] = {
        "verification": {"custom": {"nested": {"local": 1}}},
        "custom": {"nested": {"local": 1}},
    }
    existing["custom"] = {"nested": {"local": 1}}
    board_path.write_text(json.dumps(board), encoding="utf-8")
    proposals_path = root / ".opdisc" / "proposals.json"
    proposals_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "updated_at": "2026-09-01T00:00:00Z",
                "proposals": {
                    "synthetic-hard-filter-proposal": {
                        "status": "rejected",
                        "created_at": "2026-09-01T00:00:00Z",
                        "reviewed_by_user_at": "2026-09-02T00:00:00Z",
                        "custom": {"nested": {"local": 1}},
                    }
                },
                "custom": {},
            }
        ),
        encoding="utf-8",
    )

    def mutate(document):
        document["decisions"][0]["custom"] = {"nested": {"incoming": 2}}
        document["decisions"][0]["verification"]["custom"] = {"nested": {"incoming": 2}}
        document["proposals"][0]["custom"] = {"nested": {"incoming": 2}}

    result = apply_workspace_review(root, materialize_review(tmp_path, mutate), manifest_path=manifest)
    board = json.loads(board_path.read_text(encoding="utf-8"))
    record = board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]
    assert record["user_state"]["status"] == "submitted"
    assert record["custom"] == {"nested": {"local": 1}}
    assert record["review"]["custom"] == {"nested": {"local": 1, "incoming": 2}}
    assert record["review"]["verification"]["custom"] == {"nested": {"local": 1, "incoming": 2}}
    proposal = json.loads(proposals_path.read_text(encoding="utf-8"))["proposals"][
        "synthetic-hard-filter-proposal"
    ]
    assert proposal["status"] == "rejected"
    assert proposal["reviewed_by_user_at"] == "2026-09-02T00:00:00Z"
    assert proposal["custom"] == {"nested": {"local": 1, "incoming": 2}}
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["custom"] == {"synthetic_run_label": "phase-4-demo"}


def test_feedback_preserves_nested_custom_and_report_level_custom(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    board_path = root / ".opdisc" / "board.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    record = board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]
    record["user_state"]["feedback"] = {"custom": {"nested": {"local": 1}}}
    board_path.write_text(json.dumps(board), encoding="utf-8")
    feedback_document = json.loads(FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    feedback_document["feedback"][0]["custom"] = {"nested": {"incoming": 2}}
    feedback_path = tmp_path / "feedback-custom.json"
    feedback_path.write_text(json.dumps(feedback_document), encoding="utf-8")

    result = apply_workspace_feedback(root, feedback_path)

    board = json.loads(board_path.read_text(encoding="utf-8"))
    custom = board["opportunities"]["opp_239f53013db5046110ffb26dfb5c5188"]["user_state"]["feedback"][
        "custom"
    ]
    assert custom == {"nested": {"local": 1, "incoming": 2}}
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["custom"] == {"synthetic_run_label": "phase-4-feedback-demo"}


def test_workspace_review_and_feedback_cli_json(tmp_path, capsys):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    review = materialize_review(tmp_path)
    assert (
        main(
            [
                "--json",
                "workspace-apply-review",
                str(root),
                str(review),
                "--manifest",
                str(manifest),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["promoted"] == 1

    feedback = tmp_path / "feedback.json"
    feedback.write_bytes(FEEDBACK_FIXTURE.read_bytes())
    assert main(["--json", "workspace-apply-feedback", str(root), str(feedback)]) == 0
    assert json.loads(capsys.readouterr().out)["preference_signals_updated"] == 2


def test_direct_validators_preserve_custom_objects():
    review = json.loads(REVIEW_FIXTURE.read_text(encoding="utf-8"))
    assert validate_workspace_review(review)["custom"] == {"synthetic_run_label": "phase-4-demo"}
    feedback = json.loads(FEEDBACK_FIXTURE.read_text(encoding="utf-8"))
    assert validate_workspace_feedback(feedback)["custom"] == {"synthetic_run_label": "phase-4-feedback-demo"}
