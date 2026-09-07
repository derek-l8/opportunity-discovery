import copy
import hashlib
import json
from pathlib import Path

import pytest

from opportunity_discovery.export import export_all
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from opportunity_discovery.review_contract import (
    ReviewContractError,
    import_review_response,
    validate_review_response,
)
from tests.helpers import MockFetcher, make_db, source

DEMO_DIR = Path(__file__).parent / "fixtures" / "demo"
DEMO_FEED = DEMO_DIR / "phase1-opportunities.json"
RESPONSE_FIXTURE = DEMO_DIR / "phase2-review-response.json"


def _write_generation(tmp_path: Path, identifiers: list[str], generation_id: str = "a" * 64) -> Path:
    candidate_path = tmp_path / "candidates.jsonl"
    payload = b"".join(
        json.dumps({"opportunity_id": identifier}, sort_keys=True).encode() + b"\n"
        for identifier in identifiers
    )
    candidate_path.write_bytes(payload)
    manifest = {
        "generation_id": generation_id,
        "files": [{"filename": "candidates.jsonl", "sha256": hashlib.sha256(payload).hexdigest()}],
    }
    manifest_path = tmp_path / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _fixture() -> dict:
    return json.loads(RESPONSE_FIXTURE.read_text(encoding="utf-8"))


def test_synthetic_response_exercises_all_dispositions_and_preserves_custom():
    document = _fixture()
    validated = validate_review_response(document)
    assert {item["disposition"] for item in validated["decisions"]} == {
        "promote",
        "defer",
        "dismiss",
        "duplicate",
    }
    assert validated["custom"] == {"synthetic_run_label": "phase-2-demo"}
    assert validated["decisions"][0]["custom"] == {"review_lane": "demo"}


def test_review_formats_are_validated():
    for value in ("2026-09-06", "not-a-time"):
        document = _fixture()
        document["reviewed_at"] = value
        with pytest.raises(ReviewContractError, match="ISO-8601 timestamp"):
            validate_review_response(document)
    document = _fixture()
    document["decisions"][0]["official_evidence"]["checked_at"] = "2026-09-06"
    with pytest.raises(ReviewContractError, match="ISO-8601 timestamp"):
        validate_review_response(document)
    document = _fixture()
    document["decisions"][0]["official_evidence"]["exact_deadline"] = "2027-02-30"
    with pytest.raises(ReviewContractError, match="ISO-8601 date or timestamp"):
        validate_review_response(document)


def test_unknown_fields_and_malformed_or_duplicate_decision_ids_are_rejected():
    document = _fixture()
    document["private_rank"] = 1
    with pytest.raises(ReviewContractError, match="under custom"):
        validate_review_response(document)
    document = _fixture()
    document["decisions"][0]["opportunity_id"] = "opp_does_not_exist"
    with pytest.raises(ReviewContractError, match="stable opportunity ID"):
        validate_review_response(document)
    document = _fixture()
    document["decisions"].append(copy.deepcopy(document["decisions"][0]))
    with pytest.raises(ReviewContractError, match="duplicate decision"):
        validate_review_response(document)


def test_duplicate_requires_distinct_strong_identity():
    document = _fixture()
    document["decisions"][-1].pop("identity_evidence")
    with pytest.raises(ReviewContractError, match="strong identity evidence"):
        validate_review_response(document)
    document = _fixture()
    duplicate = document["decisions"][-1]
    duplicate["duplicate_of"] = duplicate["opportunity_id"]
    with pytest.raises(ReviewContractError, match="another opportunity"):
        validate_review_response(document)


def test_generation_artifact_integrity_failures_preserve_existing_response(tmp_path):
    document = _fixture()
    identifiers = [item["opportunity_id"] for item in document["decisions"]]
    identifiers.append(document["decisions"][-1]["duplicate_of"])
    manifest_path = _write_generation(tmp_path, identifiers, document["packet_generation_id"])
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(document), encoding="utf-8")
    output_path = tmp_path / "review_response.json"
    output_path.write_text("existing-valid-response\n", encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ReviewContractError, match="SHA-256"):
        import_review_response(input_path, output_path, manifest_path=manifest_path)
    assert output_path.read_text() == "existing-valid-response\n"

    duplicate_payload = b"".join(
        json.dumps({"opportunity_id": identifiers[0]}).encode() + b"\n" for _ in range(2)
    )
    (tmp_path / "candidates.jsonl").write_bytes(duplicate_payload)
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["sha256"] = hashlib.sha256(duplicate_payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReviewContractError, match="duplicate opportunity_id"):
        import_review_response(input_path, output_path, manifest_path=manifest_path)
    assert output_path.read_text() == "existing-valid-response\n"


def test_synthetic_demo_exports_real_ids_and_imports_end_to_end(engine_config, tmp_path):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    feed_url = "https://synthetic.example/feed.json"
    fetcher.add(feed_url, 200, DEMO_FEED.read_text(encoding="utf-8"))
    spec = source(
        source_id="synthetic-phase1",
        organization="Synthetic Opportunities",
        adapter="jsonfeed",
        endpoint_config={"url": feed_url, "records_path": "jobs"},
    )
    sync_sources_to_db(conn, [spec])
    summary = RunSummary(run_id="phase2-e2e", started_at="2026-09-06T00:00:00Z")
    Pipeline(conn, engine_config, summary.run_id, summary).process_source(spec, fetcher)
    export_all(conn, engine_config, summary.run_id)

    output_dir = engine_config.paths.output_dir
    manifest_path = output_dir / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    candidates = {
        item["title"]: item["opportunity_id"]
        for item in map(json.loads, (output_dir / "candidates.jsonl").read_text().splitlines())
    }
    document = _fixture()
    expected_ids = {
        candidates["Embedded Firmware Intern"],
        candidates["Robotics Technical Opportunity"],
        candidates["Student Engineering Recruiting Event"],
        candidates["Embedded Firmware Intern Summer 2027"],
        candidates["Embedded Firmware Intern Summer"],
    }
    response_ids = {item["opportunity_id"] for item in document["decisions"]} | {
        document["decisions"][-1]["duplicate_of"]
    }
    assert response_ids == expected_ids
    document["packet_generation_id"] = manifest["generation_id"]
    open_page = (DEMO_DIR / "phase2-official-open.html").read_text()
    expired_page = (DEMO_DIR / "phase2-official-expired.html").read_text()
    assert "Applications open" in open_page and 'datetime="2027-03-15"' in open_page
    assert "Applications closed" in expired_page and 'datetime="2020-01-01"' in expired_page
    assert document["decisions"][0]["official_evidence"]["availability"] == "open"
    assert document["decisions"][2]["official_evidence"]["availability"] == "closed"

    input_path = tmp_path / "phase2-response.json"
    input_path.write_text(json.dumps(document), encoding="utf-8")
    output_path = output_dir / "review_response.json"
    result = import_review_response(input_path, output_path, manifest_path=manifest_path)
    assert result["decision_count"] == 4
    valid_output = output_path.read_bytes()
    for field, invented_id in (
        ("opportunity_id", "opp_ffffffffffffffffffffffffffffffff"),
        ("duplicate_of", "opp_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"),
    ):
        invented = copy.deepcopy(document)
        target = invented["decisions"][0] if field == "opportunity_id" else invented["decisions"][-1]
        target[field] = invented_id
        input_path.write_text(json.dumps(invented), encoding="utf-8")
        with pytest.raises(ReviewContractError, match=f"{field} is not in"):
            import_review_response(input_path, output_path, manifest_path=manifest_path)
        assert output_path.read_bytes() == valid_output
    conn.close()
