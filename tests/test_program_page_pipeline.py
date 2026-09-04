import json

from opportunity_discovery.export import export_all
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from opportunity_discovery.runner import run_collect
from tests.helpers import MockFetcher, load_fixture, make_db, source, write_sources_toml


def program_source():
    return source(
        source_id="program-change-events",
        organization="Synthetic Organization Gamma",
        adapter="program-page",
        endpoint_config={
            "overview_url": "https://cycles.example.com/overview",
            "max_pages": 2,
            "selectors": {
                "title": "h1",
                "application_state": ".status",
                "location_text": ".location",
                "deadline": ".deadline",
                "event_start_date": ".event-start",
                "event_end_date": ".event-end",
                "requirements_text": ".requirements",
            },
            "state_rules": [
                {"state": "application-open", "pattern": "(?i)applications? open"},
                {"state": "closed", "pattern": "(?i)applications? closed"},
            ],
            "coverage": {"min_results": 1, "max_results": 1},
            "programs": [
                {
                    "application_url": "https://cycles.example.com/apply/harbor-2027",
                    "program_family_id": "cycle-program",
                    "cycle_id": "harbor-2027",
                }
            ],
        },
    )


def test_program_changes_emit_granular_events_and_optional_export_fields(engine_config, tmp_path):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    spec = program_source()
    sync_sources_to_db(conn, [spec])
    fetcher.add("https://cycles.example.com/overview", 200, "<h1>Cycle overview</h1>")
    fetcher.add(
        "https://cycles.example.com/apply/harbor-2027",
        200,
        load_fixture("program_application_open.html"),
    )
    first = RunSummary(run_id="program-run-1", started_at="2026-09-01T00:00:00Z")
    Pipeline(conn, engine_config, first.run_id, first).process_source(spec, fetcher)

    changed_page = """
    <main>
      <h1>Systems Exploration Program - Harbor 2027</h1>
      <p class="status">Applications closed</p>
      <p class="location">Mesa City, AZ, USA</p>
      <time class="deadline">2026-12-01</time>
      <time class="event-start">2027-04-01</time>
      <time class="event-end">2027-04-04</time>
      <section class="requirements">Submit two responses and one transcript.</section>
    </main>
    """
    fetcher.add("https://cycles.example.com/apply/harbor-2027", 200, changed_page)
    second = RunSummary(run_id="program-run-2", started_at="2026-09-02T00:00:00Z")
    Pipeline(conn, engine_config, second.run_id, second).process_source(spec, fetcher)

    event_rows = conn.execute(
        "SELECT change_type FROM changes WHERE run_id=? ORDER BY change_id", (second.run_id,)
    ).fetchall()
    event_types = [row["change_type"] for row in event_rows]
    assert event_types == [
        "application-closed",
        "deadline-changed",
        "requirements-changed",
        "dates-changed",
        "location-changed",
    ]
    stored = conn.execute("SELECT * FROM opportunities").fetchone()
    assert stored["change_type"] == "application-closed"
    assert json.loads(stored["last_change_events_json"]) == event_types
    assert stored["active"] == 1  # page presence and application window are separate states

    export_all(conn, engine_config, second.run_id)
    candidate = json.loads(
        (engine_config.paths.output_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert candidate["application_state"] == "closed"
    assert candidate["event_start_date"] == "2027-04-01"
    assert candidate["stated_deadline"] == "2026-12-01"
    assert candidate["change_events"] == event_types
    conn.close()


def _registry_entry(spec):
    return {
        "source_id": spec.source_id,
        "display_name": spec.display_name,
        "organization": spec.organization,
        "adapter": spec.adapter,
        "endpoint_config": spec.endpoint_config,
        "enabled": True,
        "official_source": True,
        "validation_status": "validated",
        "cadence_hours": 24,
    }


def test_program_coverage_warning_does_not_advance_closure(engine_config, tmp_path):
    conn = make_db(tmp_path)
    engine_config.changes.closed_after_consecutive_successes = 1
    spec = program_source()
    sync_sources_to_db(conn, [spec])
    write_sources_toml(engine_config, [_registry_entry(spec)])
    fetcher = MockFetcher()
    fetcher.add("https://cycles.example.com/overview", 200, "<h1>Cycle overview</h1>")
    fetcher.add(
        "https://cycles.example.com/apply/harbor-2027",
        200,
        load_fixture("program_application_open.html"),
    )

    first = RunSummary(run_id="program-coverage-1", started_at="2026-09-01T00:00:00Z")
    run_collect(conn, engine_config, first.run_id, first, force=True, fetcher=fetcher)
    assert conn.execute("SELECT active FROM opportunities").fetchone()["active"] == 1

    spec.endpoint_config["coverage"] = {
        "min_results": 1,
        "max_results": 1,
        "expected_title_patterns": [r"Unexpected Cycle$"],
    }
    write_sources_toml(engine_config, [_registry_entry(spec)])
    second = RunSummary(run_id="program-coverage-2", started_at="2026-09-02T00:00:00Z")
    run_collect(conn, engine_config, second.run_id, second, force=True, fetcher=fetcher)

    latest = conn.execute("SELECT state FROM source_checks WHERE run_id=?", (second.run_id,)).fetchone()
    closure_state = conn.execute(
        "SELECT consecutive_successful_misses FROM opportunity_source_state"
    ).fetchone()
    assert latest["state"] == "coverage-warning"
    assert second.sources_failed == 1
    assert closure_state["consecutive_successful_misses"] == 0
    assert conn.execute("SELECT active FROM opportunities").fetchone()["active"] == 1
    conn.close()


def test_program_records_are_complete_across_manifest_delta_pages(engine_config, tmp_path):
    conn = make_db(tmp_path)
    engine_config.export.packet_char_limit = 5000
    spec = program_source()
    programs = []
    fetcher = MockFetcher()
    fetcher.add("https://cycles.example.com/overview", 200, "<h1>Cycle overview</h1>")
    for index in range(4):
        cycle = f"harbor-202{7 + index}"
        url = f"https://cycles.example.com/apply/{cycle}"
        programs.append(
            {
                "application_url": url,
                "program_family_id": "cycle-program",
                "cycle_id": cycle,
            }
        )
        fetcher.add(url, 200, load_fixture("program_application_open.html"))
    spec.endpoint_config.update(
        {
            "max_pages": 5,
            "coverage": {"min_results": 4, "max_results": 4},
            "programs": programs,
        }
    )
    sync_sources_to_db(conn, [spec])
    summary = RunSummary(run_id="program-pages", started_at="2026-09-01T00:00:00Z")
    Pipeline(conn, engine_config, summary.run_id, summary).process_source(spec, fetcher)
    export_all(conn, engine_config, summary.run_id)

    output = engine_config.paths.output_dir
    manifest = json.loads((output / "export_manifest.json").read_text(encoding="utf-8"))
    delta_names = manifest["delta_packet_files"]
    assert len(delta_names) > 1
    assert delta_names == [
        "delta_packet.json",
        *[f"delta_packet.p{i}.json" for i in range(2, len(delta_names) + 1)],
    ]
    assert set(delta_names) <= {entry["filename"] for entry in manifest["files"]}

    candidates = []
    for name in delta_names:
        page = json.loads((output / name).read_text(encoding="utf-8"))
        candidates.extend(page["candidates"])
    assert len(candidates) == 4
    assert {candidate["cycle_id"] for candidate in candidates} == {
        f"harbor-202{year}" for year in range(7, 11)
    }
    assert all(candidate["program_family_id"] == "cycle-program" for candidate in candidates)
    assert all(candidate["application_state"] == "application-open" for candidate in candidates)
    conn.close()
