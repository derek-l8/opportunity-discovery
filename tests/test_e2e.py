"""End-to-end synthetic workflow: two identical runs, no false new delta."""
import json

from tests.conftest import write_sources_toml

from opportunity_discovery.runner import ensure_ready, run_full_workflow


def test_synthetic_end_to_end_twice(engine_config, tmp_path, capsys):
    fixture = tmp_path / "feed.json"
    fixture.write_text(json.dumps({"jobs": [
        {"title": "FPGA Design Intern", "url": "https://acme.example.com/apply/1",
         "season": "Summer 2027", "compensation": "$42/hr paid",
         "location": "Santa Clara, CA"},
        {"title": "Embedded Firmware Intern",
         "url": "https://acme.example.com/apply/2?utm_source=x",
         "location": "Remote, USA"},
        {"title": "Spring 2027 Co-op: Test Engineer",
         "url": "https://acme.example.com/apply/3", "location": "Austin, TX"},
    ]}), encoding="utf-8")

    write_sources_toml(engine_config, [{
        "source_id": "synthetic-acme",
        "display_name": "Synthetic Acme",
        "organization": "Acme Synthetic",
        "adapter": "jsonfeed",
        "endpoint_config": {"url": fixture.as_uri(), "records_path": "jobs"},
        "validation_status": "validated",
        "last_validated": "2026-08-23",
    }])

    from opportunity_discovery.http_client import Fetcher as RealFetcher
    real_fetcher = RealFetcher(engine_config)

    conn = ensure_ready(engine_config)
    try:
        code1, summary1 = run_full_workflow(conn, engine_config,
                                            force=True, fetcher=real_fetcher)
        assert code1 == 0, summary1.detail
        assert summary1.opportunities_new == 3
        assert summary1.review_queue_count >= 2  # coop excluded, rest relevant

        code2, summary2 = run_full_workflow(conn, engine_config,
                                            force=True, fetcher=real_fetcher)
        assert code2 == 0
        assert summary2.opportunities_new == 0, "identical rerun must not emit news"
        assert summary2.opportunities_changed == 0

        out_dir = engine_config.paths.output_dir
        packet = json.loads((out_dir / "delta_packet.json").read_text(encoding="utf-8"))
        assert packet["counts"]["total_candidates_in_store"] == 3
        assert len(packet["candidates"]) == 0  # delta since checkpoint is empty

        candidates = [json.loads(line) for line in
                      (out_dir / "candidates.jsonl").read_text().splitlines()]
        coop = [c for c in candidates if "Co-op" in c["title"]][0]
        assert "exclude:school-term-coop" in coop["reason_codes"]
        review_ids = {json.loads(line)["opportunity_id"] for line in
                      (out_dir / "review_queue.jsonl").read_text().splitlines()}
        assert coop["opportunity_id"] not in review_ids
        # stable ids across runs
        ids_a = sorted(c["opportunity_id"] for c in candidates)
        candidates_b = [json.loads(line) for line in
                        (out_dir / "candidates.jsonl").read_text().splitlines()]
        assert ids_a == sorted(c["opportunity_id"] for c in candidates_b)

        health = json.loads((out_dir / "source_health.json").read_text(encoding="utf-8"))
        assert health["summary"].get("healthy") == 1
    finally:
        conn.close()
