"""Deterministic classification and generic scoring.

All rules are transparent keyword/structured-field rules stored as score
components and reason codes. Nothing here decides applicant-specific
eligibility; that belongs to the private downstream layer.
"""
from __future__ import annotations

import re
from typing import Any

from . import constants as c
from .config import ScoringConfig
from .models import RawOpportunity, ScoreComponents

# Default keyword families. Each entry is a case-insensitive regex applied to
# title first; excerpt text contributes at reduced weight.
DEFAULT_FAMILIES: dict[str, list[str]] = {
    "ee-hardware": [r"\belectrical engineer", r"\bhardware engineer", r"\bpcb", r"\belectronics?\b",
                    r"\banalog\b", r"\brf engineer", r"\bsignal integrity", r"\bpower electronics"],
    "embedded-firmware": [r"embedded", r"\bfirmware\b", r"\bmicrocontroller", r"\brtos\b",
                          r"\bbsp\b", r"driver development", r"\blow[- ]level\b"],
    "semiconductor-fpga": [r"semiconductor", r"\bfpga\b", r"\bverilog\b", r"\bvhdl\b",
                           r"\basic\b", r"\brtl design", r"\bphysical design", r"\bdv engineer",
                           r"design verification", r"\basic\b", r"\bvlsi\b", r"\bprocess integration"],
    "robotics-controls": [r"robotic", r"\bcontrols? engineer", r"control systems", r"\bmechatronic",
                          r"\bautonomy\b", r"perception engineer", r"\bslam\b", r"\bplc\b"],
    "power-energy": [r"\bpower systems?\b", r"\brenewable", r"\benergy systems?\b", r"\bgrid\b",
                     r"\bbattery\b", r"\belectrification"],
    "test-systems-manufacturing": [r"\btest engineer", r"\bvalidation engineer", r"\bverification engineer",
                                   r"\bmanufacturing engineer", r"\bsystems engineer", r"\breliability",
                                   r"\bquality engineer", r"\bprocess engineer", r"\byield engineer"],
    "software": [r"software engineer", r"software developer", r"\bswe\b", r"\bbackend\b", r"\bfrontend\b",
                 r"full[- ]stack", r"\bmobile engineer", r"\bios engineer", r"\bplatform engineer",
                 r"\bdevops\b", r"\bsite reliability", r"\bsre\b", r"\bcloud engineer", r"\bgame dev"],
    "ai-ml-data": [r"machine learning", r"\bml engineer", r"\bai\b", r"deep learning", r"\bdata scientist",
                   r"\bdata engineer", r"\bnlp\b", r"computer vision", r"\bresearch scientist",
                   r"\bapplied scientist", r"quantitative researcher"],
    "developer-tools": [r"developer tools", r"\bdevtools\b", r"\bcompiler", r"\boperating system",
                        r"\bkernel\b", r"\bdatabase engine", r"\bdeveloper experience"],
    "quant-tech": [r"quantitative", r"quant developer", r"quant research", r"trading technology",
                   r"\btrader\b", r"\bstrats\b", r"\btrading\b", r"financial technology", r"\bfintech\b"],
    "technical-research": [r"research assistant", r"\breu\b", r"undergraduate research",
                           r"research internship", r"research experience for undergraduates",
                           r"\blab position", r"summer research"],
    "discovery-insight": [r"\binsight", r"early insights?", r"discovery program", r"freshman",
                          r"sophomore", r"first[- ]year", r"second[- ]year", r"early career",
                          r"emerging talent", r"exploration", r"fast[- ]track"],
    "recruiting-event": [r"career fair", r"recruiting event", r"networking night", r"tech talk",
                         r"information session", r"interview day", r"hiring event", r"\bexpo\b"],
    "funded-conference": [r"grace hopper", r"\bghc\b", r"\bnsbe\b", r"\bshpe\b", r"tapia",
                          r"society of women engineers", r"\bswe conference", r"conference.*grant",
                          r"scholarship.*conference", r"travel grant", r"funded conference"],
    "travel-program": [r"travel grant", r"travel funding", r"travel scholarship", r"fully funded",
                       r"all[- ]expenses[- ]paid", r"stipend provided"],
    "campus-leadership": [r"campus (ambassador|lead|evangelist)", r"student partner",
                          r"developer student", r"community lead", r"student program",
                          r"campus captain", r"\bdeveloper advocate.*student"],
    "adjacent-selective": [r"investment banking", r"quantitative finance", r"prop trading",
                           r"summer analyst", r"insight program"],
}

PAID_RE = re.compile(r"(\$\s?\d[\d,.]*\s*(?:/|per\s)?\s*(?:hr|hour)|\$\s?\d{2,}[\d,.]*\s*(?:k|,000)?|"
                     r"\bpaid\b|\bhourly\b|salary|stipend)", re.IGNORECASE)
FUNDED_RE = re.compile(r"(fully[- ]funded|travel grant|funding available|no cost|free to attend|"
                       r"expenses paid|scholarship covers|stipend)", re.IGNORECASE)
RELOCATION_RE = re.compile(r"(relocation (support|assistance|package)|relocat\w+ (support|provided)|"
                           r"housing (provided|stipend|support))", re.IGNORECASE)
COOP_RE = re.compile(r"\bco[- ]?op\b|cooperative education", re.IGNORECASE)
SCHOOL_TERM_RE = re.compile(r"\b(fall|winter|spring)\s+(19|20)\d{2}\b", re.IGNORECASE)
ONLINE_HACKATHON_RE = re.compile(r"online hackathon|virtual hackathon", re.IGNORECASE)
HACKATHON_VALUE_RE = re.compile(r"(recruit|interview|prize \$|funding|sponsor.*(hiring|recruit)|"
                                r"onsite|in[- ]person)", re.IGNORECASE)
EVENT_EXPENSIVE_RE = re.compile(r"(\$\s?\d{3,}.*(?:registration|ticket)|registration fee)", re.IGNORECASE)

EFFORT_QUICK_RE = re.compile(r"(resume only|resume required only|no cover letter)", re.IGNORECASE)
EFFORT_SUBSTANTIAL_RE = re.compile(r"(transcript|letters? of recommendation|essay|writing sample|"
                                   r"cover letter required|multiple rounds)", re.IGNORECASE)
COMPONENTS_RESUME_RE = re.compile(r"(resume|cv)", re.IGNORECASE)
COMPONENTS_COVER_RE = re.compile(r"cover letter", re.IGNORECASE)
COMPONENTS_TRANSCRIPT_RE = re.compile(r"transcript", re.IGNORECASE)
COMPONENTS_RECS_RE = re.compile(r"(letters? of recommendation|references)", re.IGNORECASE)
COMPONENTS_ESSAY_RE = re.compile(r"(essay|personal statement|writing sample)", re.IGNORECASE)

SEASON_RE = re.compile(r"\b(summer|fall|spring|winter)\s*(19|20)(\d{2})\b", re.IGNORECASE)
CLASS_YEAR_RE = re.compile(r"(freshman|sophomore|junior|senior|first[- ]year|second[- ]year|"
                           r"rising (freshman|sophomore|junior|senior)|undergrad\w*)", re.IGNORECASE)
GRAD_WINDOW_RE = re.compile(r"(graduat\w+ (date|window|between)|class of \d{4})", re.IGNORECASE)
MAJOR_RE = re.compile(r"(major\w* in|degree in|pursuing a? ?(bs|ba|b?s|ms|phd)|"
                      r"(electrical|computer|mechanical) engineering|computer science)", re.IGNORECASE)
WORK_AUTH_RE = re.compile(r"(work authorization|sponsorship|authorized to work|"
                          r"us citizen|permanent resident|visa sponsor)", re.IGNORECASE)


def _match_family(text: dict[str, str], family: str,
                  patterns: list[str]) -> float | None:
    title_part = text.get("title", "")
    excerpt_part = text.get("excerpt", "")
    for pattern in patterns:
        if re.search(pattern, title_part, re.IGNORECASE):
            return 1.0
        if excerpt_part and re.search(pattern, excerpt_part, re.IGNORECASE):
            return 0.5
    return None


def classify(
    raw: RawOpportunity, scoring_cfg: ScoringConfig
) -> tuple[list[str], ScoreComponents, dict[str, Any], list[str]]:
    """Return (role_family_tags, score_components, signals, reason_codes)."""
    families = scoring_cfg.families or DEFAULT_FAMILIES
    text = {"title": raw.title or "", "excerpt": raw.description_excerpt or ""}
    combined = " ".join([raw.title or "", raw.description_excerpt or "",
                         raw.compensation_text or ""])

    tags: list[str] = []
    components = ScoreComponents()
    for family, patterns in families.items():
        if not isinstance(patterns, list):
            continue
        weight = _match_family(text, family, patterns)
        if weight:
            tags.append(family)
            components.family_weights[family] = round(components.family_weights.get(family, 0) + weight, 3)

    signals: dict[str, Any] = {}
    reasons: list[str] = []

    if raw.compensation_text and PAID_RE.search(raw.compensation_text):
        signals["paid"] = True
        components.bonuses["paid"] = scoring_cfg.bonus_paid
    elif raw.compensation_text:
        signals["compensation_stated"] = True
    if raw.compensation_text and FUNDED_RE.search(raw.compensation_text):
        signals["funded"] = True
        components.bonuses["funded"] = scoring_cfg.bonus_funded
    if raw.deadline:
        components.bonuses["deadline-known"] = scoring_cfg.bonus_deadline_known
    if raw.remote_signal in ("remote", "hybrid"):
        components.bonuses["location-flexible"] = scoring_cfg.bonus_remote

    if raw.relocation_text and RELOCATION_RE.search(raw.relocation_text):
        signals["relocation-support"] = c.EVIDENCE_SOURCE_STATED

    # Suppression: school-term co-ops (kept in SQLite with reason code).
    if scoring_cfg.coop_suppress and COOP_RE.search(combined) and SCHOOL_TERM_RE.search(combined):
        reasons.append(c.EXCLUDE_COOP_SCHOOL_TERM)
        signals["school-term-coop"] = True

    # Online hackathons: suppress unless unusually strong value signals.
    online_hackathon = (
        scoring_cfg.online_hackathon_suppress and bool(ONLINE_HACKATHON_RE.search(combined))
    )
    if online_hackathon and HACKATHON_VALUE_RE.search(combined):
        signals["hackathon-strong-value"] = True
    elif online_hackathon:
        reasons.append(c.EXCLUDE_ONLINE_HACKATHON)
        signals["online-hackathon"] = True

    # Expensive distant unfunded events: down-rank, retain.
    event_lane = "funded-conference" in tags or "recruiting-event" in tags
    if (event_lane and EVENT_EXPENSIVE_RE.search(combined)
            and not signals.get("funded")):
        components.penalties["unfunded-expensive-event"] = (
            scoring_cfg.penalty_unfunded_distant_event)
        reasons.append(c.DOWNRANK_EXPENSIVE_EVENT)
        signals["expensive-event"] = True

    # Unpaid retention rule: keep unpaid only with exceptional generic signals.
    if not signals.get("paid") and not signals.get("funded"):
        exceptional_families = {
            "technical-research", "discovery-insight", "funded-conference", "travel-program"
        }
        exceptional = bool(exceptional_families & set(tags))
        if not exceptional and components.total < scoring_cfg.unpaid_retention_score_floor:
            reasons.append("downrank:unpaid-generic")
            signals["unpaid"] = True

    # Effort estimate from stated components only (unknown when nothing stated).
    requested: list[str] = []
    if COMPONENTS_RESUME_RE.search(combined):
        requested.append("resume")
    if COMPONENTS_COVER_RE.search(combined):
        requested.append("cover-letter")
    if COMPONENTS_TRANSCRIPT_RE.search(combined):
        requested.append("transcript")
    if COMPONENTS_RECS_RE.search(combined):
        requested.append("recommendations")
    if COMPONENTS_ESSAY_RE.search(combined):
        requested.append("essay")
    signals["requested_components"] = requested
    if EFFORT_QUICK_RE.search(combined):
        effort = c.EFFORT_QUICK
    elif EFFORT_SUBSTANTIAL_RE.search(combined) or len(requested) >= 3:
        effort = c.EFFORT_SUBSTANTIAL
    elif requested:
        effort = c.EFFORT_MODERATE
    else:
        effort = c.EFFORT_UNKNOWN
    signals["effort_estimate"] = effort

    if tags:
        reasons.append("include:broad-relevance")
    return tags, components, signals, reasons


def extract_explicit_language(raw: RawOpportunity) -> dict[str, str | None]:
    """Extract explicit class-year / graduation-window / major / work-auth language."""
    combined = " ".join(filter(None, [raw.title, raw.description_excerpt, raw.extra.get("requirements", "")]))
    out: dict[str, str | None] = {}
    m = CLASS_YEAR_RE.search(combined)
    out["class_year_language"] = m.group(0) if m else None
    m = GRAD_WINDOW_RE.search(combined)
    out["graduation_window_language"] = m.group(0) if m else None
    m = MAJOR_RE.search(combined)
    out["major_language"] = m.group(0) if m else None
    m = WORK_AUTH_RE.search(combined)
    out["work_auth_language"] = m.group(0) if m else None
    return out


def infer_season(raw: RawOpportunity, target_season: str, aliases: dict[str, str]) -> str | None:
    """Infer season from title/excerpt; configuration-driven, never hardcoded."""
    combined = " ".join(filter(None, [raw.title, raw.description_excerpt, raw.season or ""]))
    m = SEASON_RE.search(combined)
    if m:
        term = m.group(1).lower()
        year = m.group(2) + m.group(3)
        return f"{term}-{year}"
    if raw.season:
        norm = raw.season.strip().lower().replace(" ", "-")
        return aliases.get(norm, norm)
    return None
