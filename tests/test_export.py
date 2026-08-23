import json

from tests.conftest import MockFetcher, make_db, source

from opportunity_discovery.export import export_all, is_review_queue_member
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db


def seed(engine_config, tmp_path, payload: str):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    fetcher.add("https://boards-api.greenhouse.io", 200, payload)
    spec = source()
    sync_sources_to_db(conn, [spec])
    summary = RunSummary(run_id="run-x", started_at="2026-08-23T00:00:00Z")
    p = Pipeline(conn, engine_config, "run-x", summary)
    p.process_source(spec, fetcher)
    return conn


def test_exports_written_atomically_and_deterministic(engine_config, tmp_path):
    conn = seed(engine_config, tmp_path, json.dumps({"jobs": [
        {"id": 1, "title": "Firmware Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"}]}))
    a = export_all(conn, engine_config, "run-x")
    b = export_all(conn, engine_config, "run-x")
    for artifact in ("candidates", "review_queue"):
        assert a[artifact]["sha256"] == b[artifact]["sha256"], "output must be deterministic"
        assert (tmp_path / "output" / f"{artifact.replace('_', '_')}.jsonl").exists()
    # no temp leftovers
    leftovers = list((tmp_path / "output").glob("*.tmp"))
    assert not leftovers


def test_delta_packet_second_run_is_empty(engine_config, tmp_path):
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    payload = json.dumps({"jobs": [
        {"id": 1, "title": "Firmware Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},
        {"id": 2, "title": "Software Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]})
    fetcher.add("https://boards-api.greenhouse.io", 200, payload)
    spec = source()
    sync_sources_to_db(conn, [spec])
    s1 = RunSummary(run_id="run-1", started_at="2026-08-23T00:00:00Z")
    Pipeline(conn, engine_config, "run-1", s1).process_source(spec, fetcher)

    first = export_all(conn, engine_config, "run-1")
    assert first["delta_packet"]["count"] == 2  # both are new

    second = export_all(conn, engine_config, "run-2")
    assert second["delta_packet"]["count"] == 0  # identical rerun -> empty delta

    # material change produces exactly one delta entry again
    changed = json.dumps({"jobs": [
        {"id": 1, "title": "Senior Firmware Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},
        {"id": 2, "title": "Software Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]})
    fetcher.add("https://boards-api.greenhouse.io", 200, changed)
    s3 = RunSummary(run_id="run-3", started_at="2026-08-24T00:00:00Z")
    Pipeline(conn, engine_config, "run-3", s3).process_source(spec, fetcher)
    third = export_all(conn, engine_config, "run-3")
    assert third["delta_packet"]["count"] == 1
    conn.close()


def test_packet_pagination_continuation(engine_config, tmp_path):
    engine_config.export.packet_char_limit = 1500
    jobs = [{"id": i,
             "title": f"FPGA Design Verification Internship Position Number {i}",
             "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{i}",
             "content": "detailed description " * 20}
            for i in range(1, 12)]
    conn = seed(engine_config, tmp_path, json.dumps({"jobs": jobs}))
    export_all(conn, engine_config, "run-x")
    out_dir = tmp_path / "output"
    page1 = json.loads((out_dir / "delta_packet.json").read_text(encoding="utf-8"))
    total = page1["pagination"]["total_pages"]
    assert total > 1
    seen_ids = set(page1["candidates"][0].keys())
    assert "opportunity_id" in seen_ids
    count_in_packets = len(page1["candidates"])
    for p in range(2, total + 1):
        doc = json.loads((out_dir / f"delta_packet.p{p}.json").read_text(encoding="utf-8"))
        count_in_packets += len(doc["candidates"])
    assert count_in_packets == 11, "pagination must never silently truncate"
    assert page1["counts"]["delta_after_filtering"] == 11


def test_review_queue_membership_reasons(engine_config, tmp_path):
    conn = seed(engine_config, tmp_path, json.dumps({"jobs": [
        {"id": 1, "title": "Firmware Intern",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},
        {"id": 2, "title": "Office Administrator Assistant",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]}))
    rows = {r["title"]: r for r in conn.execute("SELECT * FROM opportunities")}
    member_relevant, reasons = is_review_queue_member(rows["Firmware Intern"])
    assert member_relevant
    member_irrelevant, _ = is_review_queue_member(rows["Office Administrator Assistant"])
    assert not member_irrelevant
    # excluded records stay in candidates but leave the review queue
    conn.execute("UPDATE opportunities SET reason_codes_json=? WHERE title=?",
                 (json.dumps(["exclude:school-term-coop"]), "Firmware Intern"))
    refreshed = conn.execute("SELECT * FROM opportunities WHERE title=?",
                             ("Firmware Intern",)).fetchone()
    member_excluded, _ = is_review_queue_member(refreshed)
    assert not member_excluded
    conn.close()


def test_candidates_include_excluded_records(engine_config, tmp_path):
    conn = seed(engine_config, tmp_path, json.dumps({"jobs": [
        {"id": 1, "title": "Spring 2027 Co-op: Hardware Engineer",
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"}]}))
    info = export_all(conn, engine_config, "run-x")
    assert info["candidates"]["count"] == 1  # kept in SQLite + full export
    review = [json.loads(line) for line in
              (tmp_path / "output" / "review_queue.jsonl").read_text().splitlines()]
    assert all("exclude:school-term-coop" not in (r.get("reason_codes") or [])
               or False for r in review)  # suppressed from queue with reason code
    cand = [json.loads(line) for line in
            (tmp_path / "output" / "candidates.jsonl").read_text().splitlines()]
    assert any("exclude:school-term-coop" in (c.get("reason_codes") or []) for c in cand)
