"""Synthetic public facts and private-profile comparisons, including missed leads."""

import json
from pathlib import Path

import jsonschema
import pytest

from opportunity_discovery import constants as c
from opportunity_discovery.cli import main
from opportunity_discovery.extraction import extract_description
from opportunity_discovery.models import RawOpportunity
from opportunity_discovery.routing import normalize_routing_fields, route_profiles
from opportunity_discovery.source_constraints import (
    authorization_requirement,
    graduation_windows,
    parse_constraints,
    program_evidence,
)
from opportunity_discovery.workspace_constraints import candidate_constraints, compact_review_batch
from opportunity_discovery.workspace_screening import (
    _review_role_conflict,
    apply_screening_response,
    list_personal_feed,
    screen_candidate,
    validate_profile,
)
from opportunity_discovery.workspace_state import _promotion_threshold
from tests.test_workspace_screening import PROFILE, lead, response, setup

CASES = json.loads((Path(__file__).parent / "fixtures/demo/accuracy-constraints.json").read_text())


@pytest.mark.parametrize(
    "text",
    [
        "Bachelor's degree preferred but not required.",
        "No master's degree required.",
        "PhD is not necessary.",
    ],
)
def test_explicit_degree_waivers_do_not_reject_students(text):
    facts = extract_description("Required Qualifications\n" + text)
    assert facts["source_constraints"][0]["modality"] == "not-required"
    fields = normalize_routing_fields(RawOpportunity(title="Intern", canonical_url="", **facts))
    assert fields["required_degree"] == "unknown"
    row = lead(**facts)
    finding = screen_candidate(row, validate_profile({**PROFILE, "completed_degrees": []}))
    assert finding["state"] == "worth-investigating"


@pytest.mark.parametrize(
    "text",
    [
        "Must have completed one year of an undergraduate degree.",
        "Must be pursuing a bachelor's degree and have completed two semesters.",
        "Must have completed 30 credits toward an undergraduate degree.",
    ],
)
def test_study_progress_does_not_require_an_awarded_degree(text):
    facts = extract_description("Required Qualifications\n" + text)
    finding = screen_candidate(lead(**facts), validate_profile({**PROFILE, "completed_degrees": []}))
    assert finding["state"] == "needs-clarification"
    assert any(q.startswith("Confirm completed study duration") for q in finding["questions"])
    assert not any(r["code"] == "completed-degree-mismatch" for r in finding["reasons"])


@pytest.mark.parametrize(
    "text,operator,expected",
    [
        ("Bachelor's degree and master's degree required.", "all", "low-relevance"),
        ("Bachelor's degree or master's degree required.", "any", "worth-investigating"),
        ("Currently pursuing a bachelor's and master's degree.", "unknown", "needs-clarification"),
        ("Bachelor's and master's or doctoral degrees required.", "unknown", "needs-clarification"),
    ],
)
def test_degree_conjunctions_do_not_become_unconditional_alternatives(text, operator, expected):
    facts = extract_description(text)
    assert facts["source_constraints"][0]["degree_operator"] == operator
    finding = screen_candidate(
        lead(**facts), validate_profile({**PROFILE, "completed_degrees": ["bachelors"]})
    )
    assert finding["state"] == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Travel costs are paid by students.", "uncovered"),
        ("Students must pay for travel.", "uncovered"),
        ("Travel is covered by attendees.", "uncovered"),
        ("Travel is partially reimbursed.", "unknown"),
        ("Travel is reimbursed up to $50.", "unknown"),
        ("Travel reimbursement is subject to approval.", "unknown"),
        ("Travel will be covered.", "covered"),
    ],
)
def test_funding_payer_and_limits_match_in_structured_and_legacy_paths(text, expected):
    from opportunity_discovery.workspace_screening import _travel_funding

    rules = parse_constraints(text)
    assert rules[0]["funding"] == expected
    assert _travel_funding({"relocation_text": text})[0] == expected
    assert _travel_funding({"source_constraints": rules})[0] == expected


def test_abbreviations_and_mixed_required_preferred_clauses_preserve_evidence():
    facts = extract_description(
        "Required Qualifications\nMust be a U.S. Citizen.\n"
        "Bachelor's degree required but master's degree preferred."
    )
    assert any(rule["kind"] == "work-authorization" for rule in facts["source_constraints"])
    education = [rule for rule in facts["source_constraints"] if rule["kind"] == "education"]
    assert [(rule["degrees"], rule["modality"]) for rule in education] == [
        (["bachelors"], "required"),
        (["masters"], "preferred"),
    ]
    assert facts["required_degree"] == "bachelors"
    for name in ("candidate.schema.json", "review-queue-entry.schema.json"):
        schema = json.loads((Path(__file__).parent.parent / "schemas" / name).read_text())
        jsonschema.validate(facts["source_constraints"], schema["properties"]["source_constraints"])


def test_compact_cli_preserves_hashes_quotes_and_source_facts_without_repeated_profile(tmp_path, capsys):
    text = "Must be enrolled as an undergraduate majoring in Physics."
    rows = [
        lead(i, source_constraints=parse_constraints(text), event_start_date="2035-06-01") for i in (1, 2)
    ]
    root, manifest = setup(tmp_path, rows)
    full = list_personal_feed(root, manifest, review_only=True)
    before = (manifest.parent / "candidates.jsonl").read_bytes()
    compact = compact_review_batch(full)
    assert len(json.dumps(compact)) < len(json.dumps(full))
    assert compact["documented_profile"] == full["items"][0]["ai_evidence_packet"]["documented_profile"]
    for original, item in zip(full["items"], compact["items"], strict=True):
        assert item["screening"]["candidate_hash"] == original["screening"]["candidate_hash"]
        assert (
            item["ai_evidence_packet"]["source_constraints"]
            == original["ai_evidence_packet"]["source_constraints"]
        )
        assert "documented_profile" not in item["ai_evidence_packet"]
        assert text not in item["ai_evidence_packet"]["captured_requirements"]
        assert item["major_language"] == original["major_language"]
        assert item["event_start_date"] == "2035-06-01"
    assert main(["workspace-screening", str(root), "--manifest", str(manifest), "--compact"]) == 0
    assert json.loads(capsys.readouterr().out)["packet_format"] == "compact-evidence-v1"
    assert before == (manifest.parent / "candidates.jsonl").read_bytes()
    assert compact_review_batch({**full, "items": []})["items"] == []


def test_many_unresolved_source_clauses_can_round_trip_without_dropping_questions(tmp_path):
    text = "Required Qualifications\n" + "\n".join(
        f"Bachelor's degree required for task {i}." for i in range(35)
    )
    row = lead(requirements_text=text, source_constraints=parse_constraints(text))
    root, manifest = setup(tmp_path, [row])
    finding = screen_candidate(row, validate_profile(PROFILE))
    assert len(finding["questions"]) >= 35
    document = response(root, manifest, row, state="needs-clarification", questions=finding["questions"])
    schema = json.loads(
        (Path(__file__).parent.parent / "schemas/workspace-screening-response.schema.json").read_text()
    )
    jsonschema.validate(document, schema)
    assert apply_screening_response(root, document, manifest)["applied"] == 1


def test_optional_headings_and_mastering_tools_are_not_required_degrees():
    facts = extract_description(
        "Required Qualifications\nMaster software tools and workflows.\n"
        "Optional Qualifications\nM.S. degree in Physics."
    )
    assert facts["required_degree"] is None
    assert len(facts["source_constraints"]) == 1
    assert facts["source_constraints"][0]["modality"] == "preferred"
    finding = screen_candidate(lead(**facts), validate_profile({**PROFILE, "completed_degrees": []}))
    assert finding["state"] == "worth-investigating"


@pytest.mark.parametrize(
    "requirements",
    [
        "Experience with Spring Boot and waterfall development required.",
        "Candidates must currently be enrolled and graduating in spring 2036.",
    ],
)
def test_technical_terms_and_graduation_seasons_do_not_establish_term_time_placements(requirements):
    profile = validate_profile({**PROFILE, "term_time_work": False})
    finding = screen_candidate(lead(requirements_text=requirements), profile)
    assert not any(r["code"] == "term-time-outside-preference" for r in finding["reasons"])


def test_dotted_degree_abbreviations_keep_completion_inventory_unknown():
    facts = extract_description("Required Qualifications\nM.S. required.")
    assert facts["source_constraints"][0]["degrees"] == ["masters"]
    finding = screen_candidate(lead(**facts), validate_profile(PROFILE))
    assert finding["state"] == "needs-clarification"


def test_conflicting_repeated_source_contexts_cannot_silently_clear_or_fail_eligibility():
    text = (
        "Required Qualifications\nCurrently pursuing a master's degree.\n"
        "Preferred Qualifications\nCurrently pursuing a master's degree.\n"
        "Preferred Qualifications\nCurrently pursuing a master's degree."
    )
    rules = parse_constraints(text)
    assert len(rules) == 1
    assert rules[0]["conflicting_context"]
    finding = screen_candidate(
        lead(source_constraints=rules, requirements_text=text), validate_profile(PROFILE)
    )
    assert finding["state"] == "needs-clarification"
    assert any(q.startswith("Clarify conflicting requirement contexts") for q in finding["questions"])


def test_extraction_limit_is_visible_and_does_not_look_like_complete_eligibility():
    text = "Required Qualifications\n" + "\n".join(
        f"Currently pursuing an undergraduate degree for task {i}." for i in range(70)
    )
    rules = parse_constraints(text)
    assert len(rules) == 60
    assert rules[-1]["extraction_incomplete"]
    finding = screen_candidate(
        lead(source_constraints=rules, requirements_text=text), validate_profile(PROFILE)
    )
    assert finding["state"] == "needs-clarification"
    assert any("extraction limit" in q for q in finding["questions"])


def test_legacy_parsing_cache_does_not_share_mutable_constraints():
    row = lead(source_constraints=None)
    first = candidate_constraints(row)
    original = first[0]["evidence"]
    first[0]["evidence"] = "altered by caller"
    assert candidate_constraints(row)[0]["evidence"] == original


def test_explicit_empty_extraction_does_not_resurrect_legacy_graduation_or_degree_flags():
    row = lead(
        source_constraints=[], required_degree="masters", graduation_window_language="Graduating in 2034."
    )
    finding = screen_candidate(row, validate_profile(PROFILE))
    assert finding["state"] == "worth-investigating"


def test_preferred_skills_and_experience_heading_does_not_require_a_graduate_degree():
    facts = extract_description(
        "Basic Qualifications:\nMust be enrolled as an undergraduate.\n"
        "Preferred Skills and Experience:\nMaster's degree in Physics."
    )
    assert facts["required_degree"] != "masters"
    finding = screen_candidate(lead(**facts), validate_profile({**PROFILE, "completed_degrees": []}))
    assert finding["state"] == "worth-investigating"


@pytest.mark.parametrize("case", CASES)
def test_explicit_alternatives_preserve_gaps_and_ambiguous_bounds(case):
    windows = graduation_windows(case["text"])
    if case["matches"] is None:
        assert windows is None
    else:
        assert windows and any(low <= case["month"] <= high for low, high in windows) == case["matches"]


@pytest.mark.parametrize(
    "title,type_", [("Product Planning Intern", "internship"), ("Physics Co-op", "co-op")]
)
def test_full_time_hours_do_not_override_student_role(title, type_):
    raw = RawOpportunity(
        title=title, canonical_url="https://synthetic.example/role", employment_type="full-time"
    )
    fields = normalize_routing_fields(raw)
    assert fields["engagement_type"] == type_
    assert fields["career_stage"] == "student"
    assert route_profiles(fields)[c.PROFILE_STUDENT].state == c.ROUTE_INCLUDED
    assert raw.employment_type == "full-time"


@pytest.mark.parametrize(
    "title", ["Program Scheduler", "Academy Recruiter", "Program Finance Analyst", "Developer Advocate"]
)
def test_professional_jobs_do_not_become_exploratory_programs(title):
    raw = RawOpportunity(
        title=title,
        canonical_url="https://synthetic.example/role",
        employment_type="full-time",
        requirements_text="Benefits include conferences and a graduate training program.",
    )
    assert normalize_routing_fields(raw)["engagement_type"] == "full-time"
    assert not program_evidence(title, raw.requirements_text)


def test_full_description_preserves_restrictions_after_display_bounds():
    text = "Required Qualifications\n" + "Must communicate effectively.\n" * 120
    text += "Graduating in fall 2034 or spring 2035.\nCurrently pursuing a PhD or MSc degree."
    facts = extract_description(text)
    assert len(facts["requirements_text"]) <= 2400
    assert any(rule["kind"] == "graduation" for rule in facts["source_constraints"])
    assert any(rule.get("degrees") == ["masters", "doctorate"] for rule in facts["source_constraints"])
    row = lead(**facts)
    finding = screen_candidate(row, validate_profile(PROFILE))
    assert finding["state"] == "low-relevance"
    assert {r["code"] for r in finding["reasons"]} >= {
        "degree-enrollment-mismatch",
        "graduation-window-mismatch",
    }


def test_alternative_headings_capture_experience_and_explicit_until_deadline():
    facts = extract_description(
        "We have 30 years across the industry.\nWhat we're looking for\n"
        "10+ years across video production and engineering.\n"
        "Bachelor's degree required.\nBonus Qualifications\nMaster's degree preferred.\n"
        "Applications remain open until October 31, 2035."
    )
    assert "10+ years" in facts["experience_requirement_text"]
    assert "30 years" not in facts["experience_requirement_text"]
    assert facts["deadline"] == "2035-10-31"
    fields = normalize_routing_fields(RawOpportunity(title="Engineer", canonical_url="", **facts))
    assert fields["experience_min_years"] == 10
    assert fields["required_degree"] == "bachelors"
    assert fields["preferred_degree"] == "masters"


def test_separate_required_degree_clauses_are_not_collapsed_into_alternatives():
    facts = extract_description(
        "Required Qualifications\nBachelor's degree required.\nMaster's degree required."
    )
    fields = normalize_routing_fields(RawOpportunity(title="Intern", canonical_url="", **facts))
    assert fields["required_degree"] == "masters"
    finding = screen_candidate(
        lead(**facts), validate_profile({**PROFILE, "completed_degrees": ["bachelors"]})
    )
    assert finding["state"] == "low-relevance"


def test_migrated_empty_constraint_column_still_reads_legacy_source_facts():
    row = lead(source_constraints=None, requirements_text="Must be currently pursuing a master's degree.")
    assert candidate_constraints(row)[0]["degrees"] == ["masters"]
    assert screen_candidate(row, validate_profile(PROFILE))["state"] == "low-relevance"


@pytest.mark.parametrize(
    "completed,expected",
    [(None, "needs-clarification"), ([], "low-relevance"), (["bachelors"], "worth-investigating")],
)
def test_degree_completion_uses_explicit_inventory_not_current_enrollment(completed, expected):
    row = lead(requirements_text="Required Qualifications\nBachelor's degree in Physics required.")
    finding = screen_candidate(row, validate_profile({**PROFILE, "completed_degrees": completed}))
    assert finding["state"] == expected


def test_degree_alternatives_and_undergraduate_exception_are_not_lost():
    text = (
        "Required Qualifications\nCurrently pursuing a PhD or Master's degree.\n"
        "Exceptional undergraduates with strong research experience are also encouraged to apply."
    )
    facts = extract_description(text)
    row = lead(title="Physics Research Intern (PhD)", **facts)
    profile = validate_profile(PROFILE)
    assert _review_role_conflict(row, profile) is None
    assert screen_candidate(row, profile)["state"] == "needs-clarification"
    assert any("undergraduate exception" in q for q in screen_candidate(row, profile)["questions"])
    equivalent = lead(
        requirements_text=(
            "Required Qualifications\nBachelor's degree or equivalent professional experience required."
        )
    )
    assert (
        screen_candidate(equivalent, validate_profile({**PROFILE, "completed_degrees": []}))["state"]
        == "needs-clarification"
    )


@pytest.mark.parametrize(
    "text",
    [
        "We do sponsor visas!",
        "Equal employment opportunity regardless of citizenship.",
        "Supported by executive sponsorship.",
        "Calculus coursework required.",
        "Visa sponsorship is available for selected roles.",
    ],
)
def test_benefits_and_boilerplate_do_not_generate_authorization_questions(text):
    assert not authorization_requirement(text)


def test_documented_citizenship_satisfies_only_the_citizenship_option():
    text = (
        "Required Qualifications\nMust be a U.S. citizen or permanent resident.\n"
        "Must obtain Top Secret clearance."
    )
    row = lead(requirements_text=text, work_auth_language=text, source_constraints=parse_constraints(text))
    finding = screen_candidate(row, validate_profile({**PROFILE, "citizenships": ["US"]}))
    assert not any(q.startswith("Confirm the exact work-authorization") for q in finding["questions"])
    assert any("clearance" in q for q in finding["questions"])
    unknown = screen_candidate(row, validate_profile(PROFILE))
    assert any(q.startswith("Confirm the exact work-authorization") for q in unknown["questions"])


@pytest.mark.parametrize("text", ["Travel is not paid.", "Travel is paid by the participant."])
def test_unfunded_travel_cannot_be_read_as_paid_coverage(text):
    rules = parse_constraints(text)
    assert rules[0]["funding"] == "uncovered"


def test_partner_regions_and_waived_clearance_are_not_requirements():
    assert not parse_constraints(
        "Students collaborate with partner universities in the UK. No security clearance required."
    )
    row = lead(requirements_text="Must be enrolled at a UK or EU university.")
    profile = validate_profile({**PROFILE, "institution_regions": ["US"]})
    assert screen_candidate(row, profile)["state"] == "low-relevance"


def test_long_constraint_questions_fit_the_semantic_response_contract():
    statement = "Bachelor's degree required with " + "relevant technical knowledge " * 31
    row = lead(requirements_text=statement)
    assert all(len(q) <= 1000 for q in screen_candidate(row, validate_profile(PROFILE))["questions"])


def test_term_availability_and_degree_unknowns_are_grouped_and_protected(tmp_path):
    rows = [
        lead(
            n,
            title="Winter Physics Internship",
            requirements_text="Required Qualifications\nBachelor's degree required.",
        )
        for n in (1, 2)
    ]
    root, manifest = setup(tmp_path, rows)
    page = list_personal_feed(root, manifest)
    counts = {q["field"]: q["affected_leads"] for q in page["profile_questions"]}
    assert (
        counts.items()
        >= {
            "completed_degrees": 2,
            "term_time_work": 2,
        }.items()
    )
    finding = screen_candidate(rows[0], validate_profile(PROFILE))
    document = response(root, manifest, rows[0], state="worth-investigating", questions=[])
    with pytest.raises(ValueError, match="preserve unresolved personal"):
        apply_screening_response(root, document, manifest)
    assert finding["questions"]


def test_long_rotation_cannot_use_short_program_funding_exception():
    profile = validate_profile({**PROFILE, "location_policy": "local-jobs-funded-programs"})
    text = "Participants join a six-month accelerated fellowship. Travel will be covered."
    row = lead(
        title="Physics Fellowship",
        engagement_type="fellowship",
        location_text="London, UK",
        source_constraints=parse_constraints(text),
        requirements_text=text,
    )
    assert screen_candidate(row, profile)["state"] == "low-relevance"
    short = {
        **row,
        "requirements_text": "A one-week residential workshop for students. Travel will be covered.",
        "source_constraints": parse_constraints(
            "A one-week residential workshop for students. Travel will be covered."
        ),
    }
    assert not any(
        r["code"] == "location-outside-regions" for r in screen_candidate(short, profile)["reasons"]
    )


def test_focused_packet_is_private_and_audit_sample_recovers_all_groups(tmp_path):
    rows = [
        lead(1),
        lead(2, title="Physics Technician", engagement_type="full-time"),
        lead(3, graduation_window_language="Graduating in 2034."),
    ]
    root, manifest = setup(tmp_path, rows)
    from opportunity_discovery.workspace_screening import set_screening_profile

    set_screening_profile(root, {**PROFILE, "opportunity_focus": "early-opportunities"})
    public = (manifest.parent / "candidates.jsonl").read_bytes()
    sample = list_personal_feed(root, manifest, state_filter="all", uncapped=True, audit_sample=True)
    assert {i["audit_group"] for i in sample["items"]} == {"selected", "deferred", "excluded"}
    assert (
        sample["items"]
        == list_personal_feed(root, manifest, state_filter="all", uncapped=True, audit_sample=True)["items"]
    )
    assert (
        sample["items"][0]["ai_evidence_packet"]["documented_profile"]["graduation_month"]
        == PROFILE["graduation_month"]
    )
    assert public == (manifest.parent / "candidates.jsonl").read_bytes()
    assert b"documented_profile" not in public


def test_generic_profile_exclusion_is_not_an_explicit_collector_policy_exclusion():
    decision = {
        "verification": {"supports_current_opportunity": True},
        "official_evidence": {"availability": "open"},
        "eligibility": {"conclusion": "no-known-hard-failure"},
        "reason_codes": ["profile-relevant"],
    }
    row = lead(routing_state="excluded", routing_reason_codes=["profile:full-time-excluded"])
    assert _promotion_threshold(decision, row) == (True, [])
    assert _promotion_threshold(decision, {**row, "reason_codes": ["exclude:policy"]}) == (
        False,
        ["collector-hard-exclusion"],
    )
