"""Pipeline behavior: ingestion, change detection, reconciliation, closure rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline, expected_opportunities_from_sources
from opportunity_discovery.registry import sync_sources_to_db
from tests.helpers import MockFetcher, load_fixture, make_db, source


def make_pipeline(engine_config, conn):
    run_id = "run-test"
    summary = RunSummary(run_id=run_id, started_at=datetime.now(UTC).isoformat())
    return Pipeline(conn, engine_config, run_id, summary), summary


def gh_payload(jobs: list[dict]) -> str:
    return json.dumps({"jobs": jobs})


def job(
    jid: int, title: str, url: str, content: str = "Embedded firmware in C.", location: str = "Austin, TX"
) -> dict:
    return {
        "id": jid,
        "title": title,
        "absolute_url": url,
        "updated_at": "2026-08-01T00:00:00Z",
        "offices": [{"name": location}],
        "content": content,
    }


@pytest.fixture()
def env(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(1, "Firmware Intern", "https://boards.greenhouse.io/acme/jobs/1"),
                job(2, "Software Engineer Intern", "https://boards.greenhouse.io/acme/jobs/2"),
            ]
        ),
    )
    spec = source()
    sync_sources_to_db(conn, [spec])
    yield engine_config, conn, fetcher, spec
    conn.close()


def test_first_run_creates_new_records(env):
    cfg, conn, fetcher, spec = env
    pipeline, summary = make_pipeline(cfg, conn)
    pipeline.process_source(spec, fetcher)
    assert summary.opportunities_new == 2
    assert summary.records_seen == 2
    rows = conn.execute("SELECT change_type, lead_state FROM opportunities").fetchall()
    assert {r["change_type"] for r in rows} == {"new"}
    assert {r["lead_state"] for r in rows} == {"unverified-lead"}
    # tracking params stripped / canonical url normalized on storage
    urls = {r["canonical_url"] for r in conn.execute("SELECT canonical_url FROM opportunities")}
    assert all(u.startswith("https://boards.greenhouse.io/acme/jobs/") for u in urls)
    check = conn.execute("SELECT * FROM source_checks").fetchone()
    assert check["records_seen"] == 2
    assert check["new_records"] == 2
    assert check["changed_records"] == 0
    assert check["duration_ms"] >= 0
    assert check["pages_fetched"] == 1
    assert summary.detail["sources"][spec.source_id]["records_new"] == 2


def test_continuation_organization_repairs_on_successful_reobservation(engine_config, tmp_path):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    url = "https://raw.example.org/board.html"
    fetcher.add(url, 200, load_fixture("github_continuation.html"))
    spec = source(
        source_id="gh-continuation",
        adapter="githublist",
        official_source=False,
        organization="Community aggregator",
        endpoint_config={"url": url, "format": "html_table"},
    )
    sync_sources_to_db(conn, [spec])
    pipeline, _ = make_pipeline(engine_config, conn)
    pipeline.process_source(spec, fetcher)
    original = conn.execute(
        "SELECT opportunity_id FROM opportunities WHERE title='Hardware Intern'"
    ).fetchone()["opportunity_id"]
    conn.execute("UPDATE opportunities SET organization='↳' WHERE opportunity_id=?", (original,))
    conn.commit()

    pipeline, summary = make_pipeline(engine_config, conn)
    pipeline.process_source(spec, fetcher)
    repaired = conn.execute(
        "SELECT opportunity_id, organization, change_type FROM opportunities WHERE opportunity_id=?",
        (original,),
    ).fetchone()
    assert repaired["opportunity_id"] == original
    assert repaired["organization"] == "Acme Circuits"
    assert repaired["change_type"] == "materially-changed"
    assert summary.opportunities_changed == 1
    detail = conn.execute(
        "SELECT changed_fields_json FROM changes WHERE opportunity_id=? ORDER BY change_id DESC LIMIT 1",
        (original,),
    ).fetchone()["changed_fields_json"]
    assert json.loads(detail)["organization"] == {"old": "↳", "new": "Acme Circuits"}
    conn.close()


def test_large_greenhouse_board_keeps_id_and_failed_refresh_preserves_state(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    fetcher.cfg.fetch.max_response_bytes = 1_024
    spec = source(endpoint_config={"board": "acmesilicon", "max_response_bytes": 4_096})
    sync_sources_to_db(conn, [spec])
    url = "https://boards.greenhouse.io/acmesilicon/jobs/77"

    def payload(content: str, total: int = 1) -> str:
        return json.dumps(
            {"jobs": [job(77, "Firmware Intern", url, content=content)], "meta": {"total": total}}
        )

    try:
        fetcher.add("https://boards-api.greenhouse.io", 200, payload("Firmware in C " * 120))
        first = RunSummary(run_id="large-board-1", started_at=datetime.now(UTC).isoformat())
        Pipeline(conn, engine_config, first.run_id, first).process_source(spec, fetcher)
        initial = conn.execute("SELECT opportunity_id, description_hash FROM opportunities").fetchone()
        assert first.sources_succeeded == 1 and first.opportunities_new == 1
        assert initial is not None

        fetcher.add("https://boards-api.greenhouse.io", 200, payload("Firmware in Rust " * 120))
        second = RunSummary(run_id="large-board-2", started_at=datetime.now(UTC).isoformat())
        Pipeline(conn, engine_config, second.run_id, second).process_source(spec, fetcher)
        changed = conn.execute("SELECT opportunity_id, description_hash FROM opportunities").fetchone()
        assert second.sources_succeeded == 1 and second.opportunities_new == 0
        assert changed["opportunity_id"] == initial["opportunity_id"]
        assert changed["description_hash"] != initial["description_hash"]
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
        assert conn.execute("SELECT source_id FROM provenance").fetchone()[0] == spec.source_id

        fetcher.add("https://boards-api.greenhouse.io", 200, payload("Incomplete " * 120, total=2))
        third = RunSummary(run_id="large-board-3", started_at=datetime.now(UTC).isoformat())
        Pipeline(conn, engine_config, third.run_id, third).process_source(spec, fetcher)
        after_failure = conn.execute("SELECT opportunity_id, description_hash FROM opportunities").fetchone()
        assert third.sources_failed == 1 and third.opportunities_changed == 0
        assert tuple(after_failure) == tuple(changed)
        check = conn.execute(
            "SELECT state, truncated FROM source_checks WHERE run_id=?", (third.run_id,)
        ).fetchone()
        assert check["state"] == "coverage-warning" and check["truncated"] == 1
    finally:
        conn.close()


def test_second_identical_run_no_new_delta(env):
    cfg, conn, fetcher, spec = env
    p1, s1 = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)
    p2, s2 = make_pipeline(cfg, conn)
    p2.process_source(spec, fetcher)
    assert s2.opportunities_new == 0
    assert s2.opportunities_changed == 0
    changes = conn.execute("SELECT change_type FROM changes").fetchall()
    assert {c["change_type"] for c in changes} == {"new"}


def test_material_change_detected_once_with_field_detail(env):
    cfg, conn, fetcher, spec = env
    p1, _ = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)

    new_content = "Embedded firmware in Rust for microcontrollers."
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(1, "Firmware Intern", "https://boards.greenhouse.io/acme/jobs/1", content=new_content),
                job(2, "Software Engineer Intern", "https://boards.greenhouse.io/acme/jobs/2"),
            ]
        ),
    )
    p2, s2 = make_pipeline(cfg, conn)
    p2.process_source(spec, fetcher)
    assert s2.opportunities_changed == 1
    scored = conn.execute(
        "SELECT requested_components_json, effort_estimate, signals_json FROM opportunities "
        "WHERE title='Firmware Intern'"
    ).fetchone()
    assert json.loads(scored["requested_components_json"]) == []
    assert scored["effort_estimate"] == "unknown"
    assert json.loads(scored["signals_json"])["effort_estimate"] == "unknown"
    row = conn.execute(
        "SELECT change_type, changed_fields_json FROM changes WHERE run_id=? AND change_type != 'new'",
        ("run-test",),
    ).fetchone()
    assert row["change_type"] == "materially-changed"
    detail = json.loads(row["changed_fields_json"])
    assert "description" in detail

    # third identical run: no further changes
    p3, s3 = make_pipeline(cfg, conn)
    p3.process_source(spec, fetcher)
    assert s3.opportunities_changed == 0


def test_material_change_refreshes_requested_components_and_effort(env):
    cfg, conn, fetcher, spec = env
    p1, _ = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)

    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(
                    1,
                    "Firmware Intern",
                    "https://boards.greenhouse.io/acme/jobs/1",
                    content="Upload a resume, cover letter, transcript, and essay.",
                ),
                job(2, "Software Engineer Intern", "https://boards.greenhouse.io/acme/jobs/2"),
            ]
        ),
    )
    p2, _ = make_pipeline(cfg, conn)
    p2.process_source(spec, fetcher)
    row = conn.execute(
        "SELECT requested_components_json, effort_estimate, signals_json FROM opportunities "
        "WHERE title='Firmware Intern'"
    ).fetchone()
    requested = json.loads(row["requested_components_json"])
    signals = json.loads(row["signals_json"])
    assert requested == ["resume", "cover-letter", "transcript", "essay"]
    assert signals["requested_components"] == requested
    assert row["effort_estimate"] == signals["effort_estimate"] == "substantial"


def test_deadline_change_classified_separately(engine_config, tmp_path):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    feed = {
        "jobs": [
            {
                "title": "Quant Intern 2027",
                "url": "https://quant.example.com/apply/9",
                "deadline": "2026-09-01",
            }
        ]
    }
    fetcher.add("https://quant.example.com/feed.json", 200, json.dumps(feed))
    from tests.helpers import source as src

    spec = src(
        source_id="json-quant",
        organization="Quant Co",
        adapter="jsonfeed",
        endpoint_config={"url": "https://quant.example.com/feed.json", "records_path": "jobs"},
    )
    sync_sources_to_db(conn, [spec])

    p1, _ = make_pipeline(engine_config, conn)
    p1.process_source(spec, fetcher)
    opp_id = conn.execute("SELECT opportunity_id FROM opportunities").fetchone()["opportunity_id"]
    conn.execute("DELETE FROM changes")

    feed["jobs"][0]["deadline"] = "2026-09-15"
    fetcher.add("https://quant.example.com/feed.json", 200, json.dumps(feed))
    p2, _ = make_pipeline(engine_config, conn)
    p2.process_source(spec, fetcher)
    row = conn.execute(
        "SELECT change_type FROM changes WHERE opportunity_id=? AND change_type != 'new'", (opp_id,)
    ).fetchone()
    assert row["change_type"] == "deadline-changed"
    conn.close()


def test_missing_record_does_not_close_after_failed_run(env):
    cfg, conn, fetcher, spec = env
    p1, _ = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)

    # source check FAILS while listing only job 1 -> must not close job 2
    fetcher.routes.clear()
    fetcher.add("https://boards-api.greenhouse.io", 503, "upstream timeout")
    p2, s2 = make_pipeline(cfg, conn)
    p2.process_source(spec, fetcher)
    expected = expected_opportunities_from_sources(conn, [spec.source_id])
    p2.detect_closures(set(), expected)  # source failed -> not in successful set
    assert s2.sources_failed == 1
    active = {
        r["opportunity_id"] for r in conn.execute("SELECT opportunity_id FROM opportunities WHERE active=1")
    }
    assert len(active) == 2


def test_conservative_closure_after_consecutive_successes(env):
    cfg, conn, fetcher, spec = env
    cfg.changes.closed_after_consecutive_successes = 2
    p1, _ = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)

    # two consecutive SUCCESSFUL checks that no longer list job 2
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload([job(1, "Firmware Intern", "https://boards.greenhouse.io/acme/jobs/1")]),
    )
    for _ in range(2):
        p, s = make_pipeline(cfg, conn)
        p.process_source(spec, fetcher)
        expected = expected_opportunities_from_sources(conn, [spec.source_id])
        p.detect_closures({spec.source_id}, expected)
    closed = conn.execute("SELECT change_type FROM opportunities WHERE active=0").fetchall()
    assert len(closed) == 1
    assert closed[0]["change_type"] == "apparently-closed"

    # reappearing record is reopened
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(1, "Firmware Intern", "https://boards.greenhouse.io/acme/jobs/1"),
                job(2, "Software Engineer Intern", "https://boards.greenhouse.io/acme/jobs/2"),
            ]
        ),
    )
    p, s = make_pipeline(cfg, conn)
    p.process_source(spec, fetcher)
    expected = expected_opportunities_from_sources(conn, [spec.source_id])
    p.detect_closures({spec.source_id}, expected)
    reopened = conn.execute("SELECT change_type FROM changes WHERE change_type='reopened'").fetchall()
    assert reopened


def test_multisource_closure_requires_threshold_misses_from_all_sources(tmp_path, engine_config):
    conn = make_db(tmp_path)
    engine_config.changes.closed_after_consecutive_successes = 2
    url = "https://boards.greenhouse.io/hw/jobs/11"
    official = source(
        source_id="greenhouse-hw",
        display_name="HW",
        organization="HW",
        endpoint_config={"board": "hw"},
        official_source=True,
    )
    aggregate = source(
        source_id="csv-hw",
        display_name="HW aggregate",
        organization="HW aggregate",
        adapter="csvfeed",
        endpoint_config={"url": "https://agg.example.org/list.csv"},
        official_source=False,
    )
    sync_sources_to_db(conn, [official, aggregate])
    official_fetcher = MockFetcher()
    official_fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload([job(11, "Hardware Intern", url)]),
    )
    aggregate_fetcher = MockFetcher()
    aggregate_fetcher.add(
        "https://agg.example.org/list.csv",
        200,
        f"company,title,url\nHW,Hardware Intern,{url}\n",
    )
    initial, _ = make_pipeline(engine_config, conn)
    initial.process_source(official, official_fetcher)
    initial.process_source(aggregate, aggregate_fetcher)
    assert conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"] == 1

    official_fetcher.add("https://boards-api.greenhouse.io", 200, gh_payload([]))
    for _ in range(2):
        pipeline, _ = make_pipeline(engine_config, conn)
        pipeline.process_source(official, official_fetcher)
        expected = expected_opportunities_from_sources(conn, [official.source_id])
        pipeline.detect_closures({official.source_id}, expected)
    assert conn.execute("SELECT active FROM opportunities").fetchone()["active"] == 1

    # A miss followed by an observation through the duplicate identity resets
    # the aggregate source without disturbing the official source's misses.
    aggregate_fetcher.add("https://agg.example.org/list.csv", 200, "company,title,url\n")
    missed, _ = make_pipeline(engine_config, conn)
    missed.process_source(aggregate, aggregate_fetcher)
    expected = expected_opportunities_from_sources(conn, [aggregate.source_id])
    missed.detect_closures({aggregate.source_id}, expected)
    aggregate_fetcher.add(
        "https://agg.example.org/list.csv",
        200,
        f"company,title,url\nHW,Hardware Intern,{url}\n",
    )
    observed, _ = make_pipeline(engine_config, conn)
    observed.process_source(aggregate, aggregate_fetcher)
    expected = expected_opportunities_from_sources(conn, [aggregate.source_id])
    observed.detect_closures({aggregate.source_id}, expected)
    aggregate_misses = conn.execute(
        "SELECT consecutive_successful_misses FROM opportunity_source_state WHERE source_id=?",
        (aggregate.source_id,),
    ).fetchone()["consecutive_successful_misses"]
    assert aggregate_misses == 0

    # A failed aggregate check preserves its counter and cannot close the record.
    aggregate_fetcher.add("https://agg.example.org/list.csv", 503, "unavailable")
    failed, _ = make_pipeline(engine_config, conn)
    failed.process_source(aggregate, aggregate_fetcher)
    expected = expected_opportunities_from_sources(conn, [aggregate.source_id])
    failed.detect_closures(set(), expected)
    assert conn.execute("SELECT active FROM opportunities").fetchone()["active"] == 1

    aggregate_fetcher.add("https://agg.example.org/list.csv", 200, "company,title,url\n")
    for _ in range(2):
        pipeline, _ = make_pipeline(engine_config, conn)
        pipeline.process_source(aggregate, aggregate_fetcher)
        expected = expected_opportunities_from_sources(conn, [aggregate.source_id])
        pipeline.detect_closures({aggregate.source_id}, expected)
    assert conn.execute("SELECT active FROM opportunities").fetchone()["active"] == 0
    states = conn.execute(
        "SELECT source_id, consecutive_successful_misses FROM opportunity_source_state"
    ).fetchall()
    assert {row["source_id"]: row["consecutive_successful_misses"] for row in states} == {
        official.source_id: 2,
        aggregate.source_id: 2,
    }
    conn.close()


def test_duplicate_reconciliation_by_normalized_url(tmp_path, engine_config):
    conn = make_db(tmp_path)
    f1 = MockFetcher()
    f1.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload([job(11, "Hardware Intern", "https://boards.greenhouse.io/hw/jobs/11?utm_source=x")]),
    )
    spec_official = source(
        source_id="greenhouse-hw",
        display_name="HW",
        organization="HW",
        endpoint_config={"board": "hw"},
        official_source=True,
    )

    f2 = MockFetcher()
    csv_body = "company,title,url\nHW Agg,Hardware Intern (agg),https://boards.greenhouse.io/hw/jobs/11\n"
    f2.add("https://agg.example.org/list.csv", 200, csv_body)
    spec_agg = source(
        source_id="csv-agg",
        display_name="Agg",
        organization="Community aggregator",
        adapter="csvfeed",
        endpoint_config={"url": "https://agg.example.org/list.csv"},
        official_source=False,
    )

    sync_sources_to_db(conn, [spec_official, spec_agg])
    p, s = make_pipeline(engine_config, conn)
    p.process_source(spec_official, f1)
    before = conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"]
    p.process_source(spec_agg, f2)
    after = conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"]
    assert before == 1 and after == 1  # merged, not duplicated
    prov_sources = {r["source_id"] for r in conn.execute("SELECT source_id FROM provenance")}
    assert {"greenhouse-hw", "csv-agg"} <= prov_sources
    dupes = conn.execute("SELECT basis FROM duplicate_decisions").fetchall()
    assert any(d["basis"] == "normalized-url-equal" for d in dupes)
    conn.close()


def test_unsafe_fuzzy_merge_prevented(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(21, "FPGA Design Intern", "https://boards.greenhouse.io/x/jobs/21"),
                job(22, "FPGA Verification Intern", "https://boards.greenhouse.io/x/jobs/22"),
            ]
        ),
    )
    spec = source(source_id="greenhouse-x", organization="X", endpoint_config={"board": "x"})
    sync_sources_to_db(conn, [spec])
    p, s = make_pipeline(engine_config, conn)
    p.process_source(spec, fetcher)
    count = conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"]
    assert count == 2  # similar titles stay separate
    decisions = conn.execute("SELECT COUNT(*) n FROM duplicate_decisions").fetchone()["n"]
    assert decisions == 0
    conn.close()


def test_multiple_source_provenance_and_aliases(tmp_path, engine_config):
    conn = make_db(tmp_path)
    fa = MockFetcher()
    fa.add(
        "https://api.lever.co/v0/postings/beta",
        200,
        json.dumps(
            [
                {
                    "id": "j9",
                    "text": "Controls Engineering Intern",
                    "hostedUrl": "https://jobs.lever.co/beta/j9",
                    "createdAt": 1754000000000,
                    "categories": {"location": "Denver, CO"},
                }
            ]
        ),
    )
    spec_a = source(
        source_id="lever-beta", organization="Beta", adapter="lever", endpoint_config={"board": "beta"}
    )
    fb = MockFetcher()
    fb.add(
        "https://gamma.example.com/feed.json",
        200,
        json.dumps(
            {"jobs": [{"title": "Controls Engineering Internship", "url": "https://jobs.lever.co/beta/j9"}]}
        ),
    )
    spec_b = source(
        source_id="json-gamma",
        organization="Gamma",
        adapter="jsonfeed",
        endpoint_config={"url": "https://gamma.example.com/feed.json", "records_path": "jobs"},
    )
    sync_sources_to_db(conn, [spec_a, spec_b])
    p, s = make_pipeline(engine_config, conn)
    p.process_source(spec_a, fa)
    p.process_source(spec_b, fb)
    prov = {r["source_id"] for r in conn.execute("SELECT source_id FROM provenance")}
    assert {"lever-beta", "json-gamma"} <= prov
    aliases = [r["value"] for r in conn.execute("SELECT value FROM aliases")]
    assert aliases  # alternate title preserved
    conn.close()


def test_stable_ids_survive_reruns(env):
    cfg, conn, fetcher, spec = env
    p1, _ = make_pipeline(cfg, conn)
    p1.process_source(spec, fetcher)
    ids1 = sorted(r["opportunity_id"] for r in conn.execute("SELECT opportunity_id FROM opportunities"))
    p2, _ = make_pipeline(cfg, conn)
    p2.process_source(spec, fetcher)
    ids2 = sorted(r["opportunity_id"] for r in conn.execute("SELECT opportunity_id FROM opportunities"))
    assert ids1 == ids2


def test_field_ownership_prevents_ping_pong(tmp_path, engine_config):
    """Aggregator and official variants of one record must not oscillate."""
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(
                    31,
                    "Hardware Intern",
                    "https://boards.greenhouse.io/h/jobs/31",
                    content="Official description version.",
                )
            ]
        ),
    )
    spec_official = source(
        source_id="greenhouse-h", organization="H", endpoint_config={"board": "h"}, official_source=True
    )
    fa = MockFetcher()
    csv_body = (
        "company,title,url,notes\n"
        "H Agg,Hardware Intern,https://boards.greenhouse.io/h/jobs/31,"
        "Aggregator blurb variant\n"
    )
    fa.add("https://agg2.example.org/list.csv", 200, csv_body)
    spec_agg = source(
        source_id="csv-agg2",
        display_name="Agg2",
        organization="Community aggregator",
        adapter="csvfeed",
        endpoint_config={"url": "https://agg2.example.org/list.csv"},
    )
    sync_sources_to_db(conn, [spec_official, spec_agg])

    p1, _ = make_pipeline(engine_config, conn)
    p1.process_source(spec_official, fetcher)
    p1.process_source(spec_agg, fa)  # merge; description differs
    changes_after_first = conn.execute(
        "SELECT COUNT(*) n FROM changes WHERE change_type != 'new'"
    ).fetchone()["n"]

    # several more alternating runs: no further material changes
    for _ in range(3):
        p, s = make_pipeline(engine_config, conn)
        p.process_source(spec_official, fetcher)
        p.process_source(spec_agg, fa)
    total = conn.execute("SELECT COUNT(*) n FROM changes WHERE change_type != 'new'").fetchone()["n"]
    assert total == changes_after_first, "field values must not ping-pong between sources"
    # official source may still legitimately update its own field later
    fetcher.add(
        "https://boards-api.greenhouse.io",
        200,
        gh_payload(
            [
                job(
                    31,
                    "Hardware Intern",
                    "https://boards.greenhouse.io/h/jobs/31",
                    content="Officially revised description.",
                )
            ]
        ),
    )
    p, s = make_pipeline(engine_config, conn)
    p.process_source(spec_official, fetcher)
    assert s.opportunities_changed == 1
    conn.close()


def test_intra_batch_duplicate_urls_do_not_churn(tmp_path, engine_config):
    """Same source listing one URL twice (title + read-more) must not oscillate."""
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    payload = json.dumps(
        {
            "jobs": [
                {
                    "title": "Controls Intern",
                    "url": "https://h.example.com/role/1",
                    "description": "Variant A",
                },
                {"title": "Read more", "url": "https://h.example.com/role/1", "description": "Variant B"},
            ]
        }
    )
    fetcher.add("https://h.example.com/feed.json", 200, payload)
    spec = source(
        source_id="json-h",
        organization="H",
        adapter="jsonfeed",
        endpoint_config={"url": "https://h.example.com/feed.json", "records_path": "jobs"},
    )
    sync_sources_to_db(conn, [spec])
    p1, _ = make_pipeline(engine_config, conn)
    p1.process_source(spec, fetcher)
    conn.execute("DELETE FROM changes")
    for _ in range(3):
        p, s = make_pipeline(engine_config, conn)
        p.process_source(spec, fetcher)
    n = conn.execute("SELECT COUNT(*) n FROM changes WHERE change_type != 'new'").fetchone()["n"]
    assert n == 0, "same-source duplicate listings must not produce changes"
    assert conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"] == 1
    conn.close()
