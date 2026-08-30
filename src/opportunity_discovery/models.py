"""Typed models shared across the engine.

The public lead layer never stores applicant-specific data; see
docs/INTEGRATION_CONTRACT.md for the two-layer data contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
        if not any(k in cfg for k in ("url", "endpoint", "tenant", "board")):
            errors.append(f"{self.source_id}: endpoint_config must define 'url' (or adapter-specific keys)")
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
    compensation_text: str | None = None
    relocation_text: str | None = None
    description_excerpt: str | None = None  # bounded excerpt only
    employment_type: str | None = None  # internship / new-grad / program / event ...
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
