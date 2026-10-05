"""Private comparison of source constraints with explicitly documented facts."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .source_constraints import parse_constraints


@lru_cache(maxsize=256)
def _legacy_constraints(text: str) -> str:
    # Cache public text only; decode a fresh result so callers cannot share mutations.
    return json.dumps(parse_constraints(text))


def candidate_constraints(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    captured = candidate.get("source_constraints")
    if isinstance(captured, list):
        return captured
    return json.loads(
        _legacy_constraints(
            "\n".join(
                str(candidate.get(key) or "")
                for key in (
                    "requirements_text",
                    "class_year_language",
                    "graduation_window_language",
                    "work_auth_language",
                )
            )
        )
    )


def compare_constraints(
    candidate: dict[str, Any], profile: dict[str, Any]
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    reasons: list[dict[str, str]] = []
    questions: list[str] = []
    failures: list[str] = []

    def finding(code: str, rule: dict[str, Any], message: str, failure: bool = False) -> None:
        reasons.append(
            {"code": code, "field": "source_constraints", "evidence": rule["evidence"], "message": message}
        )
        if failure:
            failures.append(code)

    for rule in candidate_constraints(candidate):
        if rule.get("extraction_incomplete"):
            questions.append(
                "Captured constraints reached the extraction limit; inspect remaining official requirements."
            )
        if rule.get("conflicting_context"):
            questions.append("Clarify conflicting requirement contexts: " + rule["evidence"])
            continue
        if rule["modality"] in {"preferred", "not-required"}:
            continue
        kind = rule["kind"]
        if kind == "education":
            choices = rule["degrees"]
            operator = rule.get("degree_operator", "any")
            if rule.get("study_progress"):
                questions.append("Confirm completed study duration or credits: " + rule["evidence"])
            if rule["exception"]:
                questions.append(
                    "Check the stated undergraduate exception against documented research or experience: "
                    + rule["exception"]
                )
            elif operator == "unknown":
                questions.append(
                    "Clarify whether the source's degree options are alternatives: " + rule["evidence"]
                )
            elif rule["state"] == "enrolled":
                if not profile["degree"]:
                    questions.append("Confirm current degree enrollment: " + rule["evidence"])
                elif profile["degree"] not in choices:
                    finding(
                        "degree-enrollment-mismatch",
                        rule,
                        "Known degree enrollment differs from every stated option.",
                        True,
                    )
            elif rule["state"] == "completed":
                completed = profile["completed_degrees"]
                if completed is None:
                    questions.append(
                        "Confirm completed degrees against the source's degree requirement: "
                        + rule["evidence"]
                    )
                elif not (
                    set(choices) <= set(completed)
                    if operator == "all"
                    else bool(set(completed).intersection(choices))
                ):
                    finding(
                        "completed-degree-mismatch",
                        rule,
                        "The documented completed-degree inventory does not satisfy the stated options.",
                        True,
                    )
            elif rule["state"] == "unknown" and not rule.get("study_progress"):
                questions.append(
                    "Clarify whether the degree requirement means enrollment, completion, "
                    "or equivalent experience: " + rule["evidence"]
                )
        elif kind == "professional-enrollment" and profile["student_status"] == "undergraduate":
            if not re.search(r"undergrad|bachelor", rule["evidence"], re.I):
                # General undergraduate status alone does not establish whether
                # a student is in a professional-entry degree internationally.
                questions.append(
                    "Confirm professional-school enrollment required by the source: " + rule["evidence"]
                )
        elif kind == "work-authorization":
            evidence = rule["evidence"]
            us_rule = re.search(r"U\.?S\.?|United States", evidence, re.I)
            citizenship_option = re.search(r"citizen|U\.?S\.? Person", evidence, re.I)
            negated = re.search(r"not|non.citizen|except|excluding", evidence, re.I)
            if us_rule and citizenship_option and not negated and "US" in profile["citizenships"]:
                finding(
                    "citizenship-requirement-match",
                    rule,
                    "Documented US citizenship matches the stated citizenship/export-person option; "
                    "separate clearance conditions remain unresolved.",
                )
            else:
                questions.append(
                    "Confirm the exact work-authorization or citizenship requirement: " + evidence
                )
        elif kind == "security-clearance":
            questions.append("Confirm additional security-clearance conditions: " + rule["evidence"])
        elif kind == "institution-region":
            regions = profile["institution_regions"]
            if not regions:
                questions.append(
                    "Confirm institution location against the source's restriction: " + rule["evidence"]
                )
            elif not set(regions).intersection(rule["regions"]):
                finding(
                    "institution-region-mismatch",
                    rule,
                    "Documented institution region is outside the source's allowed regions.",
                    True,
                )
    return reasons, list(dict.fromkeys(questions)), failures


def evidence_packet(
    candidate: dict[str, Any], finding: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    """Small provider-neutral input; source and applicant facts remain separate."""
    return {
        "source_constraints": candidate_constraints(candidate),
        "unresolved_questions": finding["questions"],
        "captured_requirements": str(candidate.get("requirements_text") or "")[:2400],
        "documented_profile": {
            key: profile[key]
            for key in (
                "degree",
                "completed_degrees",
                "graduation_month",
                "year_in_program",
                "unit_based_standing",
                "majors",
                "citizenships",
                "institution_regions",
                "term_time_work",
                "source_refs",
            )
        },
        "instruction": (
            "Resolve only the stated conflicts using quoted source evidence and documented facts. "
            "Preserve unknowns; this packet does not establish an official-page check."
        ),
    }


def compact_review_batch(page: dict[str, Any]) -> dict[str, Any]:
    """Optional AI handoff: shared profile once, with all source quotes retained."""
    items = []
    shared_profile = None
    for item in page["items"]:
        packet = item["ai_evidence_packet"]
        shared_profile = packet["documented_profile"]
        constraints = packet["source_constraints"]
        quoted = {rule["evidence"] for rule in constraints}
        remaining = "\n".join(
            line for line in packet["captured_requirements"].splitlines() if line.strip() not in quoted
        )
        items.append(
            {
                **{
                    key: item.get(key)
                    for key in (
                        "opportunity_id",
                        "title",
                        "organization",
                        "canonical_url",
                        "engagement_type",
                        "location_text",
                        "remote_signal",
                        "stated_deadline",
                        "research_status",
                        "audit_group",
                        "class_year_language",
                        "graduation_window_language",
                        "major_language",
                        "experience_requirement",
                        "compensation_text",
                        "relocation_text",
                        "application_state",
                        "event_start_date",
                        "event_end_date",
                    )
                },
                "screening": {
                    key: item["screening"][key]
                    for key in (
                        "state",
                        "candidate_hash",
                        "profile_hash",
                        "screening_version",
                    )
                },
                "review_selection": {
                    key: item["review_selection"][key] for key in ("selected", "action", "message")
                },
                "ai_evidence_packet": {
                    **{
                        key: value
                        for key, value in packet.items()
                        if key not in {"documented_profile", "captured_requirements"}
                    },
                    "captured_requirements": remaining,
                },
            }
        )
    return {
        **page,
        "items": items,
        "documented_profile": shared_profile,
        "packet_format": "compact-evidence-v1",
    }
