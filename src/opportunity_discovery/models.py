"""Typed models shared across the engine.

The public lead layer never stores applicant-specific data; see
docs/INTEGRATION_CONTRACT.md for the two-layer data contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from . import constants as c


@dataclass
class SourceSpec:
    """A configured public source (from config/sources.toml)."""

    source_id: str
    display_name: str
    organization: str
    adapter: str
    landing_url: str | None = None
    endpoint_config: dict[str, Any] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cadence_hours: int = 24
    enabled: bool = True
    official_source: bool = False  # True when fetched from the org's own ATS/page
    rate_limit_min_seconds: float = 0.0
    last_validated: str | None = None
    validation_status: str = c.VALIDATION_PENDING
    provenance_note: str | None = None
    quarantine_reason: str | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.source_id or not self.source_id.strip():
            errors.append("source_id must be a non-empty string")
        if not self.display_name:
            errors.append(f"{self.source_id}: display_name is required")
        if not self.organization:
            errors.append(f"{self.source_id}: organization is required")
        if not self.adapter:
            errors.append(f"{self.source_id}: adapter is required")
        cfg = self.endpoint_config or {}
        if not any(k in cfg for k in ("url", "endpoint", "tenant", "board")) and (
            self.adapter != "program-page"
            or not any(k in cfg for k in ("overview_url", "application_url", "programs"))
        ):
            errors.append(f"{self.source_id}: endpoint_config must define 'url' (or adapter-specific keys)")
        if self.adapter == "program-page":
            errors.extend(_validate_program_page_config(self.source_id, cfg))
        if self.adapter == "greenhouse" and "max_response_bytes" in cfg:
            limit = cfg["max_response_bytes"]
            if type(limit) is not int or not 1_024 <= limit <= c.MAX_SOURCE_RESPONSE_BYTES:
                errors.append(
                    f"{self.source_id}: greenhouse max_response_bytes must be an integer from 1024 "
                    f"to {c.MAX_SOURCE_RESPONSE_BYTES}"
                )
        return errors


@dataclass
class RawOpportunity:
    """One candidate observed at one source at one time (pre-normalization)."""

    title: str
    canonical_url: str
    organization: str | None = None
    provider: str | None = None  # e.g. greenhouse / lever / ashby / workday
    provider_req_id: str | None = None
    location_text: str | None = None
    remote_signal: str | None = None  # remote / hybrid / in-person / None(=unknown)
    posted_date: str | None = None  # ISO date when known
    deadline: str | None = None  # ISO date of stated deadline
    deadline_tz: str | None = None
    overview_url: str | None = None
    application_url: str | None = None
    program_family_id: str | None = None
    cycle_id: str | None = None
    event_start_date: str | None = None
    event_end_date: str | None = None
    application_state: str = c.APPLICATION_UNKNOWN
    requirements_text: str | None = None
    source_constraints: list[dict[str, Any]] | None = None
    compensation_text: str | None = None
    relocation_text: str | None = None
    description_excerpt: str | None = None  # bounded excerpt only
    employment_type: str | None = None  # internship / new-grad / program / event ...
    engagement_type: str | None = None
    career_stage: str | None = None
    required_degree: str | None = None
    preferred_degree: str | None = None
    experience_requirement_text: str | None = None
    season: str | None = None  # e.g. summer-2027
    class_year_language: str | None = None
    graduation_window_language: str | None = None
    major_language: str | None = None
    work_auth_language: str | None = None
    requested_components: list[str] = field(default_factory=list)
    evidence: str = c.EVIDENCE_SOURCE_STATED
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    """Outcome of one adapter invocation against one source."""

    records: list[RawOpportunity] = field(default_factory=list)
    ok: bool = True
    empty_ok: bool = False  # True => valid empty result; False => parse found nothing unexpected
    state: str = c.HEALTH_HEALTHY  # one of the HEALTH_* constants
    detail: str | None = None
    http_status: int | None = None
    pages_fetched: int | None = None
    reported_total: int | None = None
    truncated: bool | None = None


@dataclass
class ScoreComponents:
    """Deterministic, inspectable score components (no opaque model)."""

    family_weights: dict[str, float] = field(default_factory=dict)
    bonuses: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        t = sum(self.family_weights.values())
        t += sum(self.bonuses.values())
        t -= sum(self.penalties.values())
        return round(t, 3)


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str | None = None
    mode: str = "run"
    exit_code: int = 0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    records_seen: int = 0
    opportunities_new: int = 0
    opportunities_changed: int = 0
    opportunities_closed: int = 0
    review_queue_count: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "mode": self.mode,
            "exit_code": self.exit_code,
            "sources_attempted": self.sources_attempted,
            "sources_succeeded": self.sources_succeeded,
            "sources_failed": self.sources_failed,
            "records_seen": self.records_seen,
            "opportunities_new": self.opportunities_new,
            "opportunities_changed": self.opportunities_changed,
            "opportunities_closed": self.opportunities_closed,
            "review_queue_count": self.review_queue_count,
            "detail": self.detail,
        }


def _validate_program_page_config(source_id: str, cfg: dict[str, Any]) -> list[str]:
    """Validate the bounded, explicitly configured program-page shape."""
    errors: list[str] = []
    programs = cfg.get("programs")
    if not isinstance(programs, list) or not programs:
        return [f"{source_id}: program-page endpoint_config.programs must be a non-empty array"]
    if len(programs) > 8:
        errors.append(f"{source_id}: program-page supports at most 8 configured programs")
    max_pages = cfg.get("max_pages", 8)
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 8:
        errors.append(f"{source_id}: program-page max_pages must be an integer from 1 to 8")
        max_pages = 8

    source_overview = cfg.get("overview_url")
    urls: set[str] = set()
    identities: set[tuple[str, str]] = set()
    canonical_counts: dict[str, int] = {}
    for index, program in enumerate(programs):
        prefix = f"{source_id}: program-page programs[{index}]"
        if not isinstance(program, dict):
            errors.append(f"{prefix} must be a table")
            continue
        overview_url = program.get("overview_url", source_overview)
        application_url = program.get("application_url", cfg.get("application_url"))
        if not overview_url and not application_url:
            errors.append(f"{prefix} requires overview_url or application_url")
        for name, value in (("overview_url", overview_url), ("application_url", application_url)):
            if value:
                url_error = _configured_http_url_error(str(value))
                if url_error:
                    errors.append(f"{prefix} {name} {url_error}")
                urls.add(str(value))
        canonical = str(application_url or overview_url or "")
        canonical_counts[canonical] = canonical_counts.get(canonical, 0) + 1

        family = program.get("program_family_id", cfg.get("program_family_id"))
        cycle = program.get("cycle_id", program.get("session_id"))
        if program.get("cycle_id") and program.get("session_id"):
            errors.append(f"{prefix} must use only one of cycle_id or session_id")
        if bool(family) != bool(cycle):
            errors.append(f"{prefix} program_family_id and cycle/session identifier must be paired")
        if family and cycle:
            key = (str(family), str(cycle))
            if key in identities:
                errors.append(f"{prefix} duplicates program identity {key!r}")
            identities.add(key)
        state = program.get("application_state")
        if state is not None and state not in c.ALL_APPLICATION_STATES:
            errors.append(f"{prefix} application_state must be one of {c.ALL_APPLICATION_STATES}")
        for mapping_name in ("selectors", "jsonld_fields"):
            mapping = program.get(mapping_name, cfg.get(mapping_name, {}))
            if not isinstance(mapping, dict):
                errors.append(f"{prefix} {mapping_name} must be a table")
            elif not all(isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()):
                errors.append(f"{prefix} {mapping_name} keys and values must be strings")
        rules = program.get("state_rules", cfg.get("state_rules", []))
        if not isinstance(rules, list):
            errors.append(f"{prefix} state_rules must be an array of tables")
        else:
            for rule_index, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    errors.append(f"{prefix} state_rules[{rule_index}] must be a table")
                    continue
                rule_state = rule.get("state")
                pattern = rule.get("pattern")
                if rule_state not in c.ALL_APPLICATION_STATES:
                    errors.append(
                        f"{prefix} state_rules[{rule_index}].state must be one of {c.ALL_APPLICATION_STATES}"
                    )
                if not isinstance(pattern, str):
                    errors.append(f"{prefix} state_rules[{rule_index}].pattern must be a regex string")
                else:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        errors.append(f"{prefix} invalid state rule regex {pattern!r}: {exc}")

    if len(urls) > max_pages:
        errors.append(
            f"{source_id}: program-page configured {len(urls)} unique pages, exceeding max_pages={max_pages}"
        )
    for canonical, count in canonical_counts.items():
        if canonical and count > 1:
            matching = [
                p
                for p in programs
                if isinstance(p, dict)
                and str(
                    p.get("application_url", cfg.get("application_url"))
                    or p.get("overview_url", source_overview)
                    or ""
                )
                == canonical
            ]
            if any(
                not (
                    p.get("program_family_id", cfg.get("program_family_id"))
                    and (p.get("cycle_id") or p.get("session_id"))
                )
                for p in matching
            ):
                errors.append(
                    f"{source_id}: repeated canonical URL {canonical!r} requires explicit "
                    "program_family_id plus cycle/session identifier for every record"
                )

    canaries = cfg.get("coverage", {})
    if not isinstance(canaries, dict):
        errors.append(f"{source_id}: program-page coverage must be a table")
    else:
        minimum = canaries.get("min_results", 1)
        maximum = canaries.get("max_results", len(programs))
        if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum < 0 or maximum < minimum:
            errors.append(f"{source_id}: coverage result range must satisfy 0 <= min_results <= max_results")
        for coverage_key in ("expected_url_patterns", "expected_title_patterns"):
            patterns = canaries.get(coverage_key, [])
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                errors.append(f"{source_id}: coverage.{coverage_key} must be an array of regex strings")
                continue
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{source_id}: invalid coverage regex {pattern!r}: {exc}")
    return errors


def _configured_http_url_error(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        return f"is invalid: {exc}"
    if parts.scheme not in ("http", "https"):
        return "must use http or https"
    if not parts.hostname or parts.username or parts.password:
        return "must have a host and no embedded credentials"
    return None
