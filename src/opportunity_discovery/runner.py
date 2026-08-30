"""Deterministic end-to-end workflow shared by the CLI and scheduled runs."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from . import db as dbm
from .config import EngineConfig
from .export import export_all
from .http_client import Fetcher
from .models import RunSummary
from .pipeline import Pipeline, expected_opportunities_from_sources
from .registry import due_sources, load_sources, sync_sources_to_db

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    return "run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def workflow_exit_code(summary: RunSummary) -> int:
    """Tolerant scheduling contract shared by `opdisc run` and `opdisc collect`.

    - 0 when no source failed, no sources were due, or at least one
      attempted source succeeded (partial failure is tolerated by design;
      per-source health records the failures).
    - 1 only when sources were attempted and every attempt failed.
    Fatal/configuration errors return 2 before this helper is consulted;
    a competing lock returns 3 from the CLI.
    """
    if summary.sources_attempted and summary.sources_failed == summary.sources_attempted:
        return 1
    return 0


def ensure_ready(cfg: EngineConfig) -> sqlite3.Connection:
    """Initialize/migrate storage and sync the registry into the DB."""
    conn = dbm.connect(cfg.paths.data_dir / "opdisc.sqlite3")
    dbm.migrate(conn)
    sources, errors = load_sources(cfg.sources_file)
    if errors:
        for err in errors:
            log.warning("registry warning: %s", err)
    sync_sources_to_db(conn, sources)
    return conn


def run_collect(
    conn: sqlite3.Connection,
    cfg: EngineConfig,
    run_id: str,
    summary: RunSummary,
    *,
    force: bool = False,
    fetcher: Fetcher | None = None,
) -> RunSummary:
    """Fetch due sources and ingest. Isolated per source."""
    sources, errors = load_sources(cfg.sources_file)
    for err in errors:
        log.warning("registry warning: %s", err)
    targets = due_sources(conn, sources, force=force)
    summary.detail["due_sources"] = len(targets)

    own_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(cfg, conn=conn)
    try:
        pipeline = Pipeline(conn, cfg, run_id, summary)
        successful = set()
        expected = expected_opportunities_from_sources(conn, [s.source_id for s in targets])
        for spec in targets:
            try:
                pipeline.process_source(spec, fetcher)
            except Exception as exc:  # absolute isolation boundary
                log.exception("unexpected failure processing %s", spec.source_id)
                summary.sources_failed += 1
                summary.detail.setdefault("failures", {})[spec.source_id] = str(exc)
            row = conn.execute(
                "SELECT state FROM source_checks WHERE source_id=? AND run_id=?"
                " ORDER BY check_id DESC LIMIT 1",
                (spec.source_id, run_id),
            ).fetchone()
            if row and row["state"] in ("healthy", "valid-empty"):
                successful.add(spec.source_id)
        pipeline.detect_closures(successful, expected)
    finally:
        if own_fetcher:
            fetcher.close()
    return summary


def finalize_run(conn: sqlite3.Connection, cfg: EngineConfig, run_id: str, summary: RunSummary) -> None:
    """Write exports + run summary atomically; persist run row."""
    artifacts = export_all(conn, cfg, run_id)
    summary.review_queue_count = artifacts.get("review_queue", {}).get("count", 0)
    summary.finished_at = _now()
    existing = conn.execute("SELECT 1 FROM collection_runs WHERE run_id=?", (run_id,)).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE collection_runs SET finished_at=?, mode=?, exit_code=?,
                sources_attempted=?, sources_succeeded=?, sources_failed=?,
                records_seen=?, opportunities_new=?, opportunities_changed=?,
                opportunities_closed=?, summary_json=?
            WHERE run_id=?
            """,
            (
                summary.finished_at,
                summary.mode,
                summary.exit_code,
                summary.sources_attempted,
                summary.sources_succeeded,
                summary.sources_failed,
                summary.records_seen,
                summary.opportunities_new,
                summary.opportunities_changed,
                summary.opportunities_closed,
                json.dumps(summary.to_dict()["detail"]),
                run_id,
            ),
        )
    else:
        conn.execute(
            """
        INSERT INTO collection_runs (run_id, started_at, finished_at, mode, exit_code,
            sources_attempted, sources_succeeded, sources_failed, records_seen,
            opportunities_new, opportunities_changed, opportunities_closed, summary_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                run_id,
                summary.started_at,
                summary.finished_at,
                summary.mode,
                summary.exit_code,
                summary.sources_attempted,
                summary.sources_succeeded,
                summary.sources_failed,
                summary.records_seen,
                summary.opportunities_new,
                summary.opportunities_changed,
                summary.opportunities_closed,
                json.dumps(summary.to_dict()["detail"]),
            ),
        )
    # run_summary.json artifact
    from pathlib import Path

    out_path = Path(cfg.paths.output_dir) / "run_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".json.tmp")
    doc = {"schema_version": "1.0", **summary.to_dict(), "artifacts": {k: v for k, v in artifacts.items()}}
    tmp.write_text(json.dumps(doc, sort_keys=True, indent=2), encoding="utf-8")
    import os

    os.replace(tmp, out_path)
    conn.commit()


def run_full_workflow(
    conn: sqlite3.Connection,
    cfg: EngineConfig,
    *,
    force: bool = False,
    fetcher: Fetcher | None = None,
    do_export: bool = True,
) -> tuple[int, RunSummary]:
    """The normal deterministic workflow behind `opdisc run` / Task Scheduler."""
    run_id = new_run_id()
    summary = RunSummary(run_id=run_id, started_at=_now())
    exit_code = 0
    try:
        sources, errors = load_sources(cfg.sources_file)
        fatal_errors = [e for e in errors if "missing required keys" in e or "not found" in e]
        if fatal_errors:
            summary.exit_code = 2
            summary.detail["fatal"] = fatal_errors
            return 2, summary
        run_collect(conn, cfg, run_id, summary, force=force, fetcher=fetcher)
        exit_code = workflow_exit_code(summary)
        if do_export:
            finalize_run(conn, cfg, run_id, summary)
        else:
            summary.finished_at = _now()
            conn.execute(
                """UPDATE collection_runs SET finished_at=?, mode=?, exit_code=?,
                   sources_attempted=?, sources_succeeded=?, sources_failed=?,
                   records_seen=?, opportunities_new=?, opportunities_changed=?,
                   opportunities_closed=?, summary_json=?
                   WHERE run_id=?""",
                (
                    summary.finished_at,
                    summary.mode,
                    exit_code,
                    summary.sources_attempted,
                    summary.sources_succeeded,
                    summary.sources_failed,
                    summary.records_seen,
                    summary.opportunities_new,
                    summary.opportunities_changed,
                    summary.opportunities_closed,
                    json.dumps(summary.detail),
                    run_id,
                ),
            )
            conn.commit()
    except Exception as exc:
        log.exception("workflow failed")
        summary.exit_code = 2
        summary.detail["fatal"] = str(exc)
        return 2, summary
    summary.exit_code = exit_code
    return exit_code, summary
