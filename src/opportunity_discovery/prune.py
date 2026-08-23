"""Explicit retention pruning. Defaults to dry-run; durable history is kept."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def plan_prune(conn: sqlite3.Connection, *, cache_days: int, log_days: int,
               check_days: int) -> list[dict[str, object]]:
    plans = [
        ("raw_cache", "expires_at < ?", (_cutoff(0),)),
        ("raw_cache", "fetched_at < ? AND expires_at < ?", (_cutoff(cache_days), _cutoff(cache_days))),
        ("collection_runs", "started_at < ?", (_cutoff(max(log_days * 30, 90)),)),
        ("source_checks", "checked_at < ?", (_cutoff(check_days),)),
    ]
    out: list[dict[str, object]] = []
    for table, where, params in plans:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {where}",
            tuple(params),
        ).fetchone()
        if row["n"]:
            out.append({"table": table, "where": where, "rows": int(row["n"])})
    return out


def apply_prune(conn: sqlite3.Connection, plans: list[dict[str, object]]) -> int:
    deleted = 0
    for plan in plans:
        cur = conn.execute(
            f"DELETE FROM {plan['table']} WHERE {plan['where']}",
            tuple(plan["params"]),  # type: ignore[arg-type]
        )
        deleted += cur.rowcount
    conn.commit()
    return deleted
