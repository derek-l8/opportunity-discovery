from __future__ import annotations

# Lead verification vocabulary (public layer only -- never claims applicant-level verification)
LEAD_UNVERIFIED = "unverified-lead"
EVIDENCE_SOURCE_STATED = "source-stated"
EVIDENCE_INFERRED = "inferred-signal"
UNKNOWN = "unknown"

# Public-text normalization and deterministic profile routing. These values
# describe what a posting says; they never express applicant-specific fitness.
ENGAGEMENT_INTERNSHIP = "internship"
ENGAGEMENT_COOP = "co-op"
ENGAGEMENT_CONTRACT = "contract"
ENGAGEMENT_RESEARCH = "research"
ENGAGEMENT_FELLOWSHIP = "fellowship"
ENGAGEMENT_PROGRAM = "program"
ENGAGEMENT_EVENT = "event"
ENGAGEMENT_FULL_TIME = "full-time"
ENGAGEMENT_UNKNOWN = UNKNOWN

CAREER_STUDENT = "student"
CAREER_NEW_GRAD = "new-grad"
CAREER_ENTRY_LEVEL = "entry-level"
CAREER_EXPERIENCED = "experienced"
CAREER_UNKNOWN = UNKNOWN

DEGREE_HIGH_SCHOOL = "high-school"
DEGREE_ASSOCIATE = "associate"
DEGREE_BACHELORS = "bachelors"
DEGREE_MASTERS = "masters"
DEGREE_DOCTORATE = "doctorate"
DEGREE_UNKNOWN = UNKNOWN

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

ROUTE_INCLUDED = "included"
ROUTE_EXCLUDED = "excluded"
ROUTE_RESEARCH = "research_needed"

PROFILE_STUDENT = "student-early-career"
PROFILE_NEW_GRAD = "new-grad"
PROFILE_ALL = "all-opportunities"
ALL_PROFILES = (PROFILE_STUDENT, PROFILE_NEW_GRAD, PROFILE_ALL)

# Change types
CHANGE_NEW = "new"
CHANGE_NO_CHANGE = "no-change"
CHANGE_REOPENED = "reopened"
CHANGE_CLOSED = "apparently-closed"
CHANGE_DEADLINE = "deadline-changed"
CHANGE_APPLICATION_OPENED = "application-opened"
CHANGE_APPLICATION_CLOSED = "application-closed"
CHANGE_REQUIREMENTS = "requirements-changed"
CHANGE_DATES = "dates-changed"
CHANGE_LOCATION = "location-changed"
CHANGE_MATERIAL = "materially-changed"
CHANGE_CHECK_FAILED = "check-failed"
ALL_CHANGE_TYPES = (
    CHANGE_NEW,
    CHANGE_NO_CHANGE,
    CHANGE_REOPENED,
    CHANGE_CLOSED,
    CHANGE_DEADLINE,
    CHANGE_APPLICATION_OPENED,
    CHANGE_APPLICATION_CLOSED,
    CHANGE_REQUIREMENTS,
    CHANGE_DATES,
    CHANGE_LOCATION,
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
HEALTH_COVERAGE_WARNING = "coverage-warning"
HEALTH_DISABLED = "disabled"
HEALTH_QUARANTINED = "quarantined"
ALL_HEALTH_STATES = (
    HEALTH_HEALTHY,
    HEALTH_VALID_EMPTY,
    HEALTH_DEGRADED,
    HEALTH_CHECK_FAILED,
    HEALTH_RATE_LIMITED,
    HEALTH_FORMAT_CHANGED,
    HEALTH_COVERAGE_WARNING,
    HEALTH_DISABLED,
    HEALTH_QUARANTINED,
)

# Public-page application state (source-stated, never applicant-specific)
APPLICATION_OPEN = "application-open"
APPLICATION_NOTIFICATION_ONLY = "notification-only"
APPLICATION_CLOSED = "closed"
APPLICATION_UNKNOWN = UNKNOWN
ALL_APPLICATION_STATES = (
    APPLICATION_OPEN,
    APPLICATION_NOTIFICATION_ONLY,
    APPLICATION_CLOSED,
    APPLICATION_UNKNOWN,
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
