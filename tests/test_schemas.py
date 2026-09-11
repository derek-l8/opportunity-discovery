"""Validate real export artifacts against the shipped JSON Schemas."""

import json
from pathlib import Path

import jsonschema
import pytest

from opportunity_discovery.http_client import Fetcher
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from tests.helpers import MockFetcher, load_fixture, make_db, source

SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


def load_registry():
    from referencing import Registry, Resource

    registry = Registry()
    for path in SCHEMA_DIR.glob("*.schema.json"):
        resource = Resource.from_contents(json.loads(path.read_text(encoding="utf-8")))
        registry = registry.with_resource(path.name, resource)
    return registry


@pytest.fixture()
def exported(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fetcher = Fetcher(engine_config, conn=conn)
    fixture = tmp_path / "feed.json"
    fixture.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "title": "FPGA Design Intern",
                        "url": "https://acme.example.com/1",
                        "season": "Summer 2027",
                        "compensation": "$40/hr paid",
                        "location": "Santa Clara, CA",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    spec = source(adapter="jsonfeed", endpoint_config={"url": fixture.as_uri(), "records_path": "jobs"})
    sync_sources_to_db(conn, [spec])
    from opportunity_discovery.runner import finalize_run

    summary = RunSummary(run_id="run-1", started_at="now")
    Pipeline(conn, engine_config, "run-1", summary).process_source(spec, fetcher)
    finalize_run(conn, engine_config, "run-1", summary)
    fetcher.close()
    return engine_config.paths.output_dir


def test_candidates_validate(exported):
    schema = json.loads((SCHEMA_DIR / "candidate.schema.json").read_text(encoding="utf-8"))
    registry = load_registry()
    for line in (exported / "candidates.jsonl").read_text().splitlines():
        jsonschema.Draft202012Validator(schema, registry=registry).validate(json.loads(line))

    review_schema = json.loads((SCHEMA_DIR / "review-queue-entry.schema.json").read_text(encoding="utf-8"))
    for line in (exported / "review_queue.jsonl").read_text().splitlines():
        jsonschema.Draft202012Validator(review_schema, registry=registry).validate(json.loads(line))


def test_delta_packet_validates(exported):
    schema = json.loads((SCHEMA_DIR / "delta-packet.schema.json").read_text(encoding="utf-8"))
    registry = load_registry()
    doc = json.loads((exported / "delta_packet.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, registry=registry).validate(doc)


def test_synthetic_review_response_validates():
    schema = json.loads((SCHEMA_DIR / "review-response.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "demo" / "phase2-review-response.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(
        schema, registry=load_registry(), format_checker=jsonschema.FormatChecker()
    ).validate(fixture)


def test_workspace_source_manifest_schema_accepts_custom_metadata():
    schema = json.loads((SCHEMA_DIR / "workspace-source-manifest.schema.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "imports": [
            {
                "sha256": "0" * 64,
                "original_name": "synthetic-notes.txt",
                "stored_path": "sources/2026-09-08-synthetic-notes.txt",
                "imported_at": "2026-09-08T12:00:00Z",
                "custom": {"synthetic_label": "demo"},
            }
        ],
        "custom": {"synthetic_scenario": "phase-3-demo"},
    }
    jsonschema.Draft202012Validator(
        schema, registry=load_registry(), format_checker=jsonschema.FormatChecker()
    ).validate(manifest)


@pytest.mark.parametrize(
    "stored_path",
    [
        "/sources/notes.txt",
        "C:/sources/notes.txt",
        "sources/../notes.txt",
        "sources/nested/../../notes.txt",
        "sources\\notes.txt",
        "inbox/notes.txt",
    ],
)
def test_workspace_source_manifest_rejects_nonportable_or_escaping_path(stored_path):
    schema = json.loads((SCHEMA_DIR / "workspace-source-manifest.schema.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "imports": [
            {
                "sha256": "0" * 64,
                "original_name": "notes.txt",
                "stored_path": stored_path,
                "imported_at": "2026-09-08T12:00:00Z",
            }
        ],
        "custom": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(
            schema, registry=load_registry(), format_checker=jsonschema.FormatChecker()
        ).validate(manifest)


def test_run_summary_and_health_validate(exported):
    registry = load_registry()
    for artifact, schema_name in (
        ("run_summary.json", "run-summary.schema.json"),
        ("source_health.json", "source-health.schema.json"),
        ("export_manifest.json", "export-manifest.schema.json"),
    ):
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        doc = json.loads((exported / artifact).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, registry=registry).validate(doc)

    health = json.loads((exported / "source_health.json").read_text(encoding="utf-8"))
    last_check = health["sources"][0]["last_check"]
    assert last_check["records_seen"] == 1
    assert last_check["new_records"] == 1
    assert last_check["changed_records"] == 0
    assert last_check["duration_ms"] >= 0
    assert last_check["pages_fetched"] == 1


def test_program_export_validates_combined_optional_schemas(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    overview = "https://schema.example.com/program"
    application = "https://schema.example.com/program/2027"
    fetcher.add(overview, 200, "<h1>Program overview</h1>")
    fetcher.add(application, 200, load_fixture("program_application_open.html"))
    spec = source(
        source_id="program-schema",
        organization="Synthetic Schema Organization",
        adapter="program-page",
        endpoint_config={
            "overview_url": overview,
            "max_pages": 2,
            "selectors": {
                "title": "h1",
                "application_state": ".status",
                "deadline": ".deadline",
                "event_start_date": ".event-start",
                "event_end_date": ".event-end",
                "requirements_text": ".requirements",
            },
            "state_rules": [{"state": "application-open", "pattern": "(?i)applications? open"}],
            "coverage": {"min_results": 1, "max_results": 1},
            "programs": [
                {
                    "application_url": application,
                    "program_family_id": "schema-program",
                    "cycle_id": "2027-cycle",
                }
            ],
        },
    )
    sync_sources_to_db(conn, [spec])
    summary = RunSummary(run_id="program-schema-run", started_at="2026-09-01T00:00:00Z")
    Pipeline(conn, engine_config, summary.run_id, summary).process_source(spec, fetcher)
    from opportunity_discovery.runner import finalize_run

    finalize_run(conn, engine_config, summary.run_id, summary)

    registry = load_registry()
    output = engine_config.paths.output_dir
    candidate_schema = json.loads((SCHEMA_DIR / "candidate.schema.json").read_text(encoding="utf-8"))
    delta_schema = json.loads((SCHEMA_DIR / "delta-packet.schema.json").read_text(encoding="utf-8"))
    manifest_schema = json.loads((SCHEMA_DIR / "export-manifest.schema.json").read_text(encoding="utf-8"))
    candidate = json.loads((output / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    delta = json.loads((output / "delta_packet.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "export_manifest.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(candidate_schema, registry=registry).validate(candidate)
    jsonschema.Draft202012Validator(delta_schema, registry=registry).validate(delta)
    jsonschema.Draft202012Validator(manifest_schema, registry=registry).validate(manifest)
    assert candidate["program_family_id"] == "schema-program"
    assert candidate["change_events"] == ["new"]
    conn.close()
