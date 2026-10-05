"""Provider-neutral review selection across clear, unresolved and carried leads."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opportunity_discovery.cli import main
from opportunity_discovery.workspace_screening import (
    _research,
    _review_role_conflict,
    _review_selection,
    apply_screening_response,
    list_personal_feed,
    screen_candidate,
    screen_collection,
    set_screening_profile,
    validate_profile,
)
from tests.test_workspace_screening import PROFILE, lead, response, setup

NOW = datetime(2035, 4, 15, tzinfo=UTC)
EARLY = {**PROFILE, "opportunity_focus": "early-opportunities"}
CASES = json.loads((Path(__file__).parent / "fixtures/demo/review-selection-cases.json").read_text())


def test_review_queue_combines_clear_and_promising_questions_and_keeps_backlog_recoverable(tmp_path, capsys):
    candidates = [
        lead(index, **{k: v for k, v in case.items() if k != "expected_action"})
        for index, case in enumerate(CASES, 1)
    ]
    root, manifest = setup(tmp_path, candidates)
    set_screening_profile(root, EARLY)
    screen_collection(root, manifest)
    before = (root / ".opdisc/screening.json").read_bytes()
    public = (manifest.parent / "candidates.jsonl").read_bytes()
    all_feed = list_personal_feed(root, manifest, state_filter="all", uncapped=True, now=NOW)
    indexed = {item["opportunity_id"]: item for item in all_feed["items"]}
    for candidate, case in zip(candidates, CASES, strict=True):
        assert indexed[candidate["opportunity_id"]]["review_selection"]["action"] == case["expected_action"]
    page = list_personal_feed(root, manifest, review_only=True, uncapped=True, now=NOW)
    assert {item["opportunity_id"] for item in page["items"]} == {r["opportunity_id"] for r in candidates[:3]}
    assert page["items"][0]["opportunity_id"] == candidates[2]["opportunity_id"]
    assert page["coverage"]["selected_for_review"] == 3
    assert page["coverage"]["selected_needing_clarification"] == 2
    assert page["coverage"]["awaiting_investigation"] == 6
    assert next(q for q in page["profile_questions"] if q["field"] == "gpa")["affected_leads"] == 2
    assert main(["workspace-screening", str(root), "--manifest", str(manifest), "--uncapped"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 3
    assert (
        main(
            [
                "workspace-screening",
                str(root),
                "--manifest",
                str(manifest),
                "--include-deferred",
                "--uncapped",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["total"] == 6
    assert (
        main(
            [
                "workspace-screening",
                str(root),
                "--manifest",
                str(manifest),
                "--review-action",
                "clarify-profile",
                "--uncapped",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["total"] == 2
    assert (
        main(["workspace-screening", str(root), "--manifest", str(manifest), "--state", "all", "--uncapped"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["total"] == 7
    assert before == (root / ".opdisc/screening.json").read_bytes()
    assert public == (manifest.parent / "candidates.jsonl").read_bytes()


def official_record(row, *, checked_at="2035-04-14T00:00:00Z", unresolved=False):
    return {
        "collector_snapshot": row,
        "review": {
            "reviewed_at": checked_at,
            "disposition": "defer" if unresolved else "promote",
            "official_evidence": {
                "checked_at": checked_at,
                "availability": "unknown" if unresolved else "open",
            },
        },
        "eligibility": {"conclusion": "unknown" if unresolved else "no-known-hard-failure"},
    }


@pytest.mark.parametrize("unresolved,expected", [(False, "reuse-findings"), (True, "await-new-evidence")])
def test_unchanged_official_checks_are_deferred_but_real_changes_and_staleness_return(unresolved, expected):
    row = lead()
    profile = validate_profile(EARLY)
    record = official_record(row, unresolved=unresolved)
    research, reasons = _research(row, record, profile, NOW)
    selection = _review_selection(screen_candidate(row, profile), research, reasons, True)
    assert not selection["selected"] and selection["action"] == expected
    changed = {**row, "requirements_text": "Changed Physics requirements."}
    research, reasons = _research(changed, record, profile, NOW)
    assert "source-facts-changed" in reasons
    assert _review_selection(screen_candidate(changed, profile), research, reasons, True)["selected"]
    record = official_record(row, checked_at="2035-01-01T00:00:00Z", unresolved=unresolved)
    research, reasons = _research(row, record, profile, NOW)
    assert "stale-official-check" in reasons
    assert _review_selection(screen_candidate(row, profile), research, reasons, True)["selected"]


def test_unreviewed_deadline_is_prioritized_and_fresh_check_does_not_repeat():
    row = lead(stated_deadline="2035-04-20")
    profile = validate_profile(EARLY)
    research, reasons = _research(row, {}, profile, NOW)
    assert "deadline-approaching" in reasons
    record = official_record(row)
    assert _research(row, record, profile, NOW) == ("checked-current", [])
    record = official_record(row, checked_at="2035-03-28T00:00:00Z")
    assert "deadline-approaching" in _research(row, record, profile, NOW)[1]


def test_saved_semantic_questions_proceed_to_official_research_without_repeating_triage(tmp_path):
    row = lead(graduation_window_language="Graduating before 2037.")
    root, manifest = setup(tmp_path, [row])
    finding = screen_candidate(row, validate_profile(PROFILE))
    apply_screening_response(
        root,
        response(root, manifest, row, state="needs-clarification", questions=finding["questions"]),
        manifest,
    )
    page = list_personal_feed(root, manifest, review_only=True)
    assert page["items"][0]["review_selection"]["action"] == "official-research"
    assert page["items"][0]["screening"]["origin"] == "ai-screening"
    assert page["coverage"]["officially_checked"] == 0


def test_academic_definition_is_source_question_and_employer_cap_does_not_hide_preferred_programs(tmp_path):
    row = lead(class_year_language="Sophomore standing required.")
    finding = screen_candidate(row, validate_profile(EARLY))
    selection = _review_selection(finding, "not-checked", [], True)
    assert selection["selected"] and selection["source_questions"]
    programs = [
        lead(index, title="Physics Discovery Program", engagement_type="program", requirements_text=None)
        for index in range(1, 6)
    ]
    root, manifest = setup(tmp_path, programs)
    set_screening_profile(root, EARLY)
    page = list_personal_feed(root, manifest, review_only=True)
    assert page["total"] == 5 and page["cap_exempt_programs"] == 5


@pytest.mark.parametrize(
    "title,conflict",
    [
        ("Senior Program Controller", True),
        ("Academy Senior Recruiter", True),
        ("Program Finance Analyst", True),
        ("Academy Investment Analyst Program for Experienced Professionals", True),
        ("Campus Quantitative Researcher, PhD (Intern)", True),
        ("Research Intern (BS/MS/PhD)", False),
        ("Senior Year Physics Internship", False),
        ("Student Leadership Discovery Program", False),
        ("Senior Year Physics Research Program", False),
        ("Physics Research Intern - MS Dynamics", False),
    ],
)
def test_role_title_conflicts_are_recoverable_without_changing_eligibility(tmp_path, title, conflict):
    row = lead(title=title)
    root, manifest = setup(tmp_path, [row])
    set_screening_profile(root, EARLY)
    screen_collection(root, manifest)
    before = (root / ".opdisc/screening.json").read_bytes()
    profile = validate_profile(EARLY)
    assert bool(_review_role_conflict(row, profile)) == conflict
    page = list_personal_feed(root, manifest, review_only=True)
    assert bool(page["items"]) != conflict
    recovered = list_personal_feed(root, manifest, state_filter="all")
    assert recovered["items"][0]["screening"]["state"] == "worth-investigating"
    assert before == (root / ".opdisc/screening.json").read_bytes()


def test_clear_match_outside_stage_is_deferred_without_a_hard_eligibility_failure(tmp_path):
    row = lead(title="Physics Technician", engagement_type="full-time")
    root, manifest = setup(tmp_path, [row])
    set_screening_profile(root, EARLY)
    screen_collection(root, manifest)
    assert list_personal_feed(root, manifest, review_only=True)["items"] == []
    item = list_personal_feed(root, manifest)["items"][0]
    assert item["screening"]["state"] == "worth-investigating"
    assert item["review_selection"]["action"] == "outside-stage-focus"
    set_screening_profile(root, {**PROFILE, "opportunity_focus": "new-grad"})
    assert list_personal_feed(root, manifest, review_only=True)["items"]


def test_inclusive_degree_enrollment_is_retained_and_preferred_graduate_study_is_not_a_barrier():
    profile = validate_profile(EARLY)
    assert (
        _review_role_conflict(lead(class_year_language="Currently pursuing a BS, MS or PhD degree."), profile)
        is None
    )
    assert _review_role_conflict(
        lead(class_year_language="Master's students must be currently enrolled."), profile
    )
    assert (
        _review_role_conflict(
            lead(class_year_language="Preferred Qualifications\nLaw school students."), profile
        )
        is None
    )
