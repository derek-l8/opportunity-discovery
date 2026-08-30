"""Validate real export artifacts against the shipped JSON Schemas."""

import json
from pathlib import Path

import jsonschema
import pytest

from opportunity_discovery.http_client import Fetcher
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from tests.helpers import make_db, source

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


def test_delta_packet_validates(exported):
    schema = json.loads((SCHEMA_DIR / "delta-packet.schema.json").read_text(encoding="utf-8"))
    registry = load_registry()
    doc = json.loads((exported / "delta_packet.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, registry=registry).validate(doc)


def test_run_summary_and_health_validate(exported):
    registry = load_registry()
    for artifact, schema_name in (
        ("run_summary.json", "run-summary.schema.json"),
        ("source_health.json", "source-health.schema.json"),
    ):
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        doc = json.loads((exported / artifact).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, registry=registry).validate(doc)
