"""Versioned exports for the downstream private AI layer.

Artifacts are written atomically (temp file + os.replace). See
docs/INTEGRATION_CONTRACT.md and schemas/*.schema.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import EngineConfig

SCHEMA_VERSION = "1.0"

EXPORT_CHANGE_TYPES = {"new", "materially-changed", "deadline-changed", "reopened"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on POSIX and Windows


def _row_to_candidate(row: sqlite3.Row, excerpt_chars: int) -> dict[str, Any]:
    def _j(key: str, default: Any) -> Any:
        try:
            return json.loads(row[key])
        except (TypeError, ValueError):
            return default

    excerpt = row["description_excerpt"]
    if isinstance(excerpt, str) and len(excerpt) > excerpt_chars:
        excerpt = excerpt[:excerpt_chars]
    return {
        "opportunity_id": row["opportunity_id"],
        "lead_state": row["lead_state"],
        "organization": row["organization"],
        "title": row["title"],
        "aliases": _j("aliases_json", []),
        "category": row["category"],
        "canonical_url": row["canonical_url"],
        "official_url": row["official_url"],
        "provider": row["provider"],
        "provider_req_id": row["provider_req_id"],
        "location_text": row["location_text"],
        "location_components": {
            "city": row["location_city"],
            "state": row["location_state"],
            "country": row["location_country"],
        },
        "remote_signal": row["remote_signal"] or "unknown",
        "season": row["season"],
        "employment_type": row["employment_type"],
        "posted_date": row["posted_date"],
        "stated_deadline": row["deadline"],
        "deadline_timezone": row["deadline_tz"] or "unknown",
        "compensation_text": row["compensation_text"],
        "relocation_text": row["relocation_text"],
        "description_excerpt": excerpt,
        "description_hash": row["description_hash"],
        "class_year_language": row["class_year_language"],
        "graduation_window_language": row["graduation_window_language"],
        "major_language": row["major_language"],
        "work_auth_language": row["work_auth_language"],
        "requested_application_components": _j("requested_components_json", []),
        "application_effort_estimate": row["effort_estimate"] or "unknown",
        "role_family_tags": _j("role_family_tags_json", []),
        "signals": _j("signals_json", {}),
        "score_components": _j("score_components_json", {}),
        "generic_score": row["generic_score"],
        "reason_codes": _j("reason_codes_json", []),
        "change_type": row["change_type"],
        "active": bool(row["active"]),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "last_changed": row["last_changed"],
        "last_successful_check": row["last_successful_check"],
    }


def attach_provenance(conn: sqlite3.Connection, candidate: dict[str, Any]) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT source_id, source_url, evidence, first_seen, last_seen FROM provenance"
        " WHERE opportunity_id = ? ORDER BY first_seen",
        (candidate["opportunity_id"],),
    ).fetchall()
    candidate["provenance"] = [
        {
            "source_id": r["source_id"],
            "url": r["source_url"],
            "evidence": r["evidence"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]
    return candidate


def _iter_candidates(conn: sqlite3.Connection) -> Iterator[sqlite3.Row]:
    yield from conn.execute(
        "SELECT * FROM opportunities ORDER BY opportunity_id"
    )  # deterministic ordering


def is_review_queue_member(row: sqlite3.Row) -> tuple[bool, list[str]]:
    """Deterministic review-queue membership from stored reason codes/score."""
    reasons = json.loads(row["reason_codes_json"] or "[]")
    score = float(row["generic_score"] or 0.0)
    excluded_codes = [r for r in reasons if r.startswith("exclude:")]
    tags = json.loads(row["role_family_tags_json"] or "[]")
    include = (
        bool(tags)
        and not excluded_codes
        and score > 0
        and int(row["active"] or 0) == 1
    )
    return include, reasons


def export_all(conn: sqlite3.Connection, cfg: EngineConfig, run_id: str | None,
               *, output_dir: Path | None = None) -> dict[str, Any]:
    """Write all export artifacts atomically; returns artifact info."""
    out_dir = Path(output_dir) if output_dir else cfg.paths.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    written: dict[str, Any] = {}

    # ---- complete normalized candidates export -------------------------
    candidates_path = out_dir / "candidates.jsonl"
    total_count = 0
    lines: list[bytes] = []
    for row in _iter_candidates(conn):
        cand = attach_provenance(conn, _row_to_candidate(row, cfg.export.excerpt_chars))
        lines.append(json.dumps(cand, sort_keys=True).encode("utf-8"))
        total_count += 1
    payload = b"".join(line + b"\n" for line in lines)
    _atomic_write(candidates_path, payload)
    written["candidates"] = {
        "path": str(candidates_path), "count": total_count,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    # ---- review queue ----------------------------------------------------
    review_path = out_dir / "review_queue.jsonl"
    review_count = 0
    rlines: list[bytes] = []
    for row in _iter_candidates(conn):
        member, reasons = is_review_queue_member(row)
        if not member:
            continue
        cand = attach_provenance(conn, _row_to_candidate(row, cfg.export.excerpt_chars))
        rlines.append(json.dumps(cand, sort_keys=True).encode("utf-8"))
        review_count += 1
    rpayload = b"".join(line + b"\n" for line in rlines)
    _atomic_write(review_path, rpayload)
    written["review_queue"] = {
        "path": str(review_path), "count": review_count,
        "sha256": hashlib.sha256(rpayload).hexdigest(),
    }

    # ---- compact delta packet -------------------------------------------
    last_checkpoint = conn.execute(
        "SELECT exported_at, run_id FROM export_checkpoints WHERE artifact='delta'"
        " ORDER BY exported_at DESC LIMIT 1"
    ).fetchone()
    since = last_checkpoint["exported_at"] if last_checkpoint else None
    delta_rows = []
    for row in _iter_candidates(conn):
        if row["change_type"] not in EXPORT_CHANGE_TYPES:
            continue
        if since and str(row["last_changed"]) <= since:
            continue
        delta_rows.append(row)
    before_filter = len(delta_rows)

    packet_base = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "run_id": run_id,
        "since_checkpoint": since,
        "counts": {
            "total_candidates_in_store": total_count,
            "delta_before_filtering": before_filter,
        },
    }
    pages = _paginate_delta(conn, delta_rows, packet_base, cfg)
    for suffix, doc in pages:
        path = out_dir / f"delta_packet{suffix}.json"
        encoded = json.dumps(doc, sort_keys=True, indent=2).encode("utf-8")
        _atomic_write(path, encoded)
        if suffix == "":
            written["delta_packet"] = {
                "path": str(path),
                "count": len(doc.get("candidates", [])),
                "pages": len(pages),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }

    # ---- source health ----------------------------------------------------
    health_path = out_dir / "source_health.json"
    health_doc = build_source_health(conn, now)
    hpayload = json.dumps(health_doc, sort_keys=True, indent=2).encode("utf-8")
    _atomic_write(health_path, hpayload)
    written["source_health"] = {"path": str(health_path)}

    # ---- checkpoints -------------------------------------------------------
    for artifact, info in written.items():
        if artifact == "delta_packet":
            continue
        conn.execute(
            "INSERT INTO export_checkpoints (artifact, exported_at, run_id, packet_hash,"
            " counts_json) VALUES (?, ?, ?, ?, ?)",
            (
                artifact, now, run_id, info.get("sha256"),
                json.dumps({"count": info.get("count", 0)}),
            ),
        )
    # one checkpoint per delta page file so the next run compares to the newest
    for suffix, doc in pages:
        conn.execute(
            "INSERT INTO export_checkpoints (artifact, exported_at, run_id, packet_hash,"
            " counts_json) VALUES (?, ?, ?, NULL, ?)",
            (
                f"delta{suffix}", now, run_id,
                json.dumps({"count": len(doc.get("candidates", []))}),
            ),
        )
    conn.commit()
    written["run_summary_path"] = str(out_dir / "run_summary.json")
    return written


def _paginate_delta(conn: sqlite3.Connection, rows: list[sqlite3.Row],
                    base: dict[str, Any], cfg: EngineConfig) -> list[tuple[str, dict[str, Any]]]:
    limit = cfg.export.packet_char_limit
    docs: list[tuple[list[dict[str, Any]], int]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    def serialized(cands: list[dict[str, Any]]) -> int:
        return len(json.dumps({**base, "candidates": cands}, sort_keys=True))

    for row in rows:
        cand = attach_provenance(conn, _row_to_candidate(row, cfg.export.excerpt_chars))
        cand_chars = len(json.dumps(cand, sort_keys=True))
        if current and current_chars + cand_chars > limit:
            docs.append((current, current_chars))
            current, current_chars = [], 0
        current.append(cand)
        current_chars += cand_chars
    if current or not rows:
        docs.append((current, current_chars))

    total_pages = len(docs)
    pages: list[tuple[str, dict[str, Any]]] = []
    for idx, (cands, chars) in enumerate(docs):
        suffix = "" if idx == 0 else f".p{idx + 1}"
        doc = dict(base)
        doc["counts"]["delta_after_filtering"] = sum(len(d[0]) for d in docs)
        doc["estimated_chars"] = chars
        doc["pagination"] = {
            "page": idx + 1,
            "total_pages": total_pages,
            "next_file": (f"delta_packet.p{idx + 2}.json" if idx + 1 < total_pages else None),
        }
        doc["candidates"] = cands
        pages.append((suffix, doc))
    return pages


def build_source_health(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    sources = conn.execute(
        "SELECT * FROM sources ORDER BY source_id"
    ).fetchall()
    out_sources = []
    summary: dict[str, int] = {}
    for src in sources:
        last = conn.execute(
            "SELECT state, http_status, detail, checked_at FROM source_checks"
            " WHERE source_id=? ORDER BY checked_at DESC LIMIT 1",
            (src["source_id"],),
        ).fetchone()
        state: str | None
        if not int(src["enabled"] or 0):
            state = "disabled"
        elif src["quarantine_reason"]:
            state = "quarantined"
        elif last is None:
            state = "pending-check"
        else:
            state = last["state"]
        summary[state] = summary.get(state, 0) + 1
        out_sources.append(
            {
                "source_id": src["source_id"],
                "display_name": src["display_name"],
                "organization": src["organization"],
                "adapter": src["adapter"],
                "enabled": bool(src["enabled"]),
                "landing_url": src["landing_url"],
                "validation_status": src["validation_status"],
                "last_validated": src["last_validated"],
                "health_state": state,
                "last_check": dict(last) if last else None,
                "provenance_note": src["provenance_note"],
                "quarantine_reason": src["quarantine_reason"],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "summary": summary,
        "sources": out_sources,
    }
