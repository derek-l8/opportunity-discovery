"""Extract bounded source language from full ATS content before display truncation.

Full descriptions are transient. Statements remain source language, never an
applicant eligibility conclusion. Dates without an explicit year stay unknown.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import TypedDict, cast

from bs4 import BeautifulSoup

_FACT_PATTERNS = {
    "class_year_language": (
        r"\b(?:students?|enrolled|pursuing|undergrad\w*|freshm[ae]n|sophomore|"
        r"junior|senior|first.year|second.year)\b"
    ),
    "graduation_window_language": r"\b(?:graduat\w*|class of)\b",
    "major_language": (
        r"\b(?:major\w*|degree in|electrical engineering|computer science|"
        r"mechanical engineering)\b"
    ),
    "work_auth_language": r"work authoriz|sponsorship|authorized to work|citizen|permanent resident|visa",
    "compensation_text": r"\$\s*\d|\b(?:USD|salary|stipend|compensation|paid internship|unpaid)\b",
    "relocation_text": r"\brelocat\w*\b|housing (?:provided|support|allowance)",
    "experience_requirement_text": (
        r"\b\d{1,2}(?:\s*[-–]\s*\d{1,2}|\+)?\s+years?\s+(?:of\s+)?"
        r"(?:(?:professional|relevant|related|industry|work)\s+)?experience\b"
    ),
}
_REQUIREMENT = re.compile(
    r"qualifications?|requirements?|must|minimum|eligible|eligibility|enrolled|pursuing|"
    r"graduat|degree|major|experience|GPA|coursework|citizen|sponsorship|authorized to work",
    re.I,
)
_OPTIONAL = re.compile(r"\b(?:preferred|desired|desirable|bonus|nice.to.have|a plus)\b", re.I)


class DescriptionFacts(TypedDict):
    class_year_language: str | None
    graduation_window_language: str | None
    major_language: str | None
    work_auth_language: str | None
    compensation_text: str | None
    relocation_text: str | None
    experience_requirement_text: str | None
    requirements_text: str | None
    deadline: str | None
    required_degree: str | None
    preferred_degree: str | None


def decoded_text(text: str | None) -> str:
    """Decode nested entity escapes, remove executable markup, preserve blocks."""
    value = text or ""
    for _ in range(3):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    soup = BeautifulSoup(value, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    for element in soup.find_all(["p", "li", "div", "br", "h1", "h2", "h3", "h4"]):
        element.insert_before("\n")
        element.insert_after("\n")
    return "\n".join(
        re.sub(r"\s+", " ", line).strip() for line in soup.get_text().splitlines() if line.strip()
    )


def description_location(content: str | None) -> str | None:
    """Use explicitly labeled locations only; never geocode or guess a city."""
    locations = []
    for line in decoded_text(content).splitlines():
        match = re.fullmatch(r"(?:job |work |office )?location\s*:\s*(.{1,200})", line, re.I)
        if match:
            locations.append(match[1].strip())
    return "; ".join(dict.fromkeys(locations))[:600] or None


def _statements(text: str) -> list[str]:
    statements: list[str] = []
    heading = ""
    for part in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])", text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(
            r"(?:(?:minimum|basic|required|preferred|desired|additional)\s+)?(?:qualifications|requirements|skills):?",
            part,
            re.I,
        ):
            heading = part
            continue
        if re.fullmatch(
            r"(?:responsibilities|what you(?:'|’)ll do|about (?:us|the (?:company|role))|"
            r"benefits|compensation|salary|equal opportunity(?: employer)?):?",
            part,
            re.I,
        ):
            heading = ""
            continue
        statements.append(heading + "\n" + part if heading else part)
    # Explicit requirement sections precede company introductions even when the
    # introduction happens to mention a degree or years of experience.
    return sorted(statements, key=lambda statement: "\n" not in statement)


def _bounded_statements(statements: list[str], limit: int = 600) -> str | None:
    selected: list[str] = []
    length = 0
    for statement in dict.fromkeys(statements):
        remaining = limit - length - (1 if selected else 0)
        if remaining <= 0:
            break
        selected.append(statement[:remaining])
        length += len(selected[-1]) + (1 if len(selected) > 1 else 0)
    return "\n".join(selected) or None


def extract_description(content: str | None, *, qualification_sections: str = "") -> DescriptionFacts:
    """Inspect all available text, prefer separate qualification sections."""
    full = decoded_text(content)
    qualifications = decoded_text(qualification_sections)
    statements = _statements(qualifications) + _statements(full)
    section_statements = [statement for statement in statements if "\n" in statement]
    requirement_statements = (
        section_statements
        + [
            statement
            for statement in statements
            if "\n" not in statement
            and re.search(r"\b(?:must|required|minimum|eligible|eligibility)\b", statement, re.I)
        ]
        if section_statements
        else [statement for statement in statements if _REQUIREMENT.search(statement)]
    )
    result: dict[str, str | None] = {}
    for field, pattern in _FACT_PATTERNS.items():
        inputs = requirement_statements if field == "experience_requirement_text" else statements
        matches = [statement for statement in inputs if re.search(pattern, statement, re.I)]
        if field == "experience_requirement_text":
            # Optional experience is not a minimum requirement.
            matches = [statement for statement in matches if not _OPTIONAL.search(statement)]
        result[field] = _bounded_statements(matches)
    result["requirements_text"] = _bounded_statements(requirement_statements, 2400)
    # Degree statements at the end of long qualification lists must survive the
    # bounded public requirements excerpt. No full description is persisted.
    from .models import RawOpportunity
    from .routing import normalize_routing_fields

    routing = normalize_routing_fields(
        RawOpportunity(
            title="",
            canonical_url="",
            requirements_text="\n".join(requirement_statements),
        )
    )
    for field in ("required_degree", "preferred_degree"):
        result[field] = routing[field] if routing[field] != "unknown" else None
    result["deadline"] = None
    deadlines: set[str] = set()
    for statement in statements:
        if not re.search(
            r"(?:application|apply|applications)[^.\n]{0,60}(?:deadline|due|by)|application deadline",
            statement,
            re.I,
        ):
            continue
        for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}\b", statement):
            value = match.group(0)
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
                try:
                    parsed = datetime.strptime(value, fmt).date()
                    if date(1900, 1, 1) <= parsed <= date(2200, 1, 1):
                        deadlines.add(parsed.isoformat())
                    break
                except ValueError:
                    continue
    if len(deadlines) == 1:
        result["deadline"] = deadlines.pop()
    return cast(DescriptionFacts, result)
