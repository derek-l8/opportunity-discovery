"""Deterministic personal screening, persisted only in an external workspace.

Screening uses collector statements, never claims an official-page check, and
never changes public routing or the user's private board decisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .extraction import academic_major_language, required_statements
from .source_constraints import (
    duration_limits,
    graduation_windows,
    program_evidence,
    staff_role,
    term_time_placement,
    travel_funding,
)
from .workspace_board import _lane as board_lane
from .workspace_board import _pipeline_state
from .workspace_constraints import candidate_constraints, compare_constraints, evidence_packet
from .workspace_discovery import _board_records, _has_imported_decision, _page, load_current_queue
from .workspace_state import (
    OPPORTUNITY_ID,
    WorkspaceStateError,
    _atomic_json,
    _object,
    _parsed_timestamp,
    _read_json,
    _secure_workspace_path,
    _validate_reference,
    require_workspace,
)

SCREENING_VERSION = "11"
FOCUS_MODES = ("early-opportunities", "standard-internships", "new-grad")
LOCATION_POLICIES = ("prefer-local", "local-only", "local-jobs-funded-programs")
STATES = ("worth-investigating", "needs-clarification", "low-relevance")
REVIEW_ACTIONS = (
    "official-research",
    "clarify-source",
    "clarify-profile",
    "reuse-findings",
    "await-new-evidence",
    "low-priority",
    "outside-stage-focus",
    "role-outside-focus",
    "recoverable-exclusion",
    "respect-user-decision",
)
LANES = (
    "research",
    "early-year-programs",
    "scholarships",
    "campus-networking",
    "technical-commercial",
    "engineering-internships",
    "other",
)
MATERIAL_FIELDS = (
    "title",
    "organization",
    "canonical_url",
    "official_url",
    "location_text",
    "remote_signal",
    "engagement_type",
    "career_stage",
    "required_degree",
    "source_constraints",
    "preferred_degree",
    "experience_requirement",
    "class_year_language",
    "graduation_window_language",
    "major_language",
    "work_auth_language",
    "requirements_text",
    "description_excerpt",
    "compensation_text",
    "relocation_text",
    "stated_deadline",
    "event_start_date",
    "event_end_date",
    "application_state",
    "active",
    "season",
)
_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    """Ignore collection timestamps, generic scores, and transport churn."""
    return _hash({key: candidate.get(key) for key in MATERIAL_FIELDS})


def validate_profile(document: Any) -> dict[str, Any]:
    profile = _object(document, "screening profile")
    allowed = {
        "schema_version",
        "graduation_month",
        "student_status",
        "degree",
        "completed_degrees",
        "citizenships",
        "institution_regions",
        "term_time_work",
        "majors",
        "major_match_terms",
        "location_regions",
        "location_policy",
        "year_in_program",
        "unit_based_standing",
        "remote_work",
        "interest_keywords",
        "opportunity_focus",
        "max_required_experience_years",
        "employer_cap",
        "stale_after_days",
        "source_refs",
        "custom",
    }
    if set(profile) - allowed or profile.get("schema_version") != "1.0":
        raise WorkspaceStateError("invalid screening profile schema or unknown fields")
    result = {
        "schema_version": "1.0",
        "graduation_month": None,
        "student_status": None,
        "degree": None,
        "completed_degrees": None,
        "citizenships": [],
        "institution_regions": [],
        "term_time_work": None,
        "majors": [],
        "major_match_terms": [],
        "location_regions": [],
        "location_policy": "prefer-local",
        "year_in_program": None,
        "unit_based_standing": None,
        "remote_work": None,
        "interest_keywords": [],
        "opportunity_focus": None,
        "max_required_experience_years": None,
        "employer_cap": 3,
        "stale_after_days": 30,
        "source_refs": [],
        "custom": {},
        **profile,
    }
    for field in ("majors", "major_match_terms", "interest_keywords", "source_refs"):
        values = result[field]
        if (
            not isinstance(values, list)
            or len(values) > 100
            or not all(isinstance(value, str) and 0 < len(value.strip()) <= 200 for value in values)
        ):
            raise WorkspaceStateError(f"screening profile {field} must contain bounded strings")
        result[field] = list(dict.fromkeys(value.strip() for value in values))
    regions = result["location_regions"]
    if not isinstance(regions, list) or len(regions) > 30:
        raise WorkspaceStateError("location_regions must be a bounded array")
    result["location_regions"] = []
    for original in regions:
        if not isinstance(original, dict):
            raise WorkspaceStateError("each location region must be an object")
        region = dict(original)
        required = {"label", "match_terms", "context_terms"}
        if not required <= set(region) or set(region) - required - {
            "scope",
            "allow_city_only",
            "source_urls",
        }:
            raise WorkspaceStateError("each region requires label, match_terms and context_terms")
        region.setdefault("scope", "metro")
        region.setdefault("allow_city_only", True)
        region.setdefault("source_urls", [])
        if region["scope"] not in {"metro", "city"} or type(region["allow_city_only"]) is not bool:
            raise WorkspaceStateError("invalid region scope or allow_city_only")
        urls = region["source_urls"]
        if (
            not isinstance(urls, list)
            or len(urls) > 20
            or not all(
                isinstance(url, str) and len(url) <= 2000 and re.fullmatch(r"https?://[^\s]+", url)
                for url in urls
            )
        ):
            raise WorkspaceStateError("invalid region source_urls")
        if not isinstance(region["label"], str) or not 1 <= len(region["label"].strip()) <= 200:
            raise WorkspaceStateError("invalid location region label")
        for field in ("match_terms", "context_terms"):
            values = region[field]
            if (
                not isinstance(values, list)
                or len(values) > (500 if field == "match_terms" else 100)
                or not all(isinstance(term, str) and 0 < len(term.strip()) <= 200 for term in values)
                or field == "match_terms"
                and not values
            ):
                raise WorkspaceStateError(f"invalid region {field}")
            region[field] = list(dict.fromkeys(term.strip() for term in values))
        result["location_regions"].append(region)
    if result["year_in_program"] is not None and (
        type(result["year_in_program"]) is not int or not 1 <= result["year_in_program"] <= 8
    ):
        raise WorkspaceStateError("year_in_program must be an integer from 1 to 8 or null")
    if result["unit_based_standing"] not in (None, "freshman", "sophomore", "junior", "senior"):
        raise WorkspaceStateError("invalid unit_based_standing")
    if result["remote_work"] is not None and type(result["remote_work"]) is not bool:
        raise WorkspaceStateError("remote_work must be boolean or null")
    for index, reference in enumerate(result["source_refs"]):
        _validate_reference(reference, f"source_refs[{index}]")
    if result["graduation_month"] is not None:
        value = result["graduation_month"]
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise WorkspaceStateError("graduation_month must be YYYY-MM or null")
        try:
            date.fromisoformat(value + "-01")
        except ValueError as exc:
            raise WorkspaceStateError("graduation_month is invalid") from exc
    if result["student_status"] not in (None, "undergraduate", "graduate", "not-enrolled"):
        raise WorkspaceStateError("invalid student_status")
    if result["degree"] not in (None, "bachelors", "masters", "doctorate", "associate", "high-school"):
        raise WorkspaceStateError("invalid degree")
    completed = result["completed_degrees"]
    if completed is not None and (
        not isinstance(completed, list)
        or len(completed) > 10
        or any(
            degree not in {"bachelors", "masters", "doctorate", "associate", "high-school"}
            for degree in completed
        )
    ):
        raise WorkspaceStateError("completed_degrees must be documented degree options, null for unknown")
    for field in ("citizenships", "institution_regions"):
        values = result[field]
        if (
            not isinstance(values, list)
            or len(values) > 30
            or any(not isinstance(v, str) or not re.fullmatch(r"[A-Z]{2}", v) for v in values)
        ):
            raise WorkspaceStateError(f"invalid {field}; use documented two-letter country/region codes")
        result[field] = sorted(set(values))
    if result["term_time_work"] is not None and type(result["term_time_work"]) is not bool:
        raise WorkspaceStateError("term_time_work must be boolean or null")
    if result["opportunity_focus"] not in (None, *FOCUS_MODES):
        raise WorkspaceStateError("invalid opportunity_focus")
    if result["location_policy"] not in LOCATION_POLICIES:
        raise WorkspaceStateError("invalid location_policy")
    for field, minimum, maximum in (
        ("employer_cap", 1, 100),
        ("stale_after_days", 1, 365),
        ("max_required_experience_years", 0, 50),
    ):
        value = result[field]
        if value is None and field == "max_required_experience_years":
            continue
        if type(value) is not int or not minimum <= value <= maximum:
            raise WorkspaceStateError(f"invalid {field}")
    _object(result["custom"], "screening profile custom")
    return result


def _path(root: Path, filename: str) -> Path:
    root, metadata = require_workspace(root)
    engine = metadata.get("engine_path")
    if engine and root.is_relative_to(Path(engine).resolve()):
        raise WorkspaceStateError("screening state must be outside the engine checkout")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise WorkspaceStateError("screening state must be outside a Git checkout")
    return _secure_workspace_path(root, root / ".opdisc", root / ".opdisc" / filename, "private screening")


def set_screening_profile(root: Path, document: Any) -> dict[str, Any]:
    profile = validate_profile(document)
    path = _path(root, "screening-profile.json")
    if path.exists():
        validate_profile(_read_json(path, {}))
    _atomic_json(path, profile)
    return {"schema_version": "1.0", "profile_path": path.relative_to(root.resolve()).as_posix()}


def load_profile(root: Path) -> dict[str, Any]:
    path = _path(root, "screening-profile.json")
    if not path.exists():
        raise WorkspaceStateError(
            "Ask your AI to configure a private screening profile for personalized Explore."
        )
    return validate_profile(_read_json(path, {}))


def screening_profile_exists(root: Path) -> bool:
    return _path(root, "screening-profile.json").exists()


def _lane(candidate: dict[str, Any]) -> str:
    text = str(candidate.get("title") or "").casefold()
    engagement = candidate.get("engagement_type")
    if "scholarship" in text:
        return "scholarships"
    if engagement == "event" or re.search(r"workshop|campus|ambassador|career fair|networking", text):
        return "campus-networking"
    if engagement == "research" or re.search(r"research|\breu\b|\bsurf\b", text):
        return "research"
    if re.search(r"sales|product|marketing|venture|commercial|business development", text):
        return "technical-commercial"
    if engagement in {"program", "fellowship"} or re.search(
        r"first.year|early.insight|discovery program", text
    ):
        return "early-year-programs"
    if engagement in {"internship", "co-op"}:
        return "engineering-internships"
    return "other"


_EARLY_YEAR = re.compile(r"\bfreshm[ae]n\b|\bsophomores?\b|\b(?:first|second|1st|2nd)[ -]year\b", re.I)
_UPPER_YEAR = re.compile(r"\bjuniors?\b|\bseniors?\b|\b(?:third|fourth|3rd|4th)[ -]year\b", re.I)
_PROGRAM_FORM = re.compile(
    r"\bprogram(?:me)?s?\b(?!\s+(?:manager|director|management|coordinator|officer))|"
    r"\bscholarship|\bfellowship|\bsummit|\bacademy|\bworkshop|\bconference|\bopen day|\bspring week",
    re.I,
)
_EXPLORATORY = re.compile(
    r"\bexplorat(?:ory|ion)\b|\bdiscovery\b|\binsights?\b|\bimmersion\b|"
    r"\bspring weeks?\b|\bpre[ -]internship\b",
    re.I,
)
_NEW_GRAD = re.compile(
    r"\bnew[ -]grad(?:uate)?s?\b|\bentry[ -]level\b|\bgraduate (?:program|scheme|trainee)\b", re.I
)


def _early_student_cue(text: str, *, title: bool = False) -> bool:
    """Require an academic year, not time at work or a company anniversary."""
    for statement in re.split(r"\n+|(?<=[.!?])\s+", text):
        cue = _EARLY_YEAR.search(statement)
        if not cue:
            continue
        context = statement[max(0, cue.start() - 140) : cue.end() + 140]
        if re.search(
            r"law school|medical school|graduate school|doctoral|\bPhD\b|master['’]?s", context, re.I
        ) and not re.search(r"undergrad|bachelor", context, re.I):
            continue
        # A lower bound does not dedicate an internship to the first two years.
        if re.search(
            r"(?:at least|minimum|completed).{0,45}(?:sophomore|(?:first|second)[ -]year)|"
            r"sophomore.{0,35}\b(?:or|and)\s+(?:above|higher|beyond)",
            context,
            re.I,
        ):
            continue
        if re.search(r"freshm[ae]n|sophomore", cue.group(), re.I):
            return True
        if re.search(r"\bstudents?\b|undergrad|college|university|bachelor|academic", context, re.I):
            return True
        if title and (re.search(r"\bintern(?:ship)?\b", text, re.I) or _PROGRAM_FORM.search(text)):
            return True
    return False


def _focus_match(candidate: dict[str, Any], mode: str | None) -> dict[str, Any]:
    """Stage preference from source cues, independently of unresolved eligibility.

    Broad exploration is intentional. A program can be preferred with a question
    about subject relevance; explicit eligibility mismatches still take precedence.
    Ordinary 'consumer insights' or 'drug discovery' jobs are not program cues.
    """
    title = str(candidate.get("title") or "")
    engagement = candidate.get("engagement_type")
    qualifiers = " ".join(
        str(candidate.get(key) or "") for key in ("class_year_language", "requirements_text")
    )
    internship = engagement in {"internship", "co-op"} or bool(
        re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I)
    )
    title_internship = bool(re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I))
    type_conflict = not title_internship and (
        bool(re.search(r"\binternal\b|\binternational\b", title, re.I))
        or candidate.get("career_stage") in {"new-grad", "entry-level"}
    )
    if type_conflict:
        internship = False
    # Generic public routing may infer "program" from workplace benefit text.
    # A title or an explicitly configured program page is stronger evidence.
    program = program_evidence(
        title,
        qualifiers + " " + str(candidate.get("description_excerpt") or ""),
        configured=bool(candidate.get("program_family_id") or candidate.get("overview_url")),
    )
    if not (
        _PROGRAM_FORM.search(title) or candidate.get("program_family_id") or candidate.get("overview_url")
    ) and re.search(r"\b(?:engineer|scientist|analyst|designer|technician)\b", title, re.I):
        program = False
    if not title_internship and (
        engagement in {"full-time", "contract"}
        or re.search(r"\b(?:manager|director|head|lead|specialist|coordinator|officer)\b", title, re.I)
    ):
        program = False
    early_field = next(
        (
            key
            for key in ("title", "class_year_language", "requirements_text")
            if _early_student_cue(str(candidate.get(key) or ""), title=key == "title")
        ),
        None,
    )
    # All-year internships remain useful, but are not dedicated early-year roles.
    dedicated_early = bool(early_field) and not _UPPER_YEAR.search(qualifiers)
    student_research = engagement == "research" and bool(
        re.search(r"research assistant|research experience|\breu\b", title, re.I)
        or re.search(r"undergrad|currently enrolled", str(candidate.get("class_year_language") or ""), re.I)
    )
    exploratory = program and bool(_EXPLORATORY.search(title))
    match, message, field = "other", "Outside the selected stage's main emphasis.", "title"
    if mode is None:
        match, message = "unspecified", "No opportunity-stage preference configured."
    elif mode == "early-opportunities":
        if dedicated_early:
            match, message, field = (
                "preferred",
                "Source mentions freshman, sophomore, or first/second-year opportunities.",
                early_field or "title",
            )
        elif exploratory:
            match, message = "preferred", "Exploratory program prioritized broadly in early-opportunity mode."
        elif program or internship or student_research:
            match, message = (
                "related",
                "Supporting student opportunity; no dedicated early-year cue captured.",
            )
    elif mode == "standard-internships":
        if internship:
            match = "related" if dedicated_early else "preferred"
            message = "Standard undergraduate internship focus; class-year eligibility still needs checking."
        elif program or student_research:
            match, message = "related", "Supporting program or research opportunity."
    elif mode == "new-grad":
        if (
            not internship
            and engagement in {None, "unknown", "full-time"}
            and (candidate.get("career_stage") in {"new-grad", "entry-level"} or _NEW_GRAD.search(title))
        ):
            match, message = (
                "preferred",
                "Entry-level or new-graduate job cue; employment type still needs checking if unknown.",
            )
        elif engagement in {"full-time", "contract"} or program:
            match, message = "related", "Broader job or program; new-graduate suitability is unresolved."
    evidence = str(candidate.get(field) or "")
    if dedicated_early and (cue := _EARLY_YEAR.search(evidence)):
        evidence = evidence[max(0, cue.start() - 100) :]
    return {
        "mode": mode,
        "match": match,
        "priority": {"preferred": 0, "related": 1, "other": 2, "unspecified": 0}[match],
        "field": field,
        "evidence": evidence[:600],
        "message": message,
        "program": program,
    }


def _graduation_range(language: str) -> tuple[str, str] | None:
    """Recognize explicit inclusive month/year ranges; ambiguous rules stay questions."""
    if re.search(r"\b(?:before|after|not|or|preferred|desirable|example)\b|[<>]", language, re.I):
        return None
    token = (
        r"(?:(January|February|March|April|May|June|July|August|September|October|"
        r"November|December)\s+)?(20\d{2})"
    )
    ranged = re.search(token + r"\s*(?:and|to|through|[-–])\s*" + token, language, re.I)
    if ranged and len(re.findall(r"\b20\d{2}\b", language)) != 2:
        return None

    def month(name: str | None, year: str, fallback: str) -> str:
        return year + "-" + (f"{_MONTHS.index(name.casefold()) + 1:02}" if name else fallback)

    if ranged:
        return month(ranged[1], ranged[2], "01"), month(ranged[3], ranged[4], "12")
    years = re.findall(r"\b20\d{2}\b", language)
    if len(years) == 1 and re.search(r"class of|graduat\w* (?:in|date(?: of)?:?)", language, re.I):
        matched = re.search(token, language, re.I)
        if matched:
            return month(matched[1], matched[2], "01"), month(matched[1], matched[2], "12")
    return None


_US_STATES = dict(
    pair.split(":")
    for pair in [
        "AL:Alabama",
        "AK:Alaska",
        "AZ:Arizona",
        "AR:Arkansas",
        "CA:California",
        "CO:Colorado",
        "CT:Connecticut",
        "DE:Delaware",
        "DC:District of Columbia",
        "FL:Florida",
        "GA:Georgia",
        "HI:Hawaii",
        "ID:Idaho",
        "IL:Illinois",
        "IN:Indiana",
        "IA:Iowa",
        "KS:Kansas",
        "KY:Kentucky",
        "LA:Louisiana",
        "ME:Maine",
        "MD:Maryland",
        "MA:Massachusetts",
        "MI:Michigan",
        "MN:Minnesota",
        "MS:Mississippi",
        "MO:Missouri",
        "MT:Montana",
        "NE:Nebraska",
        "NV:Nevada",
        "NH:New Hampshire",
        "NJ:New Jersey",
        "NM:New Mexico",
        "NY:New York",
        "NC:North Carolina",
        "ND:North Dakota",
        "OH:Ohio",
        "OK:Oklahoma",
        "OR:Oregon",
        "PA:Pennsylvania",
        "RI:Rhode Island",
        "SC:South Carolina",
        "SD:South Dakota",
        "TN:Tennessee",
        "TX:Texas",
        "UT:Utah",
        "VT:Vermont",
        "VA:Virginia",
        "WA:Washington",
        "WV:West Virginia",
        "WI:Wisconsin",
        "WY:Wyoming",
    ]
)


_COUNTRIES = {
    "US": ("United States", "USA", "US"),
    "UK": ("United Kingdom", "UK", "England", "Scotland", "Wales"),
    **{
        name: (name,)
        for name in (
            "Canada",
            "Australia",
            "New Zealand",
            "Singapore",
            "Japan",
            "China",
            "India",
            "Germany",
            "France",
            "Spain",
            "Italy",
            "Ireland",
            "Netherlands",
            "Switzerland",
            "Sweden",
            "Norway",
            "Denmark",
            "Finland",
            "Poland",
            "Portugal",
            "Brazil",
            "Mexico",
            "Israel",
            "Taiwan",
            "South Korea",
            "Hong Kong",
            "United Arab Emirates",
            "South Africa",
        )
    },
}


def _location_parts(location: str) -> list[str]:
    # Boards often join distinct city/state pairs with commas. Keep each city's
    # context together instead of borrowing a state from another listed office.
    states = "|".join(re.escape(value) for pair in _US_STATES.items() for value in pair)
    separated = re.sub(r"(\b(?:" + states + r")),\s*(?=[^,]+,)", r"\1;", location, flags=re.I)
    return re.split(r"[;|\n]|\s+and\s+|\s*/\s*", separated)


def _region_matches(part: str, region: dict[str, Any]) -> bool:
    if not any(_contains(part, term) for term in region["match_terms"]):
        return False
    # Never borrow context from another office or accept a known namesake city
    # in another state/country, even when the configured country also matches.
    if _outside_region_context(part, [region]):
        return False
    explicit_countries = {
        country for country, aliases in _COUNTRIES.items() if any(_contains(part, alias) for alias in aliases)
    }
    configured_countries = {
        country
        for country, aliases in _COUNTRIES.items()
        if any(term.casefold() == alias.casefold() for term in region["context_terms"] for alias in aliases)
    }
    if any(
        term.casefold() in {code.casefold(), name.casefold()}
        for term in region["context_terms"]
        for code, name in _US_STATES.items()
    ):
        configured_countries.add("US")
    if configured_countries and explicit_countries - configured_countries:
        return False
    if not region["context_terms"] or any(_contains(part, term) for term in region["context_terms"]):
        return True
    return bool(region.get("allow_city_only", True))


def _major_matches(major: str, profile: dict[str, Any]) -> bool:
    if re.search(r"\b(?:not|except|excluding|excluded)\b|other than", major, re.I):
        return False  # Negative/exception clauses need interpretation, not a keyword approval.
    for term in [*profile["majors"], *profile.get("major_match_terms", [])]:
        text = major
        if term.casefold() == "engineering":
            # A broad engineering requirement can fit a configured engineering
            # family. A different named discipline is not that broad requirement.
            text = re.sub(
                r"\b(?:electrical|electronic|computer|mechanical|aerospace|civil|chemical|"
                r"industrial|biomedical|nuclear|software|systems|materials|manufacturing)\s+engineering\b",
                "",
                text,
                flags=re.I,
            )
        elif term.casefold() == "science":
            text = re.sub(r"\b(?:computer|data|social|political|physical)\s+science\b", "", text, flags=re.I)
        if _contains(text, term):
            return True
    return False


def _defined_program_year(student: str) -> set[int]:
    # Future/rising standing still needs the opportunity's timing checked.
    if re.search(
        r"\brising\b|\bby\b|\bat (?:the )?(?:start|time)\b|\bnext\b|\bwill\b|"
        r"or higher|at least|or equivalent",
        student,
        re.I,
    ):
        return set()
    years = set()
    for number, word in enumerate(("first", "second", "third", "fourth"), 1):
        if re.search(
            r"\b(?:" + word + "|" + str(number) + r"(?:st|nd|rd|th)?)"
            r"[ -]year\s+(?:of|in)\s+(?:(?:their|your|the|an?)\s+)?"
            r"(?:university|college|undergraduate|degree)\b",
            student,
            re.I,
        ):
            years.add(number)
    if years:
        for group in re.findall(
            r"((?:first|second|third|fourth)(?:\s*(?:,|and|or)\s*(?:first|second|third|fourth))+)[ -]year",
            student,
            re.I,
        ):
            years.update(
                number
                for number, word in enumerate(("first", "second", "third", "fourth"), 1)
                if word in group.lower()
            )
    return years


def _academic_standing_language(student: str) -> str:
    statements = re.split(r"\n+|(?<=[.!?])\s+", required_statements(student))
    return "\n".join(
        statement
        for statement in statements
        if re.search(
            r"\bstudents?\b|undergrad|university|college|\benrolled\b|class standing|"
            r"\bfreshm[ae]n\b|\bsophomores?\b|\b(?:junior|senior)\s+(?:standing|year)\b",
            statement,
            re.I,
        )
        or (
            re.search(r"\b(?:must|minimum|completed|eligible)\b", statement, re.I)
            and re.search(r"\b(?:first|second|third|fourth|1st|2nd|3rd|4th)[ -]year\b", statement, re.I)
            and not re.search(r"\bemploy(?:ee|ment)\b|\bbenefits?\b", statement, re.I)
        )
    )


def _outside_region_context(location: str, regions: list[dict[str, Any]]) -> bool:
    """Explicit disjoint states/countries prove exclusion; missing aliases do not.

    All configured regions must have known state context. Mixed or incomplete
    location lists remain questions, including an unrecognized city in-state.
    """
    configured: set[str] = set()
    configured_countries: set[str] = set()
    for region in regions:
        states = {
            code
            for code, name in _US_STATES.items()
            if any(term.casefold() in {code.casefold(), name.casefold()} for term in region["context_terms"])
        }
        countries = {
            country
            for country, aliases in _COUNTRIES.items()
            if any(
                term.casefold() == alias.casefold() for term in region["context_terms"] for alias in aliases
            )
        }
        if states:
            countries.add("US")
        if not countries:
            return False
        configured.update(states)
        configured_countries.update(countries)
    parts = _location_parts(location)
    located: set[str] = set()
    for part in parts:
        states = {
            code
            for code, name in _US_STATES.items()
            if re.search(r",\s*" + code + r"\b", part)
            or re.search(
                r"(?:,\s*|^|\s)" + re.escape(name) + r"\s*(?:,\s*(?:USA|US|United States))?\s*$", part, re.I
            )
        }
        countries = (
            {"US"}
            if states
            else {
                country
                for country, aliases in _COUNTRIES.items()
                if any(_contains(part, alias) for alias in aliases)
            }
        )
        if not countries:
            return False
        if countries.isdisjoint(configured_countries):
            located.add("country:" + sorted(countries)[0])
            continue
        if not states or not configured or not countries <= configured_countries:
            return False
        located.update(states)
    return bool(located) and located.isdisjoint(configured)


def _short_program(candidate: dict[str, Any]) -> bool:
    durations = [
        duration_limits(rule["evidence"])
        for rule in candidate_constraints(candidate)
        if rule["kind"] == "duration"
    ]
    if any(duration and duration[0] > 14 for duration in durations):
        return False
    if any(duration and duration[1] <= 14 for duration in durations):
        return True
    start, end = candidate.get("event_start_date"), candidate.get("event_end_date")
    if start and end:
        try:
            duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
            return 0 <= duration < 14
        except (ValueError, TypeError):
            pass
    text = " ".join(
        str(candidate.get(key) or "") for key in ("title", "requirements_text", "description_excerpt")
    )
    duration_pattern = (
        r"(?:day[ -]long|week[ -]long|one[ -]day|two[ -]day|three[ -]day|single[ -]day|"
        r"(?:[1-9]|1[0-4])[ -]days?|(?:[12]|one|two)[ -]weeks?)"
    )
    program = r"(?:program(?:me)?|event|conference|summit|workshop|experience|session)"
    return bool(
        re.search(
            r"\b"
            + duration_pattern
            + r"\s+(?:(?:exploratory|intensive|residential|work|shadowing)\s+){0,3}"
            + program
            + r"\b|\b"
            + program
            + r"\s+(?:lasts?|runs? for)\s+"
            + duration_pattern
            + r"\b",
            text,
            re.I,
        )
    )


def _travel_funding(candidate: dict[str, Any]) -> tuple[str, str, str]:
    captured = [rule for rule in candidate_constraints(candidate) if rule["kind"] == "travel-funding"]
    if captured:
        states = {rule["funding"] for rule in captured}
        if len(states) == 1:
            return captured[0]["funding"], "source_constraints", captured[0]["evidence"]
        return "unknown", "source_constraints", ""
    findings: dict[str, tuple[str, str]] = {}
    for field in ("relocation_text", "compensation_text", "requirements_text", "description_excerpt"):
        for sentence in re.split(r"[.;\n]", str(candidate.get(field) or "")):
            if not re.search(r"\b(?:travel|airfare|flights?|transportation)\b", sentence, re.I):
                continue
            findings[travel_funding(sentence)] = (field, sentence.strip())
    if len(findings) == 1:
        state, (field, evidence) = next(iter(findings.items()))
        return state, field, evidence[:600]
    return "unknown", "relocation_text", ""


def screen_candidate(candidate: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    reasons: list[dict[str, str]] = []
    questions: list[str] = []
    mismatches: list[str] = []

    def reason(code: str, field: str, evidence: Any, message: str, *, mismatch: bool = False) -> None:
        reasons.append({"code": code, "field": field, "evidence": str(evidence or ""), "message": message})
        if mismatch:
            mismatches.append(code)

    title = str(candidate.get("title") or "")
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "description_excerpt", "requirements_text", "major_language")
    )
    requirements = str(candidate.get("requirements_text") or "")
    focus = _focus_match(candidate, profile["opportunity_focus"])
    if focus["match"] == "preferred":
        reason("opportunity-focus-match", focus["field"], focus["evidence"], focus["message"])
    if candidate.get("active") is False or candidate.get("application_state") == "closed":
        reason(
            "source-closed",
            "application_state",
            candidate.get("application_state"),
            "Source reports closure.",
            mismatch=True,
        )
    if candidate.get("career_stage") == "experienced" and profile["student_status"] == "undergraduate":
        if candidate.get("engagement_type") in {"internship", "co-op"} and re.search(
            r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I
        ):
            questions.append(
                "The experienced-role label conflicts with the internship title; confirm the role level."
            )
        else:
            reason(
                "experienced-role",
                "career_stage",
                title,
                "Experienced role has low relevance to an undergraduate feed.",
                mismatch=True,
            )
    degree = candidate.get("required_degree")
    constraints = candidate_constraints(candidate)
    constraint_reasons, constraint_questions, constraint_failures = compare_constraints(candidate, profile)
    reasons.extend(constraint_reasons)
    questions.extend(constraint_questions)
    mismatches.extend(constraint_failures)
    if (
        not any(rule["kind"] == "education" for rule in constraints)
        and candidate.get("source_constraints") != []
        and degree in {"masters", "doctorate"}
        and profile["degree"] in {"bachelors", "associate", "high-school"}
    ):
        reason(
            "graduate-degree-required",
            "required_degree",
            requirements or degree,
            "Source requires a graduate degree.",
            mismatch=True,
        )
    graduation_rules = [
        rule
        for rule in constraints
        if rule["kind"] == "graduation" and rule["modality"] not in {"preferred", "not-required"}
    ]
    graduation = str(candidate.get("graduation_window_language") or "")
    if (
        not graduation_rules
        and candidate.get("source_constraints") != []
        and graduation
        and required_statements(graduation)
    ):
        graduation_rules = [
            {
                "evidence": required_statements(graduation),
                "windows": graduation_windows(required_statements(graduation)),
            }
        ]
    for graduation_rule in graduation_rules:
        graduation = graduation_rule["evidence"]
        windows = graduation_rule["windows"]
        if windows and profile["graduation_month"]:
            matches = any(low <= profile["graduation_month"] <= high for low, high in windows)
            reason(
                "graduation-window-match" if matches else "graduation-window-mismatch",
                "graduation_window_language",
                graduation,
                "Expected graduation falls within the stated window."
                if matches
                else "Expected graduation falls outside the stated window.",
                mismatch=not matches,
            )
        else:
            questions.append("Clarify graduation restriction: " + graduation)
    student = str(candidate.get("class_year_language") or "")
    if profile["student_status"] == "undergraduate" and re.search(
        r"undergrad|enrolled|pursuing", student, re.I
    ):
        reason(
            "student-language",
            "class_year_language",
            student,
            "Source mentions enrolled or undergraduate students.",
        )
    standing = _academic_standing_language(student)
    if re.search(
        r"\b(?:freshman|junior|senior|sophomore|(?:first|second|third|fourth|1st|2nd|3rd|4th)[ -]year)\b",
        standing,
        re.I,
    ):
        years = _defined_program_year(standing)
        if years and profile["year_in_program"] is not None:
            matches = profile["year_in_program"] in years
            reason(
                "program-year-match" if matches else "program-year-mismatch",
                "class_year_language",
                student,
                "Known year in program matches the explicitly defined university year."
                if matches
                else "Known year in program differs from the explicitly defined university year.",
                mismatch=not matches,
            )
        else:
            questions.append("Confirm whether class standing means units or years in program: " + student)
    major = academic_major_language(str(candidate.get("major_language") or ""), required_only=True)
    major = major or academic_major_language(requirements, required_only=True)
    if major:
        if _major_matches(major, profile):
            reason(
                "major-mentioned",
                "major_language",
                major,
                "Source mentions a configured major; verify the complete rule.",
            )
        else:
            questions.append("Check whether your major satisfies the source's rule: " + major)
    experience = candidate.get("experience_requirement") or {}
    if isinstance(experience, dict) and experience.get("minimum_years") is not None:
        value = profile["max_required_experience_years"]
        evidence = str(experience.get("text") or "")
        if not required_statements(evidence):
            pass
        elif value is None or not re.search(r"required|minimum|must|at least|\+", evidence, re.I):
            questions.append("Confirm experience requirement and your qualifying experience: " + evidence)
        elif experience["minimum_years"] > value:
            reason(
                "experience-mismatch",
                "experience_requirement",
                evidence,
                "Stated minimum exceeds the configured experience limit.",
                mismatch=True,
            )
    location = str(candidate.get("location_text") or "")
    if candidate.get("remote_signal") == "remote" and profile["remote_work"] is False:
        reason(
            "remote-outside-preference",
            "remote_signal",
            "remote",
            "Remote work is outside configured preferences.",
            mismatch=True,
        )
    elif candidate.get("remote_signal") == "remote":
        questions.append("Confirm geographic and work-authorization restrictions for remote work.")
    elif profile["location_regions"] and location:
        region_matches = [
            region["label"]
            for region in profile["location_regions"]
            if any(_region_matches(part, region) for part in _location_parts(location))
        ]
        if region_matches:
            reason("location-match", "location_text", location, "Source lists a configured location.")
        elif profile["location_policy"] != "prefer-local":
            outside = _outside_region_context(location, profile["location_regions"])
            program_exception = (
                profile["location_policy"] == "local-jobs-funded-programs"
                and focus["program"]
                and candidate.get("engagement_type") not in {"co-op", "full-time", "contract"}
                and not re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I)
            )
            if program_exception:
                funding, field, evidence = _travel_funding(candidate)
                long_program = any(
                    (limits := duration_limits(rule["evidence"])) and limits[0] > 14
                    for rule in constraints
                    if rule["kind"] == "duration"
                )
                if _short_program(candidate) and funding == "covered":
                    reason(
                        "funded-program-travel",
                        field,
                        evidence,
                        "Source covers travel for a short out-of-region program.",
                    )
                elif (funding == "uncovered" or long_program) and outside:
                    reason(
                        "location-outside-regions",
                        field,
                        evidence,
                        "The out-of-region program is explicitly unfunded "
                        "or longer than the short-visit exception.",
                        mismatch=True,
                    )
                else:
                    questions.append("Confirm short program duration and covered travel: " + location)
            elif outside:
                reason(
                    "location-outside-regions",
                    "location_text",
                    location,
                    "Source explicitly lists a state or country outside configured regions.",
                    mismatch=True,
                )
            else:
                questions.append("Confirm location or relocation feasibility: " + location)
        else:
            # A free-text city can be inside a configured metro region; do not
            # convert a missing substring into a hard geographic mismatch.
            questions.append("Confirm location or relocation feasibility: " + location)
    elif not location and candidate.get("engagement_type") not in {"event", "program"}:
        questions.append("Work location has not been captured.")
    required = required_statements(requirements)
    if re.search(r"\bGPA\b|grade.point", required, re.I):
        questions.append("Confirm the applicable GPA and how the program measures it.")
    if re.search(
        r"prerequisites?|completed.{0,40}courses?|(?:must|required).{0,50}coursework|coursework.{0,40}required",
        required,
        re.I,
    ):
        questions.append("Confirm required coursework against your completed courses.")
    # Authorization clauses are interpreted individually above, excluding
    # benefits/EEO statements and reusing documented citizenship.
    if re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I) and term_time_placement(
        title, requirements
    ):
        if profile["term_time_work"] is None:
            questions.append("Confirm term-time work availability for this internship or co-op.")
        elif profile["term_time_work"] is False and not re.search(
            r"summer|part.time|flexible", title + " " + requirements, re.I
        ):
            reason(
                "term-time-outside-preference",
                "title/requirements_text",
                title,
                "Term-time work is outside documented availability.",
                mismatch=True,
            )
    interests = [
        value
        for value in profile["interest_keywords"]
        if re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I)
    ]
    if interests:
        reason(
            "interest-match", "title/requirements_text", ", ".join(interests), "Matches configured interests."
        )
    elif profile["interest_keywords"]:
        questions.append("Personal relevance is unclear from the captured title and requirements.")
    else:
        questions.append("Configure interest keywords for personal relevance screening.")
    if not requirements:
        questions.append("Requirements have not been captured; inspect the official page.")
    if candidate.get("engagement_type", "unknown") == "unknown":
        questions.append("Opportunity type is unresolved.")
    elif (
        candidate.get("engagement_type") == "internship"
        and not re.search(r"\bintern(?:ship)?\b", title, re.I)
        and (
            re.search(r"\binternal\b|\binternational\b", title, re.I)
            or candidate.get("career_stage") in {"new-grad", "entry-level"}
        )
    ):
        questions.append(
            "The internship label conflicts with the title or career stage; confirm the opportunity type."
        )
    state = "low-relevance" if mismatches else "needs-clarification" if questions else "worth-investigating"
    return {
        "origin": "deterministic",
        "state": state,
        "lane": _lane(candidate),
        "reasons": reasons,
        "questions": list(dict.fromkeys(q if len(q) <= 1000 else q[:997] + "..." for q in questions)),
        "candidate_hash": candidate_fingerprint(candidate),
        "profile_hash": _hash(profile),
        "screening_version": SCREENING_VERSION,
        "focus": focus,
    }


@lru_cache(maxsize=8192)
def _term_pattern(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", re.I)


def _contains(text: str, value: str) -> bool:
    return bool(_term_pattern(value).search(text))


def _state(root: Path) -> dict[str, Any]:
    state = _read_json(_path(root, "screening.json"), {"schema_version": "1.0", "records": {}, "custom": {}})
    if state.get("schema_version") != "1.0":
        raise WorkspaceStateError("invalid screening state schema")
    records = _object(state.get("records"), "screening records")
    _object(state.get("custom", {}), "screening custom")
    for identifier, record in records.items():
        if not OPPORTUNITY_ID.fullmatch(identifier) or not isinstance(record, dict):
            raise WorkspaceStateError("invalid screening record identity")
        if record.get("state") not in STATES or record.get("lane") not in LANES:
            raise WorkspaceStateError("invalid screening record state or lane")
        _parsed_timestamp(record.get("screened_at"), "screened_at")
        if not isinstance(record.get("questions"), list) or not all(
            isinstance(q, str) for q in record["questions"]
        ):
            raise WorkspaceStateError("invalid screening questions")
        if not isinstance(record.get("reasons"), list) or not all(
            isinstance(r, dict) for r in record["reasons"]
        ):
            raise WorkspaceStateError("invalid screening reasons")
        for field in ("candidate_hash", "profile_hash"):
            if not isinstance(record.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", record[field]):
                raise WorkspaceStateError("invalid screening fingerprint")
        if record.get("screening_version") == SCREENING_VERSION:
            focus = _object(record.get("focus"), "screening focus")
            if (
                focus.get("mode") not in (None, *FOCUS_MODES)
                or focus.get("match") not in ("preferred", "related", "other", "unspecified")
                or type(focus.get("priority")) is not int
                or focus["priority"] not in (0, 1, 2)
                or type(focus.get("program")) is not bool
                or not all(isinstance(focus.get(key), str) for key in ("field", "evidence", "message"))
            ):
                raise WorkspaceStateError("invalid screening focus")
    return state


def _current(record: dict[str, Any], candidate: dict[str, Any], profile: dict[str, Any]) -> bool:
    return (
        record.get("candidate_hash") == candidate_fingerprint(candidate)
        and record.get("profile_hash") == _hash(profile)
        and record.get("screening_version") == SCREENING_VERSION
    )


def screen_collection(root: Path, manifest_path: Path) -> dict[str, Any]:
    """Explicitly screen every candidate; persist unchanged findings without churn."""
    profile = load_profile(root)
    manifest, candidates = load_current_queue(manifest_path, filename="candidates.jsonl")
    state = _state(root)
    records = dict(state["records"])
    now = datetime.now(UTC).isoformat()
    updated = carried = 0
    for candidate in candidates:
        identifier = candidate["opportunity_id"]
        previous = records.get(identifier, {})
        if _current(previous, candidate, profile):
            carried += 1
            continue
        records[identifier] = {**previous, **screen_candidate(candidate, profile), "screened_at": now}
        updated += 1
    document = {**state, "records": records, "generation_id": manifest["generation_id"]}
    if document != state:
        _atomic_json(_path(root, "screening.json"), document)
    return {
        "schema_version": "1.0",
        "collection_count": len(candidates),
        "updated": updated,
        "carried_forward": carried,
        "generation_id": manifest["generation_id"],
    }


def apply_screening_response(root: Path, document: Any, manifest_path: Path) -> dict[str, Any]:
    """Import a bounded semantic pass without treating it as official research.

    Every interpretation quotes captured text. Explicit deterministic mismatches
    cannot be promoted through this path; they require corrected source facts or
    a separate official review. A profile/source change invalidates the pass.
    """
    response = _object(document, "screening response")
    if (
        set(response) != {"schema_version", "generation_id", "profile_hash", "decisions"}
        or response.get("schema_version") != "1.0"
    ):
        raise WorkspaceStateError("invalid screening response fields")
    profile = load_profile(root)
    manifest, candidates = load_current_queue(manifest_path, filename="candidates.jsonl")
    if response["generation_id"] != manifest["generation_id"] or response["profile_hash"] != _hash(profile):
        raise WorkspaceStateError("screening response does not match current generation and profile")
    decisions = response["decisions"]
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 100:
        raise WorkspaceStateError("screening response requires 1 to 100 decisions")
    state = _state(root)
    records = dict(state["records"])
    indexed = {candidate["opportunity_id"]: candidate for candidate in candidates}
    seen: set[str] = set()
    now = datetime.now(UTC).isoformat()
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "opportunity_id",
            "candidate_hash",
            "state",
            "reasons",
            "questions",
        }:
            raise WorkspaceStateError("invalid screening decision fields")
        identifier = decision["opportunity_id"]
        if not isinstance(identifier, str) or identifier not in indexed or identifier in seen:
            raise WorkspaceStateError("screening decision has missing or repeated identity")
        seen.add(identifier)
        candidate = indexed[identifier]
        if decision["candidate_hash"] != candidate_fingerprint(candidate):
            raise WorkspaceStateError("screening decision has stale candidate facts")
        if decision["state"] not in STATES:
            raise WorkspaceStateError("invalid screening decision state")
        baseline = screen_candidate(candidate, profile)
        if baseline["state"] == "low-relevance" and decision["state"] != "low-relevance":
            raise WorkspaceStateError("semantic screening cannot override explicit deterministic mismatches")
        questions = decision["questions"]
        if (
            not isinstance(questions, list)
            or len(questions) > 128
            or not all(isinstance(q, str) and 0 < len(q) <= 1000 for q in questions)
        ):
            raise WorkspaceStateError("invalid semantic screening questions")
        reasons = decision["reasons"]
        if not isinstance(reasons, list) or not 1 <= len(reasons) <= 20:
            raise WorkspaceStateError("semantic screening requires bounded evidence reasons")
        for reason in reasons:
            if not isinstance(reason, dict) or set(reason) != {"field", "evidence", "message", "code"}:
                raise WorkspaceStateError("invalid semantic screening reason fields")
            if not all(isinstance(value, str) and 0 < len(value) <= 1000 for value in reason.values()):
                raise WorkspaceStateError("invalid semantic screening reason text")
            quoted = str(candidate.get(reason["field"]) or "")
            if reason["field"] == "source_constraints":
                quoted = "\n".join(rule["evidence"] for rule in candidate_constraints(candidate))
            if reason["field"] not in MATERIAL_FIELDS or reason["evidence"] not in quoted:
                raise WorkspaceStateError("semantic screening evidence must quote a captured candidate field")
        # Questions about unknown personal credentials must not disappear merely
        # through interpreting collector text. Official review is a separate path.
        protected = [
            q
            for q in baseline["questions"]
            if q.startswith(
                (
                    "Confirm the applicable GPA",
                    "Confirm required coursework",
                    "Confirm the exact work-authorization",
                    "Confirm whether class standing",
                    "Confirm experience requirement",
                    "Confirm completed degrees",
                    "Confirm term-time work availability",
                    "Confirm additional security-clearance",
                    "Confirm completed study duration",
                    "Confirm current degree enrollment",
                    "Confirm professional-school enrollment",
                    "Confirm institution location",
                )
            )
        ]
        if any(q not in questions for q in protected):
            raise WorkspaceStateError("semantic screening must preserve unresolved personal requirements")
        if decision["state"] == "worth-investigating" and questions:
            raise WorkspaceStateError("worth-investigating decisions must resolve their screening questions")
        records[identifier] = {
            **records.get(identifier, {}),
            **baseline,
            "state": decision["state"],
            "questions": questions,
            "reasons": reasons,
            "screened_at": now,
            "origin": "ai-screening",
        }
    _atomic_json(
        _path(root, "screening.json"),
        {**state, "records": records, "generation_id": manifest["generation_id"]},
    )
    return {"schema_version": "1.0", "applied": len(decisions), "generation_id": manifest["generation_id"]}


def _research(
    candidate: dict[str, Any], record: dict[str, Any], profile: dict[str, Any], now: datetime
) -> tuple[str, list[str]]:
    review = record.get("review") or {}
    evidence = review.get("official_evidence") or record.get("verified_facts") or {}
    deadline = evidence.get("exact_deadline") or candidate.get("stated_deadline")
    deadline_near = False
    deadline_date = None
    if deadline:
        try:
            deadline_date = date.fromisoformat(str(deadline)[:10])
            deadline_near = 0 <= (deadline_date - now.date()).days <= 21
        except ValueError:
            pass
    if not _has_imported_decision(record):
        return "not-checked", ["unreviewed-opportunity", *(["deadline-approaching"] if deadline_near else [])]
    checked = evidence.get("checked_at")
    if not checked:
        return "not-checked", ["official-check-missing", *(["deadline-approaching"] if deadline_near else [])]
    needs: list[str] = []
    snapshot = record.get("collector_snapshot") or {}
    if candidate_fingerprint(candidate) != candidate_fingerprint(snapshot):
        needs.append("source-facts-changed")
    if now - _parsed_timestamp(checked, "official checked_at") >= timedelta(days=profile["stale_after_days"]):
        needs.append("stale-official-check")
    # A check performed during the deadline window already addresses it. Do
    # not schedule the same unchanged page again every session until it closes.
    if (
        deadline_near
        and deadline_date
        and _parsed_timestamp(checked, "official checked_at").date() < (deadline_date - timedelta(days=21))
    ):
        needs.append("deadline-approaching")
    if (record.get("eligibility") or {}).get("conclusion") == "unknown" or evidence.get(
        "availability"
    ) == "unknown":
        needs.append("unresolved-official-findings")
    return ("recheck-needed" if needs else "checked-current"), needs


_PROFILE_QUESTIONS = {
    "study_progress": (
        "Confirm completed study duration",
        "Reuse documented completed years, terms or credits; "
        "current enrollment alone does not establish completion.",
    ),
    "completed_degrees": (
        "Confirm completed degrees",
        "Reuse documented degree completions; current enrollment alone does not establish them.",
    ),
    "term_time_work": (
        "Confirm term-time work availability",
        "Confirm term-time availability once; preserve opportunity-specific date questions.",
    ),
    "security_clearance": (
        "Confirm additional security-clearance",
        "Keep clearance conditions separate from documented citizenship.",
    ),
    "gpa": ("Confirm the applicable GPA", "Provide documented GPA and its grading scale if known."),
    "coursework": ("Confirm required coursework", "Provide completed coursework if known."),
    "work_authorization": (
        "Confirm the exact work-authorization",
        "Clarify documented work authorization or citizenship, if you wish to provide it.",
    ),
    "class_standing": (
        "Confirm whether class standing",
        "Keep academic standing separate from years in the degree program.",
    ),
    "experience": (
        "Confirm experience requirement",
        "Clarify qualifying experience rather than inferring zero years.",
    ),
}


def _review_role_conflict(candidate: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Conservative review deferral; never rewrite eligibility or public labels."""
    title = str(candidate.get("title") or "")
    internship = bool(re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b", title, re.I))
    staff_program = profile["opportunity_focus"] in {
        "early-opportunities",
        "standard-internships",
    } and staff_role(title)
    experienced = re.search(
        r"\b(?:senior|sr\.?|principal|director|head|VP)\b.*\b(?:engineer|analyst|recruiter|"
        r"controller|consultant|manager|specialist|executive|officer|scientist|developer|coordinator)\b|"
        r"experienced professionals",
        title,
        re.I,
    ) and not re.search(r"\bsenior (?:year|design|students?)\b", title, re.I)
    if not internship and (staff_program or experienced):
        return "The title targets an experienced or program-staff role; defer routine student review."
    undergraduate_exception = any(rule.get("exception") for rule in candidate_constraints(candidate))
    if not undergraduate_exception and profile["degree"] in {"bachelors", "associate", "high-school"}:
        undergraduate_option = re.search(r"\b(?:BS|BA|BSc|bachelor\w*|undergrad\w*)\b", title, re.I)
        if (
            re.search(r"\b(?:PhD|doctoral|MBA)\b|\([^)]*\b(?:MS|MSc)\b[^)]*\)", title, re.I)
            and not undergraduate_option
        ):
            return "The title targets graduate-degree candidates; retain it outside routine student research."
        academic = required_statements(str(candidate.get("class_year_language") or ""))
        if re.search(
            r"\b(?:law school|doctoral|PhD|MBA|master['’]?s?|graduate)\b.{0,50}\bstudents?\b|"
            r"\b(?:enrolled|pursuing)\b.{0,50}\b(?:law school|doctoral|PhD|MBA|master['’]?s?)\b",
            academic,
            re.I,
        ) and not re.search(r"\b(?:BS|BA|BSc|bachelor\w*|undergrad\w*)\b", academic, re.I):
            return "Enrollment language targets graduate/professional study; defer the unresolved degree fit."
    return None


def _review_selection(
    finding: dict[str, Any],
    research: str,
    priorities: list[str],
    actionable: bool,
    role_conflict: str | None = None,
) -> dict[str, Any]:
    """Choose useful next work, independently of eligibility or official checks."""
    questions = finding["questions"]
    profile_questions = [
        key for key, (prefix, _) in _PROFILE_QUESTIONS.items() if any(q.startswith(prefix) for q in questions)
    ]
    source_questions = [
        q
        for q in questions
        if not any(
            q.startswith(prefix) for key, (prefix, _) in _PROFILE_QUESTIONS.items() if key != "class_standing"
        )
    ]
    focus = finding["focus"]
    reasons = {reason["code"] for reason in finding["reasons"]}
    preferred_early = focus["mode"] == "early-opportunities" and focus["match"] == "preferred"
    broad_program = preferred_early and focus["program"]
    relevant = focus["match"] in {"preferred", "related", "unspecified"} and (
        bool(reasons & {"interest-match", "major-mentioned", "student-language", "graduation-window-match"})
        or finding["origin"] == "ai-screening"
    )
    meaningful_change = bool(
        set(priorities) & {"source-facts-changed", "deadline-approaching", "stale-official-check"}
    )
    selected, action, message = (
        False,
        "low-priority",
        "Captured facts do not yet show a strong match with a bounded research question.",
    )
    if not actionable:
        action, message = (
            "respect-user-decision",
            "Existing completed, dismissed or waiting decision carries forward.",
        )
    elif finding["state"] == "low-relevance":
        action, message = (
            "recoverable-exclusion",
            "An explicit mismatch is retained for recovery, outside the default review batch.",
        )
    elif role_conflict:
        action, message = "role-outside-focus", role_conflict
    elif research == "checked-current":
        action, message = (
            "reuse-findings",
            "Current official findings carry forward; no repeat check is needed.",
        )
    elif research == "recheck-needed" and not meaningful_change:
        action, message = (
            "await-new-evidence",
            "An unchanged official check is still unresolved; carry its questions forward."
            " Repeat only when new evidence warrants it.",
        )
    elif (
        meaningful_change
        and research == "recheck-needed"
        and (finding["state"] == "worth-investigating" or preferred_early or relevant)
    ):
        selected, action, message = (
            True,
            "official-research",
            "Revisit a useful lead because facts changed, a deadline is approaching, or its check is stale.",
        )
    elif focus["match"] == "other":
        action, message = (
            "outside-stage-focus",
            "Outside the selected opportunity stage; retain in Explore rather than routine review.",
        )
    elif finding["state"] == "worth-investigating":
        selected, action, message = (
            True,
            "official-research",
            "Plausible captured fit; verify availability and eligibility on the official page.",
        )
    elif broad_program:
        selected, action, message = (
            True,
            "official-research",
            "Explore a preferred early program broadly, including unresolved subject fit or travel funding.",
        )
    elif not source_questions and profile_questions:
        action, message = (
            "clarify-profile",
            "Group the shared personal questions before spending another page review on the same unknowns.",
        )
    elif source_questions and (preferred_early or relevant and len(source_questions) <= 2):
        selected, action, message = (
            True,
            "clarify-source",
            "A promising lead has a source question; interpret captured text, then check the official page."
            " Preferred early-year roles retain broader consideration.",
        )
    if selected and action == "clarify-source" and finding["origin"] == "ai-screening":
        action, message = (
            "official-research",
            "Captured-text triage is saved; research remaining questions without repeating that pass.",
        )
    return {
        "selected": selected,
        "action": action,
        "message": message,
        "source_questions": source_questions,
        "profile_questions": profile_questions,
    }


def list_personal_feed(
    root: Path,
    manifest_path: Path,
    *,
    state_filter: str | None = None,
    lane: str | None = None,
    search: str | None = None,
    uncapped: bool = False,
    route: str | None = None,
    engagement_type: str | None = None,
    review_status: str | None = None,
    review_only: bool = False,
    review_action: str | None = None,
    audit_sample: bool = False,
    offset: int = 0,
    limit: int = 25,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only Feed across the whole collection; cached or explicitly labeled preview."""
    if state_filter not in (None, "all", *STATES) or lane not in (None, *LANES):
        raise WorkspaceStateError("invalid screening filter")
    if review_action not in (None, *REVIEW_ACTIONS):
        raise WorkspaceStateError("invalid review action filter")
    profile = load_profile(root)
    manifest, candidates = load_current_queue(manifest_path, filename="candidates.jsonl")
    cached = _state(root)["records"]
    board = _board_records(root)
    now = now or datetime.now(UTC)
    items = []
    counts: Counter[str] = Counter()
    lanes: Counter[str] = Counter()
    selection_counts: Counter[str] = Counter()
    profile_question_counts: Counter[str] = Counter()
    selected = selected_clarification = 0
    screened = plausible = checked = awaiting = reviewed = 0
    for candidate in candidates:
        identifier = candidate["opportunity_id"]
        saved = cached.get(identifier, {})
        current = _current(saved, candidate, profile)
        finding = saved if current else screen_candidate(candidate, profile)
        screened += current
        plausible += current and finding["state"] == "worth-investigating"
        record = board.get(identifier, {})
        research, priorities = _research(candidate, record, profile, now)
        imported = _has_imported_decision(record)
        if not imported:
            for field, code in (("first_seen", "new-opportunity"), ("last_changed", "source-facts-changed")):
                timestamp = candidate.get(field)
                if not timestamp or field == "last_changed" and timestamp == candidate.get("first_seen"):
                    continue
                try:
                    age = now - _parsed_timestamp(timestamp, field)
                except WorkspaceStateError:
                    continue
                if timedelta(0) <= age <= timedelta(days=7):
                    priorities.append(code)
            if saved and saved.get("candidate_hash") != candidate_fingerprint(candidate):
                priorities.append("source-facts-changed")
        user_state = record.get("user_state") or {}
        actionable = board_lane(record, user_state, _pipeline_state(user_state)) == "active"
        role_conflict = _review_role_conflict(candidate, profile)
        selection = _review_selection(finding, research, priorities, actionable, role_conflict)
        selection_counts[selection["action"]] += 1
        selected += selection["selected"]
        selected_clarification += selection["selected"] and finding["state"] == "needs-clarification"
        if selection["selected"] or selection["action"] == "clarify-profile":
            profile_question_counts.update(selection["profile_questions"])
        reviewed += imported
        checked += research != "not-checked"
        awaiting += actionable and finding["state"] != "low-relevance" and research != "checked-current"
        counts[finding["state"]] += 1
        lanes[finding["lane"]] += 1
        if review_only and not selection["selected"]:
            continue
        if review_action and selection["action"] != review_action:
            continue
        if not state_filter and (finding["state"] == "low-relevance" or not actionable):
            continue
        if (
            state_filter not in (None, "all")
            and finding["state"] != state_filter
            or lane
            and finding["lane"] != lane
        ):
            continue
        if (
            route
            and candidate.get("routing_state") != route
            or engagement_type
            and candidate.get("engagement_type") != engagement_type
        ):
            continue
        if review_status and review_status != ("reviewed" if imported else "unreviewed"):
            continue
        if (
            search
            and search.casefold()
            not in " ".join(
                str(candidate.get(key) or "")
                for key in ("title", "organization", "location_text", "requirements_text")
            ).casefold()
        ):
            continue
        if not current:
            priorities.append("screening-refresh-needed" if saved else "screening-not-saved")
        items.append(
            {
                **candidate,
                "screening": finding,
                "screening_saved": current,
                "research_status": research,
                "review_status": "reviewed" if imported else "unreviewed",
                "investigation_reasons": priorities,
                "review_selection": selection,
                "ai_evidence_packet": evidence_packet(candidate, finding, profile),
            }
        )
    items.sort(
        key=lambda item: (
            item["screening"]["focus"]["priority"],
            "source-facts-changed" not in item["investigation_reasons"],
            "deadline-approaching" not in item["investigation_reasons"],
            "new-opportunity" not in item["investigation_reasons"],
            item["research_status"] == "checked-current",
            len(item["review_selection"]["source_questions"])
            if review_only
            else item["screening"]["state"] != "worth-investigating",
            -len(item["screening"]["reasons"]),
            item["opportunity_id"],
        )
    )
    matching = len(items)
    employer_counts: Counter[str] = Counter()
    buckets: dict[tuple[int, str], deque] = {
        (priority, name): deque() for priority in range(3) for name in LANES
    }
    for item in items:
        buckets[(item["screening"]["focus"]["priority"], item["screening"]["lane"])].append(item)
    balanced = []
    cap_exempt = 0
    for priority in range(3):
        while any(buckets[(priority, name)] for name in LANES):
            for name in LANES:
                if not buckets[(priority, name)]:
                    continue
                item = buckets[(priority, name)].popleft()
                employer = str(item.get("organization") or "").strip().casefold() or item["opportunity_id"]
                focus = item["screening"]["focus"]
                exempt = (
                    profile["opportunity_focus"] == "early-opportunities"
                    and focus["match"] == "preferred"
                    and focus["program"]
                )
                if uncapped or exempt or employer_counts[employer] < profile["employer_cap"]:
                    balanced.append(item)
                    cap_exempt += exempt
                    if not exempt:
                        employer_counts[employer] += 1
    if audit_sample:
        groups: dict[str, deque[dict[str, Any]]] = {
            name: deque() for name in ("selected", "deferred", "excluded")
        }
        for item in sorted(
            balanced, key=lambda item: _hash([manifest["generation_id"], item["opportunity_id"]])
        ):
            group = (
                "excluded"
                if item["screening"]["state"] == "low-relevance"
                else "selected"
                if item["review_selection"]["selected"]
                else "deferred"
            )
            groups[group].append({**item, "audit_group": group})
        sampled = []
        while any(groups.values()):
            for bucket in groups.values():
                if bucket:
                    sampled.append(bucket.popleft())
        balanced = sampled
    return {
        **_page(balanced, offset, limit),
        "collection_count": len(candidates),
        "queue_count": len(candidates),
        "reviewed_count": reviewed,
        "unreviewed_count": len(candidates) - reviewed,
        "matching_count": matching,
        "generated_at": manifest.get("generated_at"),
        "hidden_by_cap": matching - len(balanced),
        "employer_cap": profile["employer_cap"],
        "opportunity_focus": profile["opportunity_focus"],
        "cap_exempt_programs": cap_exempt,
        "profile_hash": _hash(profile),
        "personalized": True,
        "state_counts": dict(counts),
        "lane_counts": dict(lanes),
        "generation_id": manifest["generation_id"],
        "review_batch": review_only,
        "sampling_method": "stratified-selected-deferred-excluded; not a population error-rate estimate"
        if audit_sample
        else None,
        "review_action_counts": dict(selection_counts),
        "profile_questions": [
            {"field": key, "affected_leads": count, "message": _PROFILE_QUESTIONS[key][1]}
            for key, count in sorted(profile_question_counts.items())
        ],
        "coverage": {
            "screened": screened,
            "plausible": plausible,
            "officially_checked": checked,
            "awaiting_investigation": awaiting,
            "unsaved_screening": len(candidates) - screened,
            "selected_for_review": selected,
            "selected_needing_clarification": selected_clarification,
        },
    }
