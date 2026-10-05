"""Normalize public posting signals and route them through career profiles.

The module only classifies statements in public leads. It has no applicant
context and makes no applicant-specific eligibility or priority decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import constants as c
from .models import RawOpportunity
from .source_constraints import parse_constraints, program_evidence, staff_role


@dataclass(frozen=True)
class ProfileDecision:
    state: str
    confidence: str
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "routing_state": self.state,
            "eligibility_confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
        }


_ENGAGEMENT_PATTERNS = (
    (c.ENGAGEMENT_COOP, r"\bco[- ]?op\b|cooperative education"),
    (c.ENGAGEMENT_INTERNSHIP, r"\bintern(?:ship)?\b"),
    (c.ENGAGEMENT_FELLOWSHIP, r"\bfellow(?:ship)?\b"),
    (c.ENGAGEMENT_RESEARCH, r"\bresearch (?:assistant|experience|placement|role)\b|\breu\b"),
    (c.ENGAGEMENT_EVENT, r"career fair|conference|hackathon|recruiting event|tech talk|\bexpo\b"),
    (c.ENGAGEMENT_PROGRAM, r"\bprogram\b|\bscholarship\b|early insights?|discovery program"),
    (c.ENGAGEMENT_CONTRACT, r"\bcontract(?:or)?\b|\btemporary\b"),
    (c.ENGAGEMENT_FULL_TIME, r"full[- ]time|permanent position"),
)
_CAREER_PATTERNS = (
    (c.CAREER_NEW_GRAD, r"new grad(?:uate)?|recent grad(?:uate)?|graduate (?:role|program|position)"),
    (c.CAREER_ENTRY_LEVEL, r"entry[- ]level|early career|\bjunior (?:engineer|developer|analyst)\b"),
    (
        c.CAREER_EXPERIENCED,
        r"\b(?:senior|staff|principal|lead)\b(?=[^.\n]{0,40}"
        r"\b(?:engineer|developer|analyst|scientist)\b)|\bmanager\b",
    ),
    (c.CAREER_STUDENT, r"\bstudent\b|undergrad|freshman|sophomore|\bjunior\b|\bsenior\b"),
)
_DIRECTOR_TITLE_RE = re.compile(r"^\s*(?:(?:senior|sr\.?)\s+)?director\b(?!['’]s\b)", re.I)

_REQUIRED_DEGREE_PATTERNS = (
    (
        c.DEGREE_DOCTORATE,
        r"(?:ph\.?d\.?|doctorate|doctoral degree)\s+(?:is\s+)?required|"
        r"required[^.]{0,35}(?:ph\.?d\.?|doctorate|doctoral)",
    ),
    (
        c.DEGREE_MASTERS,
        r"(?:master'?s|master of|m\.?s\.?)\s+(?:degree\s+)?(?:is\s+)?required|"
        r"required[^.]{0,35}(?:master'?s|m\.?s\.?)",
    ),
    (
        c.DEGREE_BACHELORS,
        r"(?:bachelor'?s|bachelor of|b\.?s\.?|b\.?a\.?)\s+"
        r"(?:degree\s+)?(?:is\s+)?required|"
        r"required[^.]{0,35}(?:bachelor'?s|b\.?s\.?|b\.?a\.?)",
    ),
    (
        c.DEGREE_ASSOCIATE,
        r"associate(?:'s)? degree\s+(?:is\s+)?required|required[^.]{0,35}associate(?:'s)? degree",
    ),
    (c.DEGREE_HIGH_SCHOOL, r"high school diploma\s+(?:is\s+)?required|required[^.]{0,35}high school diploma"),
)
_PREFERRED_DEGREE_PATTERNS = (
    (
        c.DEGREE_DOCTORATE,
        r"(?:ph\.?d\.?|doctorate|doctoral degree)[^.]{0,20}preferred|"
        r"preferred[^.]{0,35}(?:ph\.?d\.?|doctorate|doctoral)",
    ),
    (
        c.DEGREE_MASTERS,
        r"(?:master'?s|m\.?s\.?)\s+(?:degree\s+)?preferred|preferred[^.]{0,35}(?:master'?s|m\.?s\.?)",
    ),
    (
        c.DEGREE_BACHELORS,
        r"(?:bachelor'?s|b\.?s\.?|b\.?a\.?)\s+(?:degree\s+)?preferred|preferred[^.]{0,35}(?:bachelor'?s|b\.?s\.?|b\.?a\.?)",
    ),
)
_GRADUATE_TITLE_RE = re.compile(r"\b(?:ph\.?d|doctoral|doctorate|master'?s)\b", re.I)
_RANGE_YEARS_RE = re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\+?\s+years?\b", re.I)
_UP_TO_YEARS_RE = re.compile(r"\b(?:up to|maximum(?: of)?|no more than)\s+(\d{1,2})\s+years?\b", re.I)
_MIN_YEARS_RE = re.compile(
    r"\b(?:at least|minimum(?: of)?)\s+(\d{1,2})\s+years?\b|\b(\d{1,2})\+\s+years?\b", re.I
)
_PLAIN_YEARS_RE = re.compile(
    r"\b(\d{1,2})\s+years?\s+(?:of\s+)?(?:professional |relevant )?experience\b", re.I
)

_ENGAGEMENT_VALUES = {
    c.ENGAGEMENT_INTERNSHIP,
    c.ENGAGEMENT_COOP,
    c.ENGAGEMENT_CONTRACT,
    c.ENGAGEMENT_RESEARCH,
    c.ENGAGEMENT_FELLOWSHIP,
    c.ENGAGEMENT_PROGRAM,
    c.ENGAGEMENT_EVENT,
    c.ENGAGEMENT_FULL_TIME,
}
_CAREER_VALUES = {
    c.CAREER_STUDENT,
    c.CAREER_NEW_GRAD,
    c.CAREER_ENTRY_LEVEL,
    c.CAREER_EXPERIENCED,
}
_DEGREE_VALUES = {
    c.DEGREE_HIGH_SCHOOL,
    c.DEGREE_ASSOCIATE,
    c.DEGREE_BACHELORS,
    c.DEGREE_MASTERS,
    c.DEGREE_DOCTORATE,
}


def _canonical(value: str | None, aliases: dict[str, str], allowed: set[str]) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("_", "-")
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else None


def _first_match(text: str, patterns: tuple[tuple[str, str], ...]) -> str:
    for value, pattern in patterns:
        if re.search(pattern, text, re.I):
            return value
    return c.UNKNOWN


def normalize_routing_fields(raw: RawOpportunity) -> dict[str, Any]:
    """Extract conservative normalized fields from structured/public text."""
    text = " ".join(
        x
        for x in (
            raw.title,
            raw.description_excerpt,
            raw.requirements_text,
            raw.employment_type,
        )
        if x
    )
    engagement = _canonical(
        raw.engagement_type,
        {"intern": c.ENGAGEMENT_INTERNSHIP, "coop": c.ENGAGEMENT_COOP, "full time": c.ENGAGEMENT_FULL_TIME},
        _ENGAGEMENT_VALUES,
    ) or _first_match(text, _ENGAGEMENT_PATTERNS)
    legacy = (raw.employment_type or "").strip().lower()
    legacy_map = {
        "intern": c.ENGAGEMENT_INTERNSHIP,
        "internship": c.ENGAGEMENT_INTERNSHIP,
        "co-op": c.ENGAGEMENT_COOP,
        "coop": c.ENGAGEMENT_COOP,
        "contract": c.ENGAGEMENT_CONTRACT,
        "fellowship": c.ENGAGEMENT_FELLOWSHIP,
        "program": c.ENGAGEMENT_PROGRAM,
        "event": c.ENGAGEMENT_EVENT,
        "full-time": c.ENGAGEMENT_FULL_TIME,
        "full time": c.ENGAGEMENT_FULL_TIME,
        "fulltime": c.ENGAGEMENT_FULL_TIME,
        "permanent": c.ENGAGEMENT_FULL_TIME,
        "new-grad": c.ENGAGEMENT_FULL_TIME,
    }
    if raw.engagement_type is None and legacy in legacy_map:
        engagement = legacy_map[legacy]

    # Hours and provider metadata do not override an explicit student role.
    if re.search(r"\bintern(?:ship)?\b", raw.title or "", re.I):
        engagement = c.ENGAGEMENT_INTERNSHIP
    elif re.search(r"\bco[- ]?op\b", raw.title or "", re.I):
        engagement = c.ENGAGEMENT_COOP
    elif (
        raw.engagement_type is None
        and engagement
        in {
            c.ENGAGEMENT_EVENT,
            c.ENGAGEMENT_PROGRAM,
            c.ENGAGEMENT_FELLOWSHIP,
        }
        and not program_evidence(
            raw.title or "",
            raw.requirements_text or "",
            configured=bool(raw.program_family_id or raw.overview_url),
        )
    ):
        engagement = (
            c.ENGAGEMENT_FULL_TIME
            if legacy in {"full-time", "fulltime", "full time", "permanent"} or staff_role(raw.title or "")
            else c.UNKNOWN
        )

    career_stage = _canonical(
        raw.career_stage,
        {"new graduate": c.CAREER_NEW_GRAD, "entry level": c.CAREER_ENTRY_LEVEL},
        _CAREER_VALUES,
    )
    if not career_stage:
        if engagement in {c.ENGAGEMENT_INTERNSHIP, c.ENGAGEMENT_COOP} and re.search(
            r"\bintern(?:ship)?\b|\bco[- ]?op\b", raw.title or "", re.I
        ):
            career_stage = c.CAREER_STUDENT
        else:
            career_stage = _first_match(raw.title or "", _CAREER_PATTERNS)
            if career_stage == c.UNKNOWN:
                # A manager or senior colleague in the description is not the
                # advertised role. Only title evidence infers experienced level.
                career_stage = _first_match(
                    text,
                    tuple(p for p in _CAREER_PATTERNS if p[0] not in {c.CAREER_EXPERIENCED, c.CAREER_STUDENT})
                    + ((c.CAREER_STUDENT, r"\bstudents?\b|undergrad|freshman|sophomore|currently enrolled"),),
                )
    if raw.career_stage is None and _DIRECTOR_TITLE_RE.search(raw.title or ""):
        career_stage = c.CAREER_EXPERIENCED
    if career_stage == c.UNKNOWN and engagement in {
        c.ENGAGEMENT_INTERNSHIP,
        c.ENGAGEMENT_COOP,
        c.ENGAGEMENT_RESEARCH,
        c.ENGAGEMENT_FELLOWSHIP,
    }:
        career_stage = c.CAREER_STUDENT
    if career_stage == c.UNKNOWN and legacy == "new-grad":
        career_stage = c.CAREER_NEW_GRAD

    degree_aliases = {
        "bachelor": c.DEGREE_BACHELORS,
        "bachelor's": c.DEGREE_BACHELORS,
        "master": c.DEGREE_MASTERS,
        "master's": c.DEGREE_MASTERS,
        "phd": c.DEGREE_DOCTORATE,
        "doctoral": c.DEGREE_DOCTORATE,
    }
    required_degree = _canonical(raw.required_degree, degree_aliases, _DEGREE_VALUES) or _first_match(
        text, _REQUIRED_DEGREE_PATTERNS
    )
    preferred_degree = _canonical(raw.preferred_degree, degree_aliases, _DEGREE_VALUES) or _first_match(
        text, _PREFERRED_DEGREE_PATTERNS
    )
    constraints = (
        raw.source_constraints
        if raw.source_constraints is not None
        else parse_constraints(raw.requirements_text or "")
    )
    all_education = [rule for rule in constraints if rule["kind"] == "education"]
    education = [
        rule for rule in constraints if rule["kind"] == "education" and rule["modality"] == "required"
    ]
    if all_education and not education:
        required_degree = c.UNKNOWN
    if education:
        if any(rule["exception"] or rule.get("degree_operator") == "unknown" for rule in education):
            required_degree = c.UNKNOWN
        else:
            order = ("bachelors", "masters", "doctorate")
            # Alternatives within a clause permit the lowest stated degree;
            # separate mandatory clauses must all be satisfied.
            minima = [
                (max if rule.get("degree_operator") == "all" else min)(
                    order.index(d) for d in rule["degrees"]
                )
                for rule in education
                if rule["degrees"]
            ]
            if minima:
                required_degree = order[max(minima)]

    exp_text = raw.experience_requirement_text
    if exp_text is None and not raw.extra.get("requirements_extracted"):
        match = _RANGE_YEARS_RE.search(text) or _UP_TO_YEARS_RE.search(text) or _MIN_YEARS_RE.search(text)
        if match is None:
            match = _PLAIN_YEARS_RE.search(text)
        exp_text = match.group(0) if match else None
    exp_min: int | None = None
    exp_max: int | None = None
    if exp_text:
        if match := _RANGE_YEARS_RE.search(exp_text):
            exp_min, exp_max = int(match.group(1)), int(match.group(2))
        elif match := _UP_TO_YEARS_RE.search(exp_text):
            exp_max = int(match.group(1))
        elif match := _MIN_YEARS_RE.search(exp_text):
            exp_min = int(match.group(1) or match.group(2))
        elif match := _PLAIN_YEARS_RE.search(exp_text):
            exp_min = int(match.group(1))

    return {
        "engagement_type": engagement,
        "career_stage": career_stage,
        "required_degree": required_degree,
        "preferred_degree": preferred_degree,
        "graduate_degree_title_signal": bool(_GRADUATE_TITLE_RE.search(raw.title or "")),
        "experience_requirement_text": exp_text,
        "experience_min_years": exp_min,
        "experience_max_years": exp_max,
    }


def route_profiles(fields: dict[str, Any]) -> dict[str, ProfileDecision]:
    """Return decisions for every shipped profile from normalized public facts."""
    engagement = fields["engagement_type"]
    stage = fields["career_stage"]
    degree = fields["required_degree"]
    exp_min = fields["experience_min_years"]
    exp_max = fields["experience_max_years"]

    student_reasons: list[str] = []
    if degree in {c.DEGREE_MASTERS, c.DEGREE_DOCTORATE}:
        student = ProfileDecision(
            c.ROUTE_EXCLUDED, c.CONFIDENCE_HIGH, (f"profile:graduate-degree-required:{degree}",)
        )
    elif engagement == c.ENGAGEMENT_FULL_TIME:
        student = ProfileDecision(c.ROUTE_EXCLUDED, c.CONFIDENCE_HIGH, ("profile:full-time-excluded",))
    elif stage == c.CAREER_EXPERIENCED:
        student = ProfileDecision(
            c.ROUTE_EXCLUDED, c.CONFIDENCE_HIGH, ("profile:experienced-stage-excluded",)
        )
    elif fields.get("graduate_degree_title_signal"):
        student = ProfileDecision(
            c.ROUTE_RESEARCH, c.CONFIDENCE_LOW, ("profile:graduate-degree-title-unverified",)
        )
    elif engagement in {
        c.ENGAGEMENT_INTERNSHIP,
        c.ENGAGEMENT_COOP,
        c.ENGAGEMENT_RESEARCH,
        c.ENGAGEMENT_FELLOWSHIP,
        c.ENGAGEMENT_PROGRAM,
        c.ENGAGEMENT_EVENT,
    }:
        student = ProfileDecision(c.ROUTE_INCLUDED, c.CONFIDENCE_HIGH, ("profile:student-opportunity",))
    elif engagement == c.ENGAGEMENT_CONTRACT and stage in {c.CAREER_STUDENT, c.CAREER_ENTRY_LEVEL}:
        student = ProfileDecision(c.ROUTE_INCLUDED, c.CONFIDENCE_HIGH, ("profile:early-career-contract",))
    else:
        student_reasons.append("profile:student-fit-ambiguous")
        student = ProfileDecision(c.ROUTE_RESEARCH, c.CONFIDENCE_LOW, tuple(student_reasons))

    if engagement in {
        c.ENGAGEMENT_INTERNSHIP,
        c.ENGAGEMENT_COOP,
        c.ENGAGEMENT_RESEARCH,
        c.ENGAGEMENT_FELLOWSHIP,
        c.ENGAGEMENT_PROGRAM,
        c.ENGAGEMENT_EVENT,
    }:
        new_grad = ProfileDecision(c.ROUTE_EXCLUDED, c.CONFIDENCE_HIGH, ("profile:non-full-time-excluded",))
    elif stage == c.CAREER_EXPERIENCED or (exp_min is not None and exp_min >= 5):
        new_grad = ProfileDecision(c.ROUTE_EXCLUDED, c.CONFIDENCE_HIGH, ("profile:experience-five-plus",))
    elif (
        engagement == c.ENGAGEMENT_FULL_TIME
        and stage in {c.CAREER_NEW_GRAD, c.CAREER_ENTRY_LEVEL}
        and (exp_max is None or exp_max <= 4)
    ):
        new_grad = ProfileDecision(c.ROUTE_INCLUDED, c.CONFIDENCE_HIGH, ("profile:new-grad-full-time",))
    else:
        new_grad = ProfileDecision(c.ROUTE_RESEARCH, c.CONFIDENCE_LOW, ("profile:new-grad-fit-ambiguous",))

    all_opportunities = ProfileDecision(c.ROUTE_INCLUDED, c.CONFIDENCE_HIGH, ("profile:all-opportunities",))
    return {
        c.PROFILE_STUDENT: student,
        c.PROFILE_NEW_GRAD: new_grad,
        c.PROFILE_ALL: all_opportunities,
    }
