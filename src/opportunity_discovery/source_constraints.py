"""Conservative, source-only constraints; no applicant data or model calls."""

from __future__ import annotations

import re
from typing import Any

MONTHS = [
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
_DEGREES = {
    "bachelors": r"\bbachelor\w*\b|\bB\.?[AS]\.?c?\b|\bundergrad\w*\b",
    "masters": r"\bmaster(?:['’]s|s)\b|\bmaster\s+(?:of|degree|in)\b|"
    r"\bM\.?Sc?\.?\b(?!\s+(?:Dynamics|Office|Teams|Excel|Word|Azure|Project))|\bMBA\b",
    "doctorate": r"\bPh\.?D\.?\b|\bdoctoral\b|\bdoctorate\b",
}
_TOKEN = r"(?:(" + "|".join(MONTHS) + r"|spring|summer|fall|autumn|winter)\s+(?:of\s+)?)?(20\d{2})"


def source_statements(text: str) -> list[str]:
    """Split prose while retaining degree/country abbreviations and quoted wording."""
    statements: list[str] = []
    for line in text.splitlines():
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line.strip())
        pending = ""
        for part in parts:
            pending += part
            if re.search(r"\b(?:U\.S|B\.S|B\.A|M\.S|Ph\.D|Dr|Mr|Ms|e\.g|i\.e)\.$", pending, re.I):
                pending += " "
                continue
            if pending.strip():
                statements.extend(
                    re.split(
                        r"\s+(?:but|while|however)\s+(?=(?:a |an )?(?:bachelor|master|PhD|doctoral)\b)|"
                        r";\s*(?=(?:must|bachelor|master|currently|no|travel|hold|possess)\b)",
                        pending.strip(),
                        flags=re.I,
                    )
                )
            pending = ""
        if pending.strip():
            statements.append(pending.strip())
    return statements


def clause_modality(clause: str, inherited: str = "unspecified") -> str:
    """A negated requirement must never become a mandatory credential."""
    negation = re.search(
        r"\bnot\s+(?:(?:strictly|necessarily|a|an)\s+)?(?:required|necessary|mandatory|needed)|"
        r"\bno\b.{0,60}\b(?:required|necessary|needed)|\bwithout\b.{0,45}\b(?:degree|GPA)",
        clause,
        re.I,
    )
    if negation:
        remainder = clause[: negation.start()] + clause[negation.end() :]
        return (
            "unspecified" if re.search(r"\b(?:must|required|minimum)\b", remainder, re.I) else "not-required"
        )
    optional = re.search(r"\b(?:preferred|nice.to.have|desirable|desired|bonus|a plus)\b", clause, re.I)
    mandatory = re.search(r"\b(?:must|required|minimum|at least|eligible|eligibility)\b", clause, re.I)
    if optional and mandatory:
        return "unspecified"  # Mixed clauses need interpretation, not a hard restriction.
    if optional:
        return "preferred"
    return "required" if mandatory else inherited


def travel_funding(clause: str) -> str:
    """Distinguish employer coverage, applicant payments and partial/conditional funding."""
    if re.search(
        r"\bnot (?:covered|reimbursed|paid|provided)|\bno (?:travel|funding)|"
        r"own expense|self.funded|responsible for|"
        r"(?:paid|covered|funded|arranged) by (?:the )?(?:participants?|students?|attendees?|applicants?)|"
        r"(?:participants?|students?|attendees?|applicants?).{0,20}(?:must|will|shall) (?:pay|cover|fund)",
        clause,
        re.I,
    ):
        return "uncovered"
    if re.search(
        r"\b(?:may|might|could|eligible|conditional|partial(?:ly)?|limited|up to|toward|towards)\b|"
        r"subject to|depending on|not guaranteed|(?:pay|cover).{0,20}own",
        clause,
        re.I,
    ):
        return "unknown"
    return (
        "covered"
        if re.search(r"\bcover(?:ed|s)?\b|reimburse|arranged|paid|provided", clause, re.I)
        else "unknown"
    )


def degree_operator(clause: str, degrees: list[str], state: str) -> str:
    if len(degrees) < 2:
        return "any"
    positions = sorted(
        (match.start(), match.end())
        for degree in degrees
        if (match := re.search(_DEGREES[degree], clause, re.I))
    )
    connectors = [clause[left[1] : right[0]] for left, right in zip(positions, positions[1:], strict=False)]
    alternatives = any(re.search(r"\bor\b|/|,", connector, re.I) for connector in connectors)
    conjunction = any(re.search(r"\band\b", connector, re.I) for connector in connectors)
    if alternatives and not conjunction:
        return "any"
    if conjunction and not alternatives and state == "completed":
        return "all"
    return "unknown"


def graduation_windows(language: str) -> list[list[str]] | None:
    """Ranges and explicit alternatives; uncertain bounds remain unresolved.

    Seasonal bounds deliberately include adjacent commencement months. Winter
    spans calendar years and remains unresolved without explicit months.
    """
    if re.search(r"before|after|not|preferred|desirable|example|[<>]", language, re.I):
        return None
    if not re.search(r"graduat|class of", language, re.I):
        return None
    tokens = list(re.finditer(_TOKEN, language, re.I))
    if not 1 <= len(tokens) <= 2 or any(t[1] and t[1].lower() == "winter" for t in tokens):
        return None

    def bounds(token: re.Match[str]) -> list[str]:
        name, year = (token[1] or "").lower(), token[2]
        if name in MONTHS:
            month = MONTHS.index(name) + 1
            return [f"{year}-{month:02}"] * 2
        low, high = {"spring": (1, 6), "summer": (5, 9), "fall": (8, 12), "autumn": (8, 12)}.get(
            name, (1, 12)
        )
        return [f"{year}-{low:02}", f"{year}-{high:02}"]

    ranges = [bounds(token) for token in tokens]
    if len(tokens) == 2:
        connector = language[tokens[0].end() : tokens[1].start()].strip()
        if re.fullmatch(r"(?:and|to|through|[-–])", connector, re.I):
            return [[ranges[0][0], ranges[1][1]]] if ranges[0][0] <= ranges[1][1] else None
        if not re.fullmatch(r"or(?:\s+in)?", connector, re.I):
            return None
    return ranges


def authorization_requirement(sentence: str) -> bool:
    """Benefits, executive sponsorship and EEO boilerplate are not restrictions."""
    if re.search(
        r"equal (?:employment )?opportunity|without regard|regardless of|executive sponsorship",
        sentence,
        re.I,
    ):
        return False
    if re.search(
        r"we (?:do )?sponsor visas|visa sponsorship (?:is )?(?:available|provided)|immigration lawyer",
        sentence,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"(?:must|required|only|eligible|authorized|authorised|authorization|"
            r"regulations|cannot|do not|unable).{0,100}"
            r"(?:citizen|resident|U\.?S\.? person|visa|sponsor)|"
            r"(?:citizen|resident|U\.?S\.? person|work authori\w*).{0,100}(?:required|only|must)|"
            r"(?:right|authorization|authorisation|authorized|authorised) to work",
            sentence,
            re.I,
        )
    )


def staff_role(title: str) -> bool:
    if re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b|\bstudent\b", title, re.I):
        return False
    return bool(
        re.search(
            r"\b(?:program|academy)\s+(?:(?:senior|staff|junior|finance|technical)\s+)*"
            r"(?:manager|scheduler|controller|recruiter|coordinator|analyst|director|officer)\b|"
            r"\b(?:recruiter|scheduler|controller)\b.*\b(?:program|academy)\b",
            title,
            re.I,
        )
    )


def duration_limits(text: str) -> tuple[int, int] | None:
    numbers = {"one": 1, "two": 2, "three": 3, "six": 6, "twelve": 12}
    match = re.search(
        r"\b(\d+|one|two|three|six|twelve)[ -](days?|weeks?|months?)\b"
        r"\s+(?:(?:accelerated|intensive|work|shadowing|exploratory|residential)\s+){0,3}"
        r"(?:program(?:me)?|fellowship|rotation|internship|co.op|workshop|experience|session)\b",
        text,
        re.I,
    )
    if not match:
        return None
    number = int(match[1]) if match[1].isdigit() else numbers[match[1].lower()]
    low, high = (
        (28, 31)
        if match[2].lower().startswith("month")
        else (7, 7)
        if match[2].lower().startswith("week")
        else (1, 1)
    )
    return number * low, number * high


def term_time_placement(title: str, requirements: str) -> bool:
    """Scheduling evidence, not graduation dates, coursework or Spring Boot."""
    pattern = (
        r"\b(?:winter|spring|fall|autumn)\b.{0,25}\b(?:20\d{2}|internship|placement|co.op|term)\b|"
        r"\b(?:internship|placement|co.op)\b.{0,25}\b(?:winter|spring|fall|autumn)\b|"
        r"\b(?:semester.long|term.time|during (?:the )?(?:school )?semester)\b"
    )
    return any(
        re.search(pattern, statement, re.I)
        for statement in [title, *source_statements(requirements)]
        if not re.search(r"graduat|class of|Spring Boot", statement, re.I)
    )


def program_evidence(title: str, text: str, *, configured: bool = False) -> bool:
    if staff_role(title):
        return False
    if configured or re.search(
        r"scholarship|fellowship|workshop|conference|summit|spring week|open day|"
        r"career fair|recruiting event|hackathon|\bexpo\b|"
        r"(?:discovery|exploratory|insight) program",
        title,
        re.I,
    ):
        return True
    return bool(
        re.search(r"\b(?:program(?:me)?|academy|insight|discovery|exploratory)\b", title, re.I)
        and re.search(
            r"participants?|cohort|students?|work shadow|program dates|mentorship|workshop", text, re.I
        )
    )


def qualification_heading(text: str) -> str | None:
    """Recognize employer headings without treating company prose as requirements."""
    if re.fullmatch(
        r"(?:(?:minimum|basic|required|preferred|desired|additional|optional)\s+)?"
        r"(?:(?:job|internship|candidate|position)\s+)?"
        r"(?:qualifications|requirements|skills|education)"
        r"(?:\s+(?:and|&)\s+(?:experience|skills|education|qualifications))?:?",
        text,
        re.I,
    ) or re.fullmatch(
        r"(?:who you are|what you bring|skills you(?:'|’)ll need|"
        r"what we(?:'|’)re looking for|we(?:'|’)re looking for someone who has|"
        r"nice.to.have|bonus(?: qualifications)?):?",
        text,
        re.I,
    ):
        return (
            "preferred"
            if re.search(r"preferred|desired|optional|nice.to.have|bonus", text, re.I)
            else "required"
        )
    return None


def parse_constraints(text: str) -> list[dict[str, Any]]:
    """Preserve exact clauses, alternatives and unresolved interpretations."""
    clauses: list[tuple[str, str]] = []
    modality = "unspecified"
    for line in source_statements(text):
        line = line.strip()
        if not line:
            continue
        if heading := qualification_heading(line):
            modality = heading
            continue
        if re.fullmatch(r"(?:benefits|responsibilities|compensation|about us|what you.ll do):?", line, re.I):
            modality = "unspecified"
        local = clause_modality(line, modality)
        clauses.append((line, local))
    constraints: list[dict[str, Any]] = []
    for index, (clause, modality) in enumerate(clauses):
        evidence = clause[:1000]
        if len(clause) > 1000:
            continue  # Do not derive constraints from a truncated premise.
        if re.search(r"\b(?:founders?|cofounders?|CEO|our team)\b", clause, re.I) and not re.search(
            r"applicants?|candidates?|must|required|eligib", clause, re.I
        ):
            continue
        if re.search(r"graduat\w*.{0,45}(?:20\d{2}|between|before|after)|class of 20\d{2}", clause, re.I):
            windows = graduation_windows(clause)
            constraints.append(
                {
                    "kind": "graduation",
                    "evidence": evidence,
                    "modality": modality,
                    "windows": windows,
                    "resolved": windows is not None,
                }
            )
        degrees = [degree for degree, pattern in _DEGREES.items() if re.search(pattern, clause, re.I)]
        academic = re.search(
            r"degree|stud(?:ent|ies)|enrolled|pursuing|education|required|graduate|BS/MS|BS, MS", clause, re.I
        )
        if degrees and (academic or modality != "unspecified"):
            exception = (
                clause
                if re.search(
                    r"exceptional undergrad|undergrad\w*.{0,50}(?:also|encouraged|considered)", clause, re.I
                )
                else ""
            )
            if index + 1 < len(clauses) and re.search(
                r"undergrad\w*.{0,80}(?:also|encouraged|considered)", clauses[index + 1][0], re.I
            ):
                exception = clauses[index + 1][0][:1000]
            state = (
                "enrolled"
                if re.search(
                    r"pursuing|enrolled|working (?:toward|towards)|current.{0,30}stud(?:ent|ies)",
                    clause,
                    re.I,
                )
                else "unknown"
            )
            study_progress = bool(
                re.search(
                    r"complet(?:ed|e|ion).{0,60}\b(?:years?|terms?|semesters?|credits?|units?|courses?|coursework)\b",
                    clause,
                    re.I,
                )
            )
            if not study_progress and (
                re.search(r"completed|earned|hold|possess", clause, re.I)
                or (
                    modality == "required"
                    and re.search(r"degree|\bBS/MS/PhD\b", clause, re.I)
                    and state != "enrolled"
                )
            ):
                state = "completed"
            if re.search(
                r"equivalent (?:experience|training)|or equivalent|"
                r"(?:by|upon|before).{0,25}(?:20\d{2}|start|graduation)",
                clause,
                re.I,
            ):
                state = "unknown"
            if modality == "unspecified" and re.search(
                r"preferred|desirable|desired|bonus|not required|no.{0,45}required", clause, re.I
            ):
                state = "unknown"
            constraints.append(
                {
                    "kind": "education",
                    "evidence": evidence,
                    "modality": modality,
                    "degrees": degrees,
                    "state": state,
                    "exception": exception,
                    "study_progress": study_progress,
                    "degree_operator": degree_operator(clause, degrees, state),
                }
            )
        if re.search(r"law schools?|medical schools?", clause, re.I) and re.search(
            r"enrolled|students?|matriculated", clause, re.I
        ):
            constraints.append(
                {"kind": "professional-enrollment", "evidence": evidence, "modality": modality}
            )
        if authorization_requirement(clause):
            constraints.append({"kind": "work-authorization", "evidence": evidence, "modality": modality})
        if re.search(r"\b(?:travel|airfare|flights?)\b", clause, re.I):
            funding = travel_funding(clause)
            constraints.append(
                {"kind": "travel-funding", "evidence": evidence, "modality": modality, "funding": funding}
            )
        if (
            re.search(r"clearance", clause, re.I)
            and re.search(r"required|must|obtain|eligible", clause, re.I)
            and not re.search(r"no.{0,20}clearance|clearance.{0,20}not required", clause, re.I)
        ):
            constraints.append({"kind": "security-clearance", "evidence": evidence, "modality": modality})
        if (
            re.search(r"universit|institution", clause, re.I)
            and re.search(r"\b(?:UK|EU)\b", clause)
            and re.search(r"enrolled|stud(?:ent|ying)|attend|eligible|applicants?", clause, re.I)
            and not re.search(r"worldwide|outside|any countr|not limited|collaborat|partners?", clause, re.I)
        ):
            constraints.append(
                {
                    "kind": "institution-region",
                    "evidence": evidence,
                    "modality": modality,
                    "regions": re.findall(r"\b(?:UK|EU)\b", clause),
                }
            )
        if re.search(r"\b(?:program|fellowship|rotation|internship|co.op)\b", clause, re.I) and re.search(
            r"\b(?:\d+|six|twelve|one|two)[ -](?:month|week|day)s?\b", clause, re.I
        ):
            constraints.append({"kind": "duration", "evidence": evidence, "modality": modality})
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for constraint in constraints:
        key = (constraint["kind"], constraint["evidence"])
        previous = unique.get(key)
        if previous and previous["modality"] != constraint["modality"]:
            constraint = {**constraint, "modality": "unspecified", "conflicting_context": True}
            if constraint["kind"] == "education":
                constraint["state"] = "unknown"
            elif constraint["kind"] == "graduation":
                constraint.update(windows=None, resolved=False)
            elif constraint["kind"] == "travel-funding":
                constraint["funding"] = "unknown"
        elif previous and previous.get("conflicting_context"):
            constraint = previous
        unique[key] = constraint
    result = list(unique.values())
    if len(result) > 60:
        result = result[:60]
        result[-1] = {**result[-1], "extraction_incomplete": True}
    return result
