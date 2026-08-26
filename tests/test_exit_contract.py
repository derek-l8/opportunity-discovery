"""Exit-code contract for opdisc run / collect (tolerant scheduling).

Contract (see runner.workflow_exit_code):
- 0: no source failed, nothing due, or at least one attempted source succeeded
- 1: sources were attempted but every attempt failed
- 2: configuration error or unexpected fatal failure
- 3: another run holds data/run.lock
"""
from __future__ import annotations

import os

import pytest

from opportunity_discovery.cli import main
from opportunity_discovery.models import RunSummary
from opportunity_discovery.runner import workflow_exit_code
from tests.helpers import MockFetcher, write_sources_toml


def _validated_feed_source(source_id: str, url: str) -> dict:
    return {
        "source_id": source_id,
        "display_name": source_id,
        "organization": "Org",
        "adapter": "jsonfeed",
        "endpoint_config": {"url": url, "records_path": "jobs"},
        "validation_status": "validated",
        "last_validated": "2026-08-23",
    }


@pytest.fixture()
def patched_fetcher(monkeypatch):
    fetcher = MockFetcher()
    monkeypatch.setattr(
        "opportunity_discovery.runner.Fetcher", lambda cfg, conn=None: fetcher)
    return fetcher


def _run(engine_config, *cmd: str) -> int:
    return main(["--config", str(engine_config.config_path), "--quiet", *cmd])


# --- helper unit tests -------------------------------------------------------
def test_exit_code_no_attempts_is_zero():
    s = RunSummary(run_id="r", started_at="t")
    assert workflow_exit_code(s) == 0


def test_exit_code_partial_failure_is_zero():
    s = RunSummary(run_id="r", started_at="t")
    s.sources_attempted, s.sources_succeeded, s.sources_failed = 2, 1, 1
    assert workflow_exit_code(s) == 0


def test_exit_code_all_failed_is_one():
    s = RunSummary(run_id="r", started_at="t")
    s.sources_attempted, s.sources_succeeded, s.sources_failed = 3, 0, 3
    assert workflow_exit_code(s) == 1


# --- CLI behavior ------------------------------------------------------------
def test_collect_no_due_sources_exits_zero(engine_config, capsys):
    write_sources_toml(engine_config, [{
        "source_id": "pending-a", "display_name": "A", "organization": "O",
        "adapter": "jsonfeed",
        "endpoint_config": {"url": "https://a.example/feed.json"},
        # validation_status defaults to pending -> never selected as due
    }])
    assert _run(engine_config, "collect") == 0
    capsys.readouterr()


def test_collect_all_sources_failed_exits_one(engine_config, patched_fetcher, capsys):
    patched_fetcher.add("https://bad.example/", 503, "upstream down")
    write_sources_toml(engine_config, [
        _validated_feed_source("feed-bad", "https://bad.example/feed.json")])
    assert _run(engine_config, "collect", "--force") == 1
    capsys.readouterr()


def test_run_all_sources_failed_exits_one(engine_config, patched_fetcher, capsys):
    patched_fetcher.add("https://bad.example/", 503, "upstream down")
    write_sources_toml(engine_config, [
        _validated_feed_source("feed-bad", "https://bad.example/feed.json")])
    assert _run(engine_config, "run", "--force") == 1
    capsys.readouterr()


def test_partial_failure_exits_zero(engine_config, patched_fetcher, capsys):
    patched_fetcher.add("https://ok.example/", 200,
                        '{"jobs": [{"title": "Intern", '
                        '"url": "https://ok.example/apply/1"}]}')
    patched_fetcher.add("https://bad.example/", 503, "upstream down")
    write_sources_toml(engine_config, [
        _validated_feed_source("feed-ok", "https://ok.example/feed.json"),
        _validated_feed_source("feed-bad", "https://bad.example/feed.json"),
    ])
    assert _run(engine_config, "collect", "--force") == 0
    assert _run(engine_config, "run", "--force") == 0
    capsys.readouterr()


def test_config_error_exits_two(engine_config, tmp_path, capsys):
    bad_cfg = tmp_path / "bad.toml"
    bad_cfg.write_text("fetch.max_concurrency = 99\n", encoding="utf-8")
    assert main(["--config", str(bad_cfg), "--quiet", "run"]) == 2
    assert main(["--config", str(bad_cfg), "--quiet", "collect"]) == 2
    capsys.readouterr()


def test_registry_fatal_error_exits_two(engine_config, patched_fetcher, capsys):
    # Missing required registry key is a configuration-level fatal failure.
    write_sources_toml(engine_config, [{
        "source_id": "incomplete", "display_name": "I", "adapter": "jsonfeed",
        "endpoint_config": {"url": "https://x.example/feed.json"}}])
    assert _run(engine_config, "run", "--force") == 2
    capsys.readouterr()


def test_lock_held_exits_three(engine_config, tmp_path, capsys):
    write_sources_toml(engine_config, [
        _validated_feed_source("feed-a", "https://a.example/feed.json")])
    lock_path = engine_config.paths.data_dir / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        assert _run(engine_config, "collect", "--force") == 3
        assert _run(engine_config, "run", "--force") == 3
    finally:
        lock_path.unlink(missing_ok=True)
    capsys.readouterr()
