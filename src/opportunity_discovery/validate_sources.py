"""Live source validation: probe each candidate source and record the result.

A source counts as validated only when a live probe confirms identity,
adapter fit, expected format, and distinguishable valid-empty behavior.
Failures are recorded with reasons; they never break ordinary runs.
"""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from . import adapters as ad
from .constants import (
    VALIDATION_EMPTY_OK,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    VALIDATION_QUARANTINED,
)
from .http_client import Fetcher
from .models import SourceSpec

log = logging.getLogger(__name__)


def validate_source(spec: SourceSpec, cfg, *, timeout_grace: bool = True) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """Probe one source. Returns (status, detail)."""
    fetcher = Fetcher(cfg)
    try:
        result = ad.run_source(spec, fetcher)
    except Exception as exc:
        return VALIDATION_FAILED, f"adapter crashed: {type(exc).__name__}: {exc}"
    finally:
        fetcher.close()
    if result.ok:
        status = VALIDATION_PASSED if result.records else VALIDATION_EMPTY_OK
        return status, f"{len(result.records)} records (HTTP {result.http_status})"
    if result.state in ("format-changed", "coverage-warning"):
        return VALIDATION_QUARANTINED, result.detail or "format changed"
    return VALIDATION_FAILED, result.detail or "check failed"


def validate_all(
    sources: list[SourceSpec],
    conn: sqlite3.Connection,
    cfg,  # type: ignore[no-untyped-def]
    concurrency: int = 6,
) -> dict[str, dict[str, str]]:
    """Validate all enabled sources concurrently; persist results."""
    results: dict[str, dict[str, str]] = {}
    today = datetime.now(UTC).date().isoformat()
    targets = [s for s in sources if s.enabled and not s.quarantine_reason]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(validate_source, s, cfg): s for s in targets}
        for fut in as_completed(futures):
            spec = futures[fut]
            try:
                status, detail = fut.result()
            except Exception as exc:
                status, detail = VALIDATION_FAILED, f"probe crashed: {exc}"
            results[spec.source_id] = {"status": status, "detail": detail}
            _persist(conn, spec.source_id, status, detail, today)
    # disabled / quarantined sources are recorded without probing
    for s in sources:
        if s.source_id in results:
            continue
        status = VALIDATION_QUARANTINED if s.quarantine_reason else "disabled"
        results[s.source_id] = {
            "status": status,
            "detail": s.quarantine_reason or "disabled by registry",
        }
        _persist(conn, s.source_id, results[s.source_id]["status"], results[s.source_id]["detail"], None)
    return results


def _persist(
    conn: sqlite3.Connection, source_id: str, status: str, detail: str, validated_on: str | None
) -> None:
    conn.execute(
        "UPDATE sources SET validation_status=?, last_validated=COALESCE(?, last_validated),"
        " updated_at=? WHERE source_id=?",
        (status, validated_on, datetime.now(UTC).isoformat(), source_id),
    )
    conn.commit()
