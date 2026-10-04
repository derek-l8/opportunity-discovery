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
from pathlib import Path
from typing import Any

from .workspace_board import _lane as board_lane
from .workspace_board import _pipeline_state
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

SCREENING_VERSION = "6"
FOCUS_MODES = ("early-opportunities", "standard-internships", "new-grad")
LOCATION_POLICIES = ("prefer-local", "local-only", "local-jobs-funded-programs")
STATES = ("worth-investigating", "needs-clarification", "low-relevance")
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
        "majors",
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
        "majors": [],
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
    for field in ("majors", "interest_keywords", "source_refs"):
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
    for region in regions:
        if not isinstance(region, dict) or set(region) != {"label", "match_terms", "context_terms"}:
            raise WorkspaceStateError("each region requires label, match_terms and context_terms")
        if not isinstance(region["label"], str) or not 1 <= len(region["label"].strip()) <= 200:
            raise WorkspaceStateError("invalid location region label")
        for field in ("match_terms", "context_terms"):
            values = region[field]
            if (
                not isinstance(values, list)
                or len(values) > 100
                or not all(isinstance(term, str) and 0 < len(term.strip()) <= 200 for term in values)
                or field == "match_terms"
                and not values
            ):
                raise WorkspaceStateError(f"invalid region {field}")
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
    program = engagement in {"event", "fellowship"} or bool(
        _PROGRAM_FORM.search(title) or candidate.get("program_family_id") or candidate.get("overview_url")
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
    findings: dict[str, tuple[str, str]] = {}
    for field in ("relocation_text", "compensation_text", "requirements_text", "description_excerpt"):
        for sentence in re.split(r"[.;\n]", str(candidate.get(field) or "")):
            if not re.search(r"\b(?:travel|airfare|flights?|transportation)\b", sentence, re.I):
                continue
            if re.search(
                r"\b(?:not|no|unfunded|own expense|self.funded|responsible for|may|might|could|eligible)\b",
                sentence,
                re.I,
            ):
                if re.search(
                    r"\b(?:not covered|not reimbursed|no (?:travel|funding)|own expense|"
                    r"self.funded|responsible for)\b",
                    sentence,
                    re.I,
                ):
                    findings["uncovered"] = (field, sentence.strip())
                continue
            if re.search(
                r"\b(?:cover(?:ed|s)?|reimburse(?:d|s|ment)?|paid|provided|arranged)\b", sentence, re.I
            ):
                findings["covered"] = (field, sentence.strip())
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
    if degree in {"masters", "doctorate"} and profile["degree"] in {"bachelors", "associate", "high-school"}:
        reason(
            "graduate-degree-required",
            "required_degree",
            requirements or degree,
            "Source requires a graduate degree.",
            mismatch=True,
        )
    graduation = str(candidate.get("graduation_window_language") or "")
    if graduation:
        window = _graduation_range(graduation)
        if window and profile["graduation_month"]:
            matches = window[0] <= profile["graduation_month"] <= window[1]
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
    if re.search(r"\b(?:junior|senior|sophomore|first.year|second.year)\b", student, re.I):
        questions.append("Confirm whether class standing means units or years in program: " + student)
    major = str(candidate.get("major_language") or "")
    if major:
        if any(re.search(r"\b" + re.escape(value) + r"\b", major, re.I) for value in profile["majors"]):
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
        if (
            value is None
            or not re.search(r"required|minimum|must|at least|\+", evidence, re.I)
            or re.search(r"preferred|a plus", evidence, re.I)
        ):
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
            if any(
                any(_contains(part, value) for value in region["match_terms"])
                and (
                    not region["context_terms"]
                    or any(_contains(part, value) for value in region["context_terms"])
                )
                for part in _location_parts(location)
            )
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
                if _short_program(candidate) and funding == "covered":
                    reason(
                        "funded-program-travel",
                        field,
                        evidence,
                        "Source covers travel for a short out-of-region program.",
                    )
                elif funding == "uncovered" and outside:
                    reason(
                        "location-outside-regions",
                        field,
                        evidence,
                        "Out-of-region program explicitly lacks covered travel.",
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
    if re.search(r"\bGPA\b|grade.point", requirements, re.I):
        questions.append("Confirm the applicable GPA and how the program measures it.")
    if re.search(r"coursework|completed.*courses?|prerequisites?", requirements, re.I):
        questions.append("Confirm required coursework against your completed courses.")
    if candidate.get("work_auth_language"):
        questions.append(
            "Confirm the exact work-authorization or citizenship requirement: "
            + str(candidate["work_auth_language"])
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
        "questions": list(dict.fromkeys(questions)),
        "candidate_hash": candidate_fingerprint(candidate),
        "profile_hash": _hash(profile),
        "screening_version": SCREENING_VERSION,
        "focus": focus,
    }


def _contains(text: str, value: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", text, re.I))


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
            or len(questions) > 30
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
            if reason["field"] not in MATERIAL_FIELDS or reason["evidence"] not in str(
                candidate.get(reason["field"]) or ""
            ):
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
    if not _has_imported_decision(record):
        return "not-checked", ["unreviewed-opportunity"]
    review = record["review"]
    evidence = review.get("official_evidence") or record.get("verified_facts") or {}
    checked = evidence.get("checked_at")
    if not checked:
        return "not-checked", ["official-check-missing"]
    needs: list[str] = []
    snapshot = record.get("collector_snapshot") or {}
    if candidate_fingerprint(candidate) != candidate_fingerprint(snapshot):
        needs.append("source-facts-changed")
    if now - _parsed_timestamp(checked, "official checked_at") >= timedelta(days=profile["stale_after_days"]):
        needs.append("stale-official-check")
    deadline = evidence.get("exact_deadline") or candidate.get("stated_deadline")
    if deadline:
        try:
            days = (date.fromisoformat(str(deadline)[:10]) - now.date()).days
            if 0 <= days <= 21:
                needs.append("deadline-approaching")
        except ValueError:
            pass
    if (record.get("eligibility") or {}).get("conclusion") == "unknown" or evidence.get(
        "availability"
    ) == "unknown":
        needs.append("unresolved-official-findings")
    return ("recheck-needed" if needs else "checked-current"), needs


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
    offset: int = 0,
    limit: int = 25,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only Feed across the whole collection; cached or explicitly labeled preview."""
    if state_filter not in (None, "all", *STATES) or lane not in (None, *LANES):
        raise WorkspaceStateError("invalid screening filter")
    profile = load_profile(root)
    manifest, candidates = load_current_queue(manifest_path, filename="candidates.jsonl")
    cached = _state(root)["records"]
    board = _board_records(root)
    now = now or datetime.now(UTC)
    items = []
    counts: Counter[str] = Counter()
    lanes: Counter[str] = Counter()
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
        reviewed += imported
        checked += research != "not-checked"
        awaiting += actionable and finding["state"] != "low-relevance" and research != "checked-current"
        counts[finding["state"]] += 1
        lanes[finding["lane"]] += 1
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
            }
        )
    items.sort(
        key=lambda item: (
            item["screening"]["focus"]["priority"],
            "source-facts-changed" not in item["investigation_reasons"],
            "deadline-approaching" not in item["investigation_reasons"],
            "new-opportunity" not in item["investigation_reasons"],
            item["research_status"] == "checked-current",
            item["screening"]["state"] != "worth-investigating",
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
        "coverage": {
            "screened": screened,
            "plausible": plausible,
            "officially_checked": checked,
            "awaiting_investigation": awaiting,
            "unsaved_screening": len(candidates) - screened,
        },
    }
