from __future__ import annotations

# Lead verification vocabulary (public layer only -- never claims applicant-level verification)
LEAD_UNVERIFIED = "unverified-lead"
EVIDENCE_SOURCE_STATED = "source-stated"
EVIDENCE_INFERRED = "inferred-signal"
UNKNOWN = "unknown"

# Change types
CHANGE_NEW = "new"
CHANGE_NO_CHANGE = "no-change"
CHANGE_REOPENED = "reopened"
CHANGE_CLOSED = "apparently-closed"
CHANGE_DEADLINE = "deadline-changed"
CHANGE_MATERIAL = "materially-changed"
CHANGE_CHECK_FAILED = "check-failed"
ALL_CHANGE_TYPES = (
    CHANGE_NEW,
    CHANGE_NO_CHANGE,
    CHANGE_REOPENED,
    CHANGE_CLOSED,
    CHANGE_DEADLINE,
    CHANGE_MATERIAL,
    CHANGE_CHECK_FAILED,
)

# Source health states
HEALTH_HEALTHY = "healthy"
HEALTH_VALID_EMPTY = "valid-empty"
HEALTH_DEGRADED = "degraded"
HEALTH_CHECK_FAILED = "check-failed"
HEALTH_RATE_LIMITED = "rate-limited"
HEALTH_FORMAT_CHANGED = "format-changed"
HEALTH_DISABLED = "disabled"
HEALTH_QUARANTINED = "quarantined"
ALL_HEALTH_STATES = (
    HEALTH_HEALTHY,
    HEALTH_VALID_EMPTY,
    HEALTH_DEGRADED,
    HEALTH_CHECK_FAILED,
    HEALTH_RATE_LIMITED,
    HEALTH_FORMAT_CHANGED,
    HEALTH_DISABLED,
    HEALTH_QUARANTINED,
)

# Validation statuses for the source registry
VALIDATION_PENDING = "pending"
VALIDATION_PASSED = "validated"
VALIDATION_EMPTY_OK = "validated-empty-ok"
VALIDATION_FAILED = "failed"
VALIDATION_QUARANTINED = "quarantined"

# Effort estimates
EFFORT_QUICK = "quick"
EFFORT_MODERATE = "moderate"
EFFORT_SUBSTANTIAL = "substantial"
EFFORT_UNKNOWN = UNKNOWN

# Reason-code prefixes
REASON_INCLUDE = "include:"
REASON_EXCLUDE = "exclude:"
REASON_DOWNRANK = "downrank:"

# Well-known exclusion reason codes
EXCLUDE_COOP_SCHOOL_TERM = "exclude:school-term-coop"
EXCLUDE_ONLINE_HACKATHON = "exclude:online-hackathon-low-value"
DOWNRANK_EXPENSIVE_EVENT = "downrank:unfunded-distant-event"
