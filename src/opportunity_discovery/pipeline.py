"""Collection pipeline: fetch -> normalize -> reconcile -> detect changes -> score."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from . import constants as c
from .adapters.base import run_source
from .config import EngineConfig
from .http_client import Fetcher
from .identity import description_hash, identity_key
from .models import AdapterResult, RawOpportunity, RunSummary, SourceSpec
from .routing import normalize_routing_fields, route_profiles
from .scoring import classify, extract_explicit_language, infer_season
from .urlnorm import normalize_url

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Pipeline:
    def __init__(self, conn: sqlite3.Connection, cfg: EngineConfig, run_id: str, summary: RunSummary) -> None:
        self.conn = conn
        self.cfg = cfg
        self.run_id = run_id
        self.summary = summary
        self._observed_by_source: dict[str, set[str]] = {}
        # ensure the run row exists before child rows reference it
        conn.execute(
            "INSERT OR IGNORE INTO collection_runs (run_id, started_at, mode) VALUES (?, ?, 'collect')",
            (run_id, summary.started_at),
        )
        conn.commit()

    # ------------------------------------------------------------- collection
    def process_source(self, source: SourceSpec, fetcher: Fetcher) -> None:
        """Run one source end-to-end with full isolation."""
        started_ns = time.monotonic_ns()
        result: AdapterResult = run_source(source, fetcher, excerpt_chars=self.cfg.export.excerpt_chars)
        duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        self._record_check(source, result, duration_ms)
        if not result.ok:
            # Preserve prior success: never let a failed check mutate records.
            return
        # Intra-batch dedupe: one source listing the same URL/identity twice
        # (e.g. title link + "read more" link) must not create field churn.
        seen_keys: set[str] = set()
        ingested = 0
        changed_before = self.summary.opportunities_changed
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
        duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        self.conn.execute(
            "UPDATE source_checks SET records_seen=?, new_records=?, changed_records=?, duration_ms=? "
            "WHERE check_id = (SELECT MAX(check_id) FROM source_checks "
            "WHERE source_id=? AND run_id=?)",
            (
                len(result.records),
                ingested,
                self.summary.opportunities_changed - changed_before,
                duration_ms,
                source.source_id,
                self.run_id,
            ),
        )
        self.summary.records_seen += len(result.records)
        self.summary.detail.setdefault("sources", {})[source.source_id].update(
            {
                "records_seen": len(result.records),
                "records_new": ingested,
                "records_changed": self.summary.opportunities_changed - changed_before,
                "duration_ms": duration_ms,
            }
        )
        self.conn.commit()

    def _record_check(self, source: SourceSpec, result: AdapterResult, duration_ms: int) -> None:
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
                                       detail, duration_ms, pages_fetched, reported_total,
                                       truncated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                self.run_id,
                _now(),
                state,
                result.http_status,
                result.detail,
                duration_ms,
                result.pages_fetched,
                result.reported_total,
                None if result.truncated is None else int(result.truncated),
            ),
        )
        self.summary.detail.setdefault("sources", {})[source.source_id] = {
            "state": state,
            "records_seen": 0,
            "records_new": 0,
            "records_changed": 0,
            "duration_ms": duration_ms,
            "pages_fetched": result.pages_fetched,
            "reported_total": result.reported_total,
            "truncated": result.truncated,
        }

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
        existing = self.conn.execute(
            "SELECT * FROM opportunities WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()

        # Duplicate reconciliation across different identity keys: strong
        # evidence only (identical normalized URL after tracking-strip).
        duplicate_of = self._find_duplicate_by_url(opp_id, norm_url)
        if duplicate_of is not None:
            self._observed_by_source.setdefault(source.source_id, set()).add(duplicate_of)
            self._merge_duplicate(duplicate_of, opp_id, source.source_id, norm_url)
            opp_row = self.conn.execute(
                "SELECT * FROM opportunities WHERE opportunity_id = ?", (duplicate_of,)
            ).fetchone()
            return self._apply_observation(opp_row, source, raw, opp_id_override=duplicate_of)

        self._observed_by_source.setdefault(source.source_id, set()).add(opp_id)

        fields = self._normalize_fields(raw, source)
        now = _now()
        if existing is None:
            tags, components, signals, reasons = self._score(raw)
            profile_routes = route_profiles(fields)
            active_decision = profile_routes[self.cfg.routing.active_profile]
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
                "engagement_type": fields["engagement_type"],
                "career_stage": fields["career_stage"],
                "required_degree": fields["required_degree"],
                "preferred_degree": fields["preferred_degree"],
                "experience_requirement_text": fields["experience_requirement_text"],
                "experience_min_years": fields["experience_min_years"],
                "experience_max_years": fields["experience_max_years"],
                "active_profile": self.cfg.routing.active_profile,
                "routing_state": active_decision.state,
                "eligibility_confidence": active_decision.confidence,
                "profile_routes_json": json.dumps(
                    {name: decision.to_dict() for name, decision in profile_routes.items()},
                    sort_keys=True,
                ),
                "routing_reason_codes_json": json.dumps(active_decision.reason_codes),
                "posted_date": fields["posted_date"],
                "deadline": fields["deadline"],
                "deadline_tz": fields["deadline_tz"],
                "overview_url": fields["overview_url"],
                "application_url": fields["application_url"],
                "program_family_id": fields["program_family_id"],
                "cycle_id": fields["cycle_id"],
                "event_start_date": fields["event_start_date"],
                "event_end_date": fields["event_end_date"],
                "application_state": fields["application_state"],
                "requirements_text": fields["requirements_text"],
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
                "last_change_events_json": json.dumps([c.CHANGE_NEW]),
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
            "UPDATE OR IGNORE opportunity_source_state SET opportunity_id=? WHERE opportunity_id=?",
            (kept_id, merged_id),
        )
        self.conn.execute(
            "DELETE FROM opportunity_source_state WHERE opportunity_id=?",
            (merged_id,),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO duplicate_decisions (kept_id, merged_id, basis, detail, decided_at)"
            " VALUES (?, ?, 'normalized-url-equal', ?, ?)",
            (kept_id, merged_id, f"url={url}", now),
        )
        self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = ?", (merged_id,))
        self._touch_provenance_url(kept_id, source_id, url, now)
        self.conn.commit()

    def _apply_observation(
        self, existing: sqlite3.Row, source: SourceSpec, raw: RawOpportunity, *, opp_id_override: str | None
    ) -> bool:
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
        if existing["organization"] == "↳" and raw.organization and raw.organization.strip() != "↳":
            corrected_organization = raw.organization.strip()
            changed["organization"] = {"old": "↳", "new": corrected_organization}
            updates["organization"] = corrected_organization
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
                if new_desc_hash and old_desc_hash != new_desc_hash and _may_overwrite("description"):
                    changed["description"] = {"old": old_desc_hash, "new": new_desc_hash}
                    updates["description_hash"] = new_desc_hash
                    updates["description_excerpt"] = fields["description_excerpt"]
                    _set_owner("description")
                continue
            if new_val not in (None, "", c.UNKNOWN) and new_val != old_val and _may_overwrite(col):
                changed[col] = {"old": old_val, "new": new_val}
                updates[col] = new_val
                _set_owner(col)

        change_type = c.CHANGE_NO_CHANGE
        event_types: list[str] = []
        was_inactive = not int(existing["active"] or 0)
        if was_inactive:
            change_type = c.CHANGE_REOPENED
            event_types = [c.CHANGE_REOPENED]
        elif changed:
            event_types = self._granular_change_types(existing, changed)
            change_type = event_types[0]
        if change_type == c.CHANGE_REOPENED:
            updates["active"] = 1
        if event_types:
            updates["last_changed"] = now
            updates["change_type"] = change_type
            updates["last_change_events_json"] = json.dumps(event_types)
            for event_type in event_types:
                detail = self._event_detail(event_type, changed)
                self.conn.execute(
                    "INSERT INTO changes (opportunity_id, run_id, change_type, changed_fields_json,"
                    " detected_at) VALUES (?, ?, ?, ?, ?)",
                    (opp_id, self.run_id, event_type, json.dumps(detail), now),
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
        # Rescore the final merged record, not the incoming observation. This
        # keeps every derived scoring field consistent with source ownership.
        if event_types:

            def final_value(column: str) -> Any:
                return updates.get(column, existing[column])

            refreshed = RawOpportunity(
                title=final_value("title") or "",
                canonical_url=final_value("canonical_url") or "",
                organization=final_value("organization"),
                provider=final_value("provider"),
                provider_req_id=final_value("provider_req_id"),
                location_text=final_value("location_text"),
                remote_signal=final_value("remote_signal"),
                posted_date=final_value("posted_date"),
                deadline=final_value("deadline"),
                deadline_tz=final_value("deadline_tz"),
                overview_url=final_value("overview_url"),
                application_url=final_value("application_url"),
                program_family_id=final_value("program_family_id"),
                cycle_id=final_value("cycle_id"),
                event_start_date=final_value("event_start_date"),
                event_end_date=final_value("event_end_date"),
                application_state=final_value("application_state"),
                requirements_text=final_value("requirements_text"),
                compensation_text=final_value("compensation_text"),
                relocation_text=final_value("relocation_text"),
                description_excerpt=final_value("description_excerpt"),
                employment_type=final_value("employment_type"),
                engagement_type=final_value("engagement_type"),
                career_stage=final_value("career_stage"),
                required_degree=final_value("required_degree"),
                preferred_degree=final_value("preferred_degree"),
                experience_requirement_text=final_value("experience_requirement_text"),
                season=final_value("season"),
            )
            tags, components, signals, reasons = self._score(refreshed)
            updates.update(
                {
                    "requested_components_json": json.dumps(signals.get("requested_components", [])),
                    "effort_estimate": signals.get("effort_estimate", c.EFFORT_UNKNOWN),
                    "role_family_tags_json": json.dumps(tags),
                    "score_components_json": json.dumps(components.__dict__),
                    "signals_json": json.dumps(signals),
                    "generic_score": components.total,
                    "reason_codes_json": json.dumps(reasons),
                }
            )
        effective_fields = dict(fields)
        for key in (
            "engagement_type",
            "career_stage",
            "required_degree",
            "preferred_degree",
            "experience_requirement_text",
            "experience_min_years",
            "experience_max_years",
        ):
            effective_fields[key] = updates.get(key, existing[key])
        profile_routes = route_profiles(effective_fields)
        active_decision = profile_routes[self.cfg.routing.active_profile]
        updates.update(
            {
                "active_profile": self.cfg.routing.active_profile,
                "routing_state": active_decision.state,
                "eligibility_confidence": active_decision.confidence,
                "profile_routes_json": json.dumps(
                    {name: decision.to_dict() for name, decision in profile_routes.items()},
                    sort_keys=True,
                ),
                "routing_reason_codes_json": json.dumps(active_decision.reason_codes),
            }
        )
        sets = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE opportunities SET {sets} WHERE opportunity_id = ?",
            (*updates.values(), opp_id),
        )
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
            if re.search(r"\bintern(?:ship)?\b", t):
                employment = "internship"
            elif any(k in t for k in ("fellowship", "scholarship")):
                employment = "program"
            elif any(k in t for k in ("conference", "hackathon", "career fair", "expo")):
                employment = "event"
            elif "full-time" in t or "full time" in t:
                employment = "full-time"
        normalized = normalize_routing_fields(
            RawOpportunity(
                title=raw.title,
                canonical_url=raw.canonical_url,
                description_excerpt=raw.description_excerpt,
                requirements_text=raw.requirements_text,
                employment_type=employment,
                engagement_type=raw.engagement_type,
                career_stage=raw.career_stage,
                required_degree=raw.required_degree,
                preferred_degree=raw.preferred_degree,
                experience_requirement_text=raw.experience_requirement_text,
                extra=raw.extra,
            )
        )
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
                parts[-1] if len(parts) > 2 else ("USA" if parts and "usa" in loc.lower() else None)
            ),
            "remote_signal": remote,
            "season": season,
            "employment_type": employment,
            **normalized,
            "posted_date": raw.posted_date,
            "deadline": raw.deadline,
            "deadline_tz": raw.deadline_tz,
            "overview_url": normalize_url(raw.overview_url) if raw.overview_url else None,
            "application_url": normalize_url(raw.application_url) if raw.application_url else None,
            "program_family_id": raw.program_family_id,
            "cycle_id": raw.cycle_id,
            "event_start_date": raw.event_start_date,
            "event_end_date": raw.event_end_date,
            "application_state": raw.application_state,
            "requirements_text": raw.requirements_text,
            "compensation_text": raw.compensation_text,
            "relocation_text": raw.relocation_text,
            "description_excerpt": raw.description_excerpt,
            **explicit,
            "requested_components": [],
            "effort_estimate": c.EFFORT_UNKNOWN,
        }

    def _score(self, raw: RawOpportunity):  # type: ignore[no-untyped-def]
        return classify(raw, self.cfg.scoring)

    @staticmethod
    def _granular_change_types(existing: sqlite3.Row, changed: dict[str, dict[str, Any]]) -> list[str]:
        events: list[str] = []
        if "application_state" in changed:
            old_state = existing["application_state"]
            new_state = changed["application_state"]["new"]
            if new_state == c.APPLICATION_OPEN and old_state != c.APPLICATION_OPEN:
                events.append(c.CHANGE_APPLICATION_OPENED)
            elif old_state == c.APPLICATION_OPEN and new_state in (
                c.APPLICATION_CLOSED,
                c.APPLICATION_NOTIFICATION_ONLY,
            ):
                events.append(c.CHANGE_APPLICATION_CLOSED)
        categories = (
            (c.CHANGE_DEADLINE, {"deadline", "deadline_tz"}),
            (
                c.CHANGE_REQUIREMENTS,
                {
                    "requirements_text",
                    "class_year_language",
                    "graduation_window_language",
                    "major_language",
                    "work_auth_language",
                    "description",
                },
            ),
            (c.CHANGE_DATES, {"event_start_date", "event_end_date"}),
            (c.CHANGE_LOCATION, {"location_text"}),
        )
        categorized: set[str] = {"application_state"}
        for event_type, fields in categories:
            triggered = (
                bool((fields - {"description"}) & set(changed))
                if event_type == c.CHANGE_REQUIREMENTS
                else bool(fields & set(changed))
            )
            if triggered:
                events.append(event_type)
                categorized.update(fields)
        if set(changed) - categorized or not events:
            events.append(c.CHANGE_MATERIAL)
        return events

    @staticmethod
    def _event_detail(event_type: str, changed: dict[str, dict[str, Any]]) -> dict[str, Any]:
        fields_by_event = {
            c.CHANGE_APPLICATION_OPENED: {"application_state"},
            c.CHANGE_APPLICATION_CLOSED: {"application_state"},
            c.CHANGE_DEADLINE: {"deadline", "deadline_tz"},
            c.CHANGE_REQUIREMENTS: {
                "requirements_text",
                "class_year_language",
                "graduation_window_language",
                "major_language",
                "work_auth_language",
                "description",
            },
            c.CHANGE_DATES: {"event_start_date", "event_end_date"},
            c.CHANGE_LOCATION: {"location_text"},
        }
        if event_type == c.CHANGE_REOPENED:
            return {"reactivated": True}
        selected = fields_by_event.get(event_type)
        if selected is None:
            categorized = set().union(*fields_by_event.values())
            detail = {key: value for key, value in changed.items() if key not in categorized}
            return detail or dict(changed)
        return {key: value for key, value in changed.items() if key in selected}

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
        self._record_source_observation(opp_id, source.source_id, now)

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
        self._record_source_observation(opp_id, source_id, now)

    def _record_source_observation(self, opp_id: str, source_id: str, now: str) -> None:
        self.conn.execute(
            """
            INSERT INTO opportunity_source_state (
                opportunity_id, source_id, consecutive_successful_misses,
                last_observed_at, last_checked_at
            ) VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(opportunity_id, source_id) DO UPDATE SET
                consecutive_successful_misses=0,
                last_observed_at=excluded.last_observed_at,
                last_checked_at=excluded.last_checked_at
            """,
            (opp_id, source_id, now, now),
        )

    # ------------------------------------------------------- post-run phases
    def detect_closures(self, successful_sources: set[str], expected_opps: dict[str, set[str]]) -> None:
        """Close only after every usable provenance source reaches the miss threshold.

        A miss advances only for a source that completed successfully in this
        run and did not observe the opportunity. Failed, unattempted, and
        truncated sources preserve their prior counters. Any observation resets
        that source's counter. Disabled and quarantined sources are not closure
        authorities.
        """
        threshold = self.cfg.changes.closed_after_consecutive_successes
        now = _now()
        affected: set[str] = set()
        for opp_id, source_ids in expected_opps.items():
            for source_id in source_ids & successful_sources:
                if opp_id in self._observed_by_source.get(source_id, set()):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO opportunity_source_state (
                        opportunity_id, source_id, consecutive_successful_misses,
                        last_checked_at
                    ) VALUES (?, ?, 1, ?)
                    ON CONFLICT(opportunity_id, source_id) DO UPDATE SET
                        consecutive_successful_misses=
                            opportunity_source_state.consecutive_successful_misses + 1,
                        last_checked_at=excluded.last_checked_at
                    """,
                    (opp_id, source_id, now),
                )
                affected.add(opp_id)

        for opp_id in affected:
            states = self.conn.execute(
                """
                SELECT oss.consecutive_successful_misses AS misses
                FROM opportunity_source_state oss
                JOIN sources s ON s.source_id = oss.source_id
                JOIN provenance p ON p.opportunity_id = oss.opportunity_id
                                 AND p.source_id = oss.source_id
                WHERE oss.opportunity_id=? AND s.enabled=1
                  AND s.quarantine_reason IS NULL
                GROUP BY oss.source_id
                """,
                (opp_id,),
            ).fetchall()
            if not states or any(int(row["misses"] or 0) < threshold for row in states):
                continue
            cur = self.conn.execute(
                "SELECT active FROM opportunities WHERE opportunity_id=?",
                (opp_id,),
            ).fetchone()
            if cur and int(cur["active"] or 0) == 1:
                self.conn.execute(
                    "UPDATE opportunities SET active=0, change_type=?, last_changed=?,"
                    " last_change_events_json=? WHERE opportunity_id=?",
                    (c.CHANGE_CLOSED, now, json.dumps([c.CHANGE_CLOSED]), opp_id),
                )
                self.conn.execute(
                    "INSERT INTO changes (opportunity_id, run_id, change_type,"
                    " changed_fields_json, detected_at) VALUES (?, ?, ?, '{}', ?)",
                    (opp_id, self.run_id, c.CHANGE_CLOSED, now),
                )
                self.summary.opportunities_closed += 1
        self.conn.commit()


def expected_opportunities_from_sources(
    conn: sqlite3.Connection, source_ids: list[str]
) -> dict[str, set[str]]:
    """Map each active opportunity to all targeted provenance sources."""
    out: dict[str, set[str]] = {}
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
        out.setdefault(str(r["oid"]), set()).add(str(r["sid"]))
    return out
