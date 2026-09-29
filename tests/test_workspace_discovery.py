"""Synthetic Home and Explore behavior across the public/private boundary."""

import hashlib
import json

import pytest

from opportunity_discovery.workspace_actions import mark_workspace_opportunity
from opportunity_discovery.workspace_dashboard import render_dashboard
from opportunity_discovery.workspace_discovery import list_curated_home, list_explore
from opportunity_discovery.workspace_state import WorkspaceStateError, apply_workspace_review
from tests.test_workspace_state import make_generation, make_workspace, materialize_review

PROMOTED = "opp_239f53013db5046110ffb26dfb5c5188"
RESEARCH = "opp_62275629da8a983b921695cc4ce53996"
UNREVIEWED = "opp_3cf744c778c9ceccceb50d064383d337"


def add_review_queue(manifest_path):
    output = manifest_path.parent
    payload = (output / "candidates.jsonl").read_bytes()
    (output / "review_queue.jsonl").write_bytes(payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "filename": "review_queue.jsonl",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_imported_decisions_drive_home_order_and_user_state(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    add_review_queue(manifest)

    def reverse_priority(document):
        first, second = document["decisions"][:2]
        first["disposition"] = "defer"
        first["reason_codes"] = ["research-missing-facts"]
        second["disposition"] = "promote"
        second["reason_codes"] = ["profile-relevant", "official-page-current"]
        second["official_evidence"]["availability"] = "open"
        second["verification"]["supports_current_opportunity"] = True
        second["eligibility"]["conclusion"] = "no-known-hard-failure"

    apply_workspace_review(root, materialize_review(tmp_path, reverse_priority), manifest_path=manifest)
    home = list_curated_home(root)
    assert [item["opportunity_id"] for item in home["items"]] == [RESEARCH, PROMOTED]
    page = render_dashboard(root, "token", {}, manifest_path=manifest)
    assert page.index(RESEARCH) < page.index(PROMOTED)
    assert "Why selected: profile relevant, official page current" in page
    assert "Next: Recheck the official page" in page
    assert "availability or eligibility facts" in page
    assert "Source-stated deadline" not in page  # Home uses the private review detail.

    mark_workspace_opportunity(root, RESEARCH, "done")
    assert [item["opportunity_id"] for item in list_curated_home(root)["items"]] == [PROMOTED]
    explore = list_explore(root, manifest)
    assert explore["reviewed_count"] == 4  # Done remains a reviewed private decision.


def test_unreviewed_outside_imported_batch_remains_searchable_in_explore(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    add_review_queue(manifest)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)

    page = list_explore(root, manifest, search="Embedded Firmware Internship", review_status="unreviewed")
    assert page["queue_count"] == 5
    assert page["reviewed_count"] == 4
    assert page["unreviewed_count"] == 1
    assert [item["opportunity_id"] for item in page["items"]] == [UNREVIEWED]
    html = render_dashboard(
        root, "token", {"view": "explore", "search": "Embedded Firmware Internship"}, manifest_path=manifest
    )
    assert UNREVIEWED in html
    assert "Current queue: 5; reviews imported: 4; no review imported: 1" in html
    assert "Collector text and links are unverified" in html
    assert 'name="review_status"' in html


def test_absent_or_failed_review_is_not_an_empty_opportunity_judgment(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    add_review_queue(manifest)
    home = render_dashboard(root, "token", {}, manifest_path=manifest)
    assert "No AI review has been imported yet" in home
    assert "If review import failed, correct it and retry" in home
    assert "A failed or absent review never means the queue has nothing worth doing" in home
    assert "Current queue: 5; reviews imported: 0; no review imported: 5" in home
    assert UNREVIEWED not in home
    assert UNREVIEWED in render_dashboard(root, "token", {"view": "explore"}, manifest_path=manifest)

    def bad_generation(document):
        document["packet_generation_id"] = "b" * 64

    with pytest.raises(WorkspaceStateError, match="generation_id does not match"):
        apply_workspace_review(root, materialize_review(tmp_path, bad_generation), manifest_path=manifest)
    assert "No AI review has been imported yet" in render_dashboard(root, "token", {}, manifest_path=manifest)

    queue_path = manifest.parent / "review_queue.jsonl"
    queue_path.write_text(queue_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    unavailable = render_dashboard(root, "token", {"view": "explore"}, manifest_path=manifest)
    assert "Explore unavailable" in unavailable
    assert "hash does not match" in unavailable
    assert "Current queue unavailable" in unavailable
    assert "current queue leads</span>" in unavailable
    assert "No leads match" not in unavailable


def test_explore_filters_type_and_shows_newly_discovered_first(tmp_path):
    root = make_workspace(tmp_path)
    manifest_path = make_generation(tmp_path)
    add_review_queue(manifest_path)
    queue_path = manifest_path.parent / "review_queue.jsonl"
    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    rows[0].update(engagement_type="internship", first_seen="2026-09-28T00:00:00Z", location_text="Boston")
    rows[1].update(engagement_type="program", first_seen="2026-09-29T00:00:00Z")
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    queue_path.write_bytes(payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    next(entry for entry in manifest["files"] if entry["filename"] == "review_queue.jsonl")["sha256"] = (
        hashlib.sha256(payload).hexdigest()
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    page = list_explore(root, manifest_path)
    assert page["items"][0]["opportunity_id"] == RESEARCH
    internship = list_explore(root, manifest_path, engagement_type="internship")
    assert [item["opportunity_id"] for item in internship["items"]] == [PROMOTED]
    assert [
        item["opportunity_id"] for item in list_explore(root, manifest_path, search="Boston")["items"]
    ] == [PROMOTED]
    html = render_dashboard(
        root, "token", {"view": "explore", "engagement_type": "program"}, manifest_path=manifest_path
    )
    assert 'name="engagement_type"' in html
    assert "First found: 2026-09-29" in html


def test_explore_escapes_source_text_from_a_valid_manifest(tmp_path):
    root = make_workspace(tmp_path)
    manifest_path = make_generation(tmp_path)
    add_review_queue(manifest_path)
    queue_path = manifest_path.parent / "review_queue.jsonl"
    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["title"] = '<script>alert("lead")</script>'
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    queue_path.write_bytes(payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    next(entry for entry in manifest["files"] if entry["filename"] == "review_queue.jsonl")["sha256"] = (
        hashlib.sha256(payload).hexdigest()
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    page = render_dashboard(
        root, "token", {"view": "explore", "search": "script"}, manifest_path=manifest_path
    )
    assert "&lt;script&gt;" in page
    assert '<script>alert("lead")</script>' not in page


def test_review_timestamp_without_imported_disposition_does_not_count_as_review(tmp_path):
    root = make_workspace(tmp_path)
    manifest_path = make_generation(tmp_path)
    add_review_queue(manifest_path)
    board = {
        "schema_version": "1.0",
        "updated_at": None,
        "opportunities": {
            UNREVIEWED: {
                "opportunity_id": UNREVIEWED,
                "review": {"reviewed_at": "2026-09-29T00:00:00Z"},
            }
        },
        "custom": {},
    }
    (root / ".opdisc" / "board.json").write_text(json.dumps(board), encoding="utf-8")
    assert list_curated_home(root)["reviewed_count"] == 0
    assert list_explore(root, manifest_path)["unreviewed_count"] == 5
