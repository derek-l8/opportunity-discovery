"""Public source registry loading (config/sources.toml)."""
from __future__ import annotations

import tomllib
from datetime import UTC
from pathlib import Path

from .models import SourceSpec

REQUIRED_SOURCE_KEYS = {"source_id", "display_name", "organization", "adapter"}
KNOWN_SOURCE_KEYS = REQUIRED_SOURCE_KEYS | {
    "landing_url", "endpoint_config", "categories", "tags", "cadence_hours",
    "enabled", "official_source", "rate_limit_min_seconds", "last_validated",
    "validation_status", "provenance_note", "quarantine_reason",
}


def load_sources(sources_file: Path) -> tuple[list[SourceSpec], list[str]]:
    """Load and validate the registry. Returns (sources, errors).

    Disabled/quarantined sources are still returned so health reporting can
    show them; callers decide whether to fetch.
    """
    errors: list[str] = []
    if not sources_file.exists():
        return [], [f"sources file not found: {sources_file}"]
    with open(sources_file, "rb") as fh:
        data = tomllib.load(fh)
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        return [], ["'sources' must be an array of tables"]
    sources: list[SourceSpec] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(raw_sources):
        unknown = set(entry) - KNOWN_SOURCE_KEYS
        for key in unknown:
            errors.append(f"sources[{i}] ({entry.get('source_id', '?')}): unknown key '{key}'")
        missing = REQUIRED_SOURCE_KEYS - set(entry)
        if missing:
            errors.append(f"sources[{i}]: missing required keys {sorted(missing)}")
            continue
        sid = str(entry["source_id"])
        if sid in seen_ids:
            errors.append(f"duplicate source_id: {sid}")
            continue
        seen_ids.add(sid)
        spec = SourceSpec(
            source_id=sid,
            display_name=str(entry["display_name"]),
            organization=str(entry["organization"]),
            adapter=str(entry["adapter"]),
            landing_url=entry.get("landing_url"),
            endpoint_config=dict(entry.get("endpoint_config") or {}),
            categories=list(entry.get("categories") or []),
            tags=list(entry.get("tags") or []),
            cadence_hours=int(entry.get("cadence_hours", 24)),
            enabled=bool(entry.get("enabled", True)),
            official_source=bool(entry.get("official_source", False)),
            rate_limit_min_seconds=float(entry.get("rate_limit_min_seconds", 0.0)),
            last_validated=entry.get("last_validated"),
            validation_status=str(entry.get("validation_status", "pending")),
            provenance_note=entry.get("provenance_note"),
            quarantine_reason=entry.get("quarantine_reason"),
        )
        errors.extend(spec.validate())
        sources.append(spec)

    ids = [s.source_id for s in sources]
    if len(set(ids)) != len(ids):
        errors.append("duplicate source_ids present (should be impossible)")
    return sources, errors


def sync_sources_to_db(conn, sources: list[SourceSpec]) -> int:  # type: ignore[no-untyped-def]
    """Upsert registry entries into the DB. Returns number of rows written."""
    import json
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    count = 0
    for s in sources:
        conn.execute(
            """
            INSERT INTO sources (source_id, display_name, organization, adapter, landing_url,
                                 endpoint_config_json, categories_json, tags_json, cadence_hours,
                                 enabled, official_source, rate_limit_min_seconds,
                                 last_validated, validation_status, provenance_note,
                                 quarantine_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                display_name=excluded.display_name,
                organization=excluded.organization,
                adapter=excluded.adapter,
                landing_url=excluded.landing_url,
                endpoint_config_json=excluded.endpoint_config_json,
                categories_json=excluded.categories_json,
                tags_json=excluded.tags_json,
                cadence_hours=excluded.cadence_hours,
                enabled=excluded.enabled,
                official_source=excluded.official_source,
                rate_limit_min_seconds=excluded.rate_limit_min_seconds,
                last_validated=excluded.last_validated,
                validation_status=excluded.validation_status,
                provenance_note=excluded.provenance_note,
                quarantine_reason=excluded.quarantine_reason,
                updated_at=excluded.updated_at
            """,
            (
                s.source_id, s.display_name, s.organization, s.adapter, s.landing_url,
                json.dumps(s.endpoint_config), json.dumps(s.categories), json.dumps(s.tags),
                s.cadence_hours, int(s.enabled), int(s.official_source),
                s.rate_limit_min_seconds, s.last_validated, s.validation_status,
                s.provenance_note, s.quarantine_reason, now,
            ),
        )
        count += 1
    conn.commit()
    return count


def due_sources(conn, sources: list[SourceSpec], *, force: bool = False) -> list[SourceSpec]:  # type: ignore[no-untyped-def]
    """Return enabled, validated sources whose cadence window has elapsed."""
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    last_success: dict[str, datetime] = {}
    try:
        rows = conn.execute(
            """
            SELECT sc.source_id AS sid, MAX(sc.checked_at) AS latest
            FROM source_checks sc JOIN sources s ON s.source_id = sc.source_id
            WHERE sc.state IN ('healthy', 'valid-empty') AND s.enabled = 1
            GROUP BY sc.source_id
            """
        ).fetchall()
        for row in rows:
            try:
                last_success[row["sid"]] = datetime.fromisoformat(row["latest"])
            except ValueError:
                continue
    except Exception:
        pass
    due: list[SourceSpec] = []
    for s in sources:
        if not s.enabled or s.quarantine_reason:
            continue
        if s.validation_status not in ("validated", "validated-empty-ok"):
            continue
        if force:
            due.append(s)
            continue
        last = last_success.get(s.source_id)
        if last is None or now - last >= timedelta(hours=s.cadence_hours):
            due.append(s)
    return due
