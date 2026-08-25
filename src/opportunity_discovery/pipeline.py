"""Collection pipeline: fetch -> normalize -> reconcile -> detect changes -> score."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from . import constants as c
from .adapters.base import run_source
from .config import EngineConfig
from .http_client import Fetcher
from .identity import description_hash, identity_key
from .models import AdapterResult, RawOpportunity, RunSummary, SourceSpec
from .scoring import classify, extract_explicit_language, infer_season
from .urlnorm import normalize_url

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Pipeline:
    def __init__(self, conn: sqlite3.Connection, cfg: EngineConfig, run_id: str,
                 summary: RunSummary) -> None:
        self.conn = conn
        self.cfg = cfg
        self.run_id = run_id
        self.summary = summary
        self._observed_ids: set[str] = set()
        # ensure the run row exists before child rows reference it
        conn.execute(
            "INSERT OR IGNORE INTO collection_runs (run_id, started_at, mode)"
            " VALUES (?, ?, 'collect')",
            (run_id, summary.started_at),
        )
        conn.commit()

    # ------------------------------------------------------------- collection
    def process_source(self, source: SourceSpec, fetcher: Fetcher) -> None:
        """Run one source end-to-end with full isolation."""
        result: AdapterResult = run_source(
            source, fetcher, excerpt_chars=self.cfg.export.excerpt_chars
        )
        self._record_check(source, result)
        if not result.ok:
            # Preserve prior success: never let a failed check mutate records.
            return
        # Intra-batch dedupe: one source listing the same URL/identity twice
        # (e.g. title link + "read more" link) must not create field churn.
        seen_keys: set[str] = set()
        ingested = 0
        for raw in result.records:
            norm = normalize_url(raw.canonical_url)
            key, _basis = identity_key(
                provider=(raw.provider.lower() if raw.provider else None),
                provider_req_id=raw.provider_req_id,
                organization=raw.organization,
                title=raw.title,
                canonical_url=raw.canonical_url,
                location_text=raw.location_text,
            )
            batch_key = f"url:{norm}" if norm else key
            if batch_key in seen_keys:
                continue
            seen_keys.add(batch_key)
            if self._ingest_record(source, raw):
                ingested += 1
        self.conn.execute(
            "UPDATE source_checks SET records_seen=?, new_records=? "
            "WHERE check_id = (SELECT MAX(check_id) FROM source_checks WHERE source_id=?)",
            (len(result.records), ingested, source.source_id),
        )
        self.summary.records_seen += len(result.records)
        self.conn.commit()

    def _record_check(self, source: SourceSpec, result: AdapterResult) -> None:
        if not result.ok:
            state = result.state
        elif result.http_status == 304:
            state = c.HEALTH_HEALTHY  # unchanged since last successful check
        elif not result.records:
            state = c.HEALTH_VALID_EMPTY
        else:
            state = c.HEALTH_HEALTHY
        self.summary.sources_attempted += 1
        if result.ok:
            self.summary.sources_succeeded += 1
        else:
            self.summary.sources_failed += 1
        self.conn.execute(
            """
            INSERT INTO source_checks (source_id, run_id, checked_at, state, http_status,
                                       detail, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id, self.run_id, _now(), state, result.http_status,
                result.detail, 0,
            ),
        )

    # -------------------------------------------------------------- ingestion
    def _ingest_record(self, source: SourceSpec, raw: RawOpportunity) -> bool:
        """Upsert one observation into opportunities. Returns True if new."""
        norm_url = normalize_url(raw.canonical_url)
        opp_id, basis = identity_key(
            provider=(raw.provider.lower() if raw.provider else None),
            provider_req_id=raw.provider_req_id,
            organization=raw.organization,
            title=raw.title,
            canonical_url=raw.canonical_url,
            location_text=raw.location_text,
        )
        self._observed_ids.add(opp_id)

        existing = self.conn.execute(
            "SELECT * FROM opportunities WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()

        # Duplicate reconciliation across different identity keys: strong
        # evidence only (identical normalized URL after tracking-strip).
        duplicate_of = self._find_duplicate_by_url(opp_id, norm_url)
        if duplicate_of is not None:
            self._merge_duplicate(duplicate_of, opp_id, source.source_id, norm_url)
            opp_row = self.conn.execute(
                "SELECT * FROM opportunities WHERE opportunity_id = ?", (duplicate_of,)
            ).fetchone()
            return self._apply_observation(opp_row, source, raw, opp_id_override=duplicate_of)

        fields = self._normalize_fields(raw, source)
        now = _now()
        if existing is None:
            tags, components, signals, reasons = self._score(raw)
            fields["effort_estimate"] = signals.get("effort_estimate", c.EFFORT_UNKNOWN)
            fields["requested_components"] = signals.get("requested_components", [])
            record: dict[str, object] = {
                "opportunity_id": opp_id,
                "identity_basis": basis,
                "organization": fields["organization"],
                "title": fields["title"],
                "category": fields["category"],
                "canonical_url": norm_url,
                "official_url": fields["official_url"],
                "provider": fields["provider"],
                "provider_req_id": fields["provider_req_id"],
                "location_text": fields["location_text"],
                "location_city": fields["location_city"],
                "location_state": fields["location_state"],
                "location_country": fields["location_country"],
                "remote_signal": fields["remote_signal"],
                "season": fields["season"],
                "employment_type": fields["employment_type"],
                "posted_date": fields["posted_date"],
                "deadline": fields["deadline"],
                "deadline_tz": fields["deadline_tz"],
                "compensation_text": fields["compensation_text"],
                "relocation_text": fields["relocation_text"],
                "description_excerpt": fields["description_excerpt"],
                "description_hash": description_hash(fields["description_excerpt"]),
                "class_year_language": fields["class_year_language"],
                "graduation_window_language": fields["graduation_window_language"],
                "major_language": fields["major_language"],
                "work_auth_language": fields["work_auth_language"],
                "requested_components_json": json.dumps(fields["requested_components"]),
                "effort_estimate": fields["effort_estimate"],
                "role_family_tags_json": json.dumps(tags),
                "signals_json": json.dumps(signals),
                "score_components_json": json.dumps(components.__dict__),
                "generic_score": components.total,
                "reason_codes_json": json.dumps(reasons),
                "lead_state": "unverified-lead",
                "change_type": "new",
                "active": 1,
                "first_seen": now,
                "last_seen": now,
                "last_changed": now,
                "last_successful_check": now,
                "field_owner_json": "{}",
            }
            cols = ", ".join(record)
            placeholders = ", ".join("?" for _ in record)
            self.conn.execute(
                f"INSERT INTO opportunities ({cols}) VALUES ({placeholders})",
                tuple(record.values()),
            )
            self._touch_provenance(opp_id, source, raw, now)
            self.conn.execute(
                "INSERT INTO observations (run_id, source_id, opportunity_id, observed_at, record_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.run_id, source.source_id, opp_id, now, json.dumps(fields)),
            )
            self.conn.execute(
                "INSERT INTO changes (opportunity_id, run_id, change_type, changed_fields_json,"
                " detected_at) VALUES (?, ?, 'new', '{}', ?)",
                (opp_id, self.run_id, now),
            )
            self.summary.opportunities_new += 1
            return True

        return self._apply_observation(existing, source, raw, opp_id_override=None)

    def _find_duplicate_by_url(self, opp_id: str, norm_url: str) -> str | None:
        if not norm_url:
            return None
        row = self.conn.execute(
            "SELECT opportunity_id FROM opportunities WHERE canonical_url = ?", (norm_url,)
        ).fetchone()
        if row and row["opportunity_id"] != opp_id:
            return str(row["opportunity_id"])
        return None

    def _merge_duplicate(self, kept_id: str, merged_id: str, source_id: str, url: str) -> None:
        """Merge a differently-keyed duplicate into an existing opportunity."""
        now = _now()
        self.conn.execute(
            "UPDATE observations SET opportunity_id = ? WHERE opportunity_id = ?",
            (kept_id, merged_id),
        )
        # Move child rows, dropping ones that would collide on unique keys.
        for table in ("provenance", "aliases", "changes"):
            self.conn.execute(
                f"UPDATE OR IGNORE {table} SET opportunity_id = ? WHERE opportunity_id = ?",
                (kept_id, merged_id),
            )
            self.conn.execute(f"DELETE FROM {table} WHERE opportunity_id = ?", (merged_id,))
        self.conn.execute(
            "INSERT OR IGNORE INTO duplicate_decisions (kept_id, merged_id, basis, detail, decided_at)"
            " VALUES (?, ?, 'normalized-url-equal', ?, ?)",
            (kept_id, merged_id, f"url={url}", now),
        )
        self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = ?", (merged_id,))
        self._touch_provenance_url(kept_id, source_id, url, now)
        self.conn.commit()

    def _apply_observation(self, existing: sqlite3.Row, source: SourceSpec,
                           raw: RawOpportunity, *, opp_id_override: str | None) -> bool:
        """Update an existing opportunity with a fresh observation; detect changes."""
        opp_id = opp_id_override or str(existing["opportunity_id"])
        now = _now()
        fields = self._normalize_fields(raw, source)
        self.conn.execute(
            "INSERT INTO observations (run_id, source_id, opportunity_id, observed_at, record_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (self.run_id, source.source_id, opp_id, now, json.dumps(fields)),
        )
        self._touch_provenance(opp_id, source, raw, now)

        changed: dict[str, dict[str, Any]] = {}
        material_fields = self.cfg.changes.material_fields
        updates: dict[str, Any] = {"last_seen": now, "last_successful_check": now}
        owners: dict[str, str] = json.loads(existing["field_owner_json"] or "{}")
        source_class = "official" if source.official_source else "aggregate"
        owner_tag = f"{source_class}:{source.source_id}"

        def _may_overwrite(col: str) -> bool:
            """Field-ownership policy: first writer wins; official sources may
            override aggregator values; the owning source may update itself.
            Prevents ping-ponging between variant descriptions each run."""
            current = owners.get(col)
            if current is None:
                return True
            if current == owner_tag:
                return True
            return source.official_source and current.startswith("aggregate:")

        def _set_owner(col: str) -> None:
            owners[col] = owner_tag

        for col in material_fields:
            old_val = existing[col]
            if col == "canonical_url":
                continue  # identity-stable by construction
            new_val = fields.get(col)
            if col == "description_hash":
                old_desc_hash = existing["description_hash"]
                new_desc_hash = description_hash(fields["description_excerpt"])
                if old_desc_hash and new_desc_hash and old_desc_hash != new_desc_hash \
                        and _may_overwrite("description"):
                    changed["description"] = {
                        "old": old_desc_hash, "new": new_desc_hash}
                    updates["description_hash"] = new_desc_hash
                    updates["description_excerpt"] = fields["description_excerpt"]
                    _set_owner("description")
                continue
            if (new_val not in (None, "") and new_val != old_val
                    and _may_overwrite(col)):
                changed[col] = {"old": old_val, "new": new_val}
                updates[col] = new_val
                _set_owner(col)

        change_type = c.CHANGE_NO_CHANGE
        was_inactive = not int(existing["active"] or 0)
        if was_inactive:
            change_type = c.CHANGE_REOPENED
        elif changed:
            change_type = (
                c.CHANGE_DEADLINE if set(changed) <= {"deadline", "deadline_tz"}
                else c.CHANGE_MATERIAL
            )
        if change_type == c.CHANGE_REOPENED:
            updates["active"] = 1
        if change_type in (c.CHANGE_REOPENED, c.CHANGE_DEADLINE, c.CHANGE_MATERIAL):
            updates["last_changed"] = now
            updates["change_type"] = change_type
            detail: dict[str, Any] = dict(changed) or {"reactivated": True}
            self.conn.execute(
                "INSERT INTO changes (opportunity_id, run_id, change_type, changed_fields_json,"
                " detected_at) VALUES (?, ?, ?, ?, ?)",
                (opp_id, self.run_id, change_type, json.dumps(detail), now),
            )
            self.summary.opportunities_changed += 1
        # alias bookkeeping: alternate titles preserved
        if fields["title"] and fields["title"] != existing["title"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO aliases (opportunity_id, alias_type, value)"
                " VALUES (?, 'prior-title', ?)",
                (opp_id, existing["title"]),
            )
        updates["field_owner_json"] = json.dumps(owners)
        sets = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE opportunities SET {sets} WHERE opportunity_id = ?",
            (*updates.values(), opp_id),
        )
        # Rescore on material change so score components stay current.
        if change_type in (c.CHANGE_MATERIAL, c.CHANGE_DEADLINE, c.CHANGE_REOPENED):
            refreshed = RawOpportunity(
                title=fields["title"], canonical_url=fields["canonical_url"] or "",
                organization=fields["organization"], provider=fields["provider"],
                provider_req_id=fields["provider_req_id"], location_text=fields["location_text"],
                remote_signal=fields["remote_signal"], posted_date=fields["posted_date"],
                deadline=fields["deadline"], deadline_tz=fields["deadline_tz"],
                compensation_text=fields["compensation_text"],
                relocation_text=fields["relocation_text"],
                description_excerpt=fields["description_excerpt"],
                employment_type=fields["employment_type"], season=fields["season"],
            )
            tags, components, signals, reasons = self._score(refreshed)
            self.conn.execute(
                "UPDATE opportunities SET role_family_tags_json=?, score_components_json=?,"
                " signals_json=?, generic_score=?, reason_codes_json=? WHERE opportunity_id=?",
                (json.dumps(tags), json.dumps(components.__dict__), json.dumps(signals),
                 components.total, json.dumps(reasons), opp_id),
            )
        # reset consecutive misses
        self._set_consecutive_misses(opp_id, 0)
        return False

    def _normalize_fields(self, raw: RawOpportunity, source: SourceSpec) -> dict[str, Any]:
        season_cfg = self.cfg.season
        explicit = extract_explicit_language(raw)
        season = infer_season(raw, season_cfg.target_season, season_cfg.season_aliases)
        loc = raw.location_text or ""
        parts = [p.strip() for p in loc.split(",")] if loc else []
        remote = raw.remote_signal
        if remote is None and loc:
            low = loc.lower()
            if "remote" in low or "anywhere" in low:
                remote = "remote"
            elif "hybrid" in low:
                remote = "hybrid"
        employment = raw.employment_type
        if employment is None:
            t = (raw.title or "").lower()
            if "intern" in t:
                employment = "internship"
            elif any(k in t for k in ("fellowship", "scholarship")):
                employment = "program"
            elif any(k in t for k in ("conference", "hackathon", "career fair", "expo")):
                employment = "event"
        official = raw.canonical_url if source.official_source else None
        return {
            "organization": raw.organization or source.organization,
            "title": raw.title,
            "category": (source.categories[0] if source.categories else None),
            "canonical_url": normalize_url(raw.canonical_url) if raw.canonical_url else None,
            "official_url": official,
            "provider": raw.provider,
            "provider_req_id": raw.provider_req_id,
            "location_text": raw.location_text,
            "location_city": parts[0] if len(parts) > 0 else None,
            "location_state": parts[1] if len(parts) > 1 else None,
            "location_country": (
                parts[-1] if len(parts) > 2
                else ("USA" if parts and "usa" in loc.lower() else None)
            ),
            "remote_signal": remote,
            "season": season,
            "employment_type": employment,
            "posted_date": raw.posted_date,
            "deadline": raw.deadline,
            "deadline_tz": raw.deadline_tz,
            "compensation_text": raw.compensation_text,
            "relocation_text": raw.relocation_text,
            "description_excerpt": raw.description_excerpt,
            **explicit,
            "requested_components": [],
            "effort_estimate": c.EFFORT_UNKNOWN,
        }

    def _score(self, raw: RawOpportunity):  # type: ignore[no-untyped-def]
        return classify(raw, self.cfg.scoring)

    def _touch_provenance(self, opp_id: str, source: SourceSpec, raw: RawOpportunity, now: str) -> None:
        from urllib.parse import urlsplit

        lead_url = raw.canonical_url
        self.conn.execute(
            """
            INSERT INTO provenance (opportunity_id, source_id, source_url, evidence,
                                    first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(opportunity_id, source_id, source_url) DO UPDATE SET
                last_seen=excluded.last_seen
            """,
            (opp_id, source.source_id, lead_url, raw.evidence, now, now),
        )
        landing = source.landing_url or (
            f"{urlsplit(lead_url).scheme}://{urlsplit(lead_url).netloc}" if lead_url else None
        )
        if landing:
            self.conn.execute(
                """
                INSERT INTO provenance (opportunity_id, source_id, source_url, evidence,
                                        first_seen, last_seen)
                VALUES (?, ?, ?, 'source-stated', ?, ?)
                ON CONFLICT(opportunity_id, source_id, source_url) DO UPDATE SET
                    last_seen=excluded.last_seen
                """,
                (opp_id, source.source_id, landing, now, now),
            )

    def _touch_provenance_url(self, opp_id: str, source_id: str, url: str, now: str) -> None:
        self.conn.execute(
            """
            INSERT INTO provenance (opportunity_id, source_id, source_url, evidence,
                                    first_seen, last_seen)
            VALUES (?, ?, ?, 'source-stated', ?, ?)
            ON CONFLICT(opportunity_id, source_id, source_url) DO UPDATE SET
                last_seen=excluded.last_seen
            """,
            (opp_id, source_id, url, now, now),
        )

    # ------------------------------------------------------- post-run phases
    def detect_closures(self, successful_sources: set[str], expected_opps: dict[str, str]) -> None:
        """Mark apparently-closed only after consecutive *successful* misses."""
        threshold = self.cfg.changes.closed_after_consecutive_successes
        now = _now()
        for opp_id, source_id in expected_opps.items():
            if opp_id in self._observed_ids or source_id not in successful_sources:
                continue
            misses = self._get_consecutive_misses(opp_id) + 1
            self._set_consecutive_misses(opp_id, misses)
            if misses >= threshold:
                cur = self.conn.execute(
                    "SELECT active, change_type FROM opportunities WHERE opportunity_id=?",
                    (opp_id,),
                ).fetchone()
                if cur and int(cur["active"] or 0) == 1:
                    self.conn.execute(
                        "UPDATE opportunities SET active=0, change_type=?, last_changed=?,"
                        " last_seen=last_seen WHERE opportunity_id=?",
                        (c.CHANGE_CLOSED, now, opp_id),
                    )
                    self.conn.execute(
                        "INSERT INTO changes (opportunity_id, run_id, change_type,"
                        " changed_fields_json, detected_at) VALUES (?, ?, ?, '{}', ?)",
                        (opp_id, self.run_id, c.CHANGE_CLOSED, now),
                    )
                    self.summary.opportunities_closed += 1
        self.conn.commit()

    def _get_consecutive_misses(self, opp_id: str) -> int:
        row = self.conn.execute(
            "SELECT signals_json FROM opportunities WHERE opportunity_id=?", (opp_id,)
        ).fetchone()
        try:
            return int((json.loads(row["signals_json"]) or {}).get("_consecutive_misses", 0))
        except Exception:
            return 0

    def _set_consecutive_misses(self, opp_id: str, value: int) -> None:
        self.conn.execute(
            "UPDATE opportunities SET signals_json = json_set(COALESCE(signals_json,'{}'),"
            " '$.\"_consecutive_misses\"', ?) WHERE opportunity_id=?",
            (value, opp_id),
        )


def expected_opportunities_from_sources(conn: sqlite3.Connection,
                                        source_ids: list[str]) -> dict[str, str]:  # type: ignore[type-arg]
    """Map active opportunity_id -> provenance source_id limited to given sources."""
    out: dict[str, str] = {}
    if not source_ids:
        return out
    placeholders = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT p.opportunity_id AS oid, p.source_id AS sid
        FROM provenance p JOIN opportunities o ON o.opportunity_id = p.opportunity_id
        WHERE o.active = 1 AND p.source_id IN ({placeholders})
        """,
        source_ids,
    ).fetchall()
    for r in rows:
        out[str(r["oid"])] = str(r["sid"])
    return out
