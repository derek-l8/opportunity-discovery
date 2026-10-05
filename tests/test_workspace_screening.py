"""Synthetic onboarding, personal screening, change memory, and privacy tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from opportunity_discovery.cli import main
from opportunity_discovery.workspace_dashboard import render_dashboard
from opportunity_discovery.workspace_discovery import list_explore
from opportunity_discovery.workspace_screening import (
    SCREENING_VERSION,
    apply_screening_response,
    candidate_fingerprint,
    list_personal_feed,
    screen_candidate,
    screen_collection,
    set_screening_profile,
    validate_profile,
)
from opportunity_discovery.workspace_state import WorkspaceStateError, apply_workspace_review
from tests.test_workspace_state import make_generation, make_workspace, materialize_review

PROFILE = json.loads((Path(__file__).parent / "fixtures/demo/screening-profile.json").read_text())
SCHEMAS = Path(__file__).parent.parent / "schemas"


def lead(index=1, **overrides):
    return {
        "opportunity_id": f"opp_{index:032x}",
        "title": "Physics Internship",
        "organization": "Synthetic Employer",
        "canonical_url": "https://synthetic.example/jobs/1",
        "active": True,
        "engagement_type": "internship",
        "career_stage": "student",
        "required_degree": "unknown",
        "location_text": "Cambridge, MA",
        "requirements_text": "Must be enrolled as an undergraduate majoring in Physics.",
        "class_year_language": "Must be enrolled as an undergraduate.",
        "major_language": "Physics or a related STEM major",
        "graduation_window_language": "Expected graduation between December 2035 and August 2036.",
        **overrides,
    }


def generation(tmp_path, candidates):
    directory = tmp_path / "screening-export"
    directory.mkdir(exist_ok=True)
    payload = "".join(json.dumps(candidate) + "\n" for candidate in candidates).encode()
    (directory / "candidates.jsonl").write_bytes(payload)
    manifest = {
        "generation_id": hashlib.sha256(payload).hexdigest(),
        "files": [{"filename": "candidates.jsonl", "sha256": hashlib.sha256(payload).hexdigest()}],
    }
    path = directory / "export_manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def setup(tmp_path, candidates):
    root = make_workspace(tmp_path)
    set_screening_profile(root, PROFILE)
    return root, generation(tmp_path, candidates)


def test_ai_normalized_metro_regions_and_graduation_match_without_embedded_ai():
    profile = validate_profile(PROFILE)
    finding = screen_candidate(lead(), profile)
    assert finding["state"] == "worth-investigating"
    assert {reason["code"] for reason in finding["reasons"]} >= {
        "location-match",
        "graduation-window-match",
        "major-mentioned",
    }
    elsewhere = screen_candidate(lead(location_text="Burlington, VT"), profile)
    assert elsewhere["state"] == "needs-clarification"
    assert not any(reason["code"] == "location-match" for reason in elsewhere["reasons"])


def test_unknown_personal_requirements_remain_questions_and_preferred_rules_do_not_fail():
    candidate = lead(
        requirements_text="GPA of at least 3.0 required; completed calculus coursework required.",
        graduation_window_language="Graduating in 2034 preferred.",
        experience_requirement={"text": "5 years of experience preferred", "minimum_years": 5},
    )
    result = screen_candidate(candidate, validate_profile(PROFILE))
    assert result["state"] == "needs-clarification"
    assert any("GPA" in question for question in result["questions"])
    assert any("coursework" in question for question in result["questions"])
    assert not any(reason["code"] == "graduation-window-mismatch" for reason in result["reasons"])
    assert not any(
        "graduation restriction" in q or "experience requirement" in q for q in result["questions"]
    )
    # A narrow CS rule is unresolved; a general engineering keyword is not an eligibility claim.
    result = screen_candidate(lead(major_language="Computer Science only"), validate_profile(PROFILE))
    assert result["state"] == "needs-clarification"


def test_city_aliases_default_to_context_optional_and_strict_mode_is_configurable():
    profile = validate_profile(PROFILE)
    assert profile["location_regions"][0]["scope"] == "metro"
    assert profile["location_regions"][0]["allow_city_only"] is True
    assert screen_candidate(lead(location_text="Cambridge"), profile)["state"] == "worth-investigating"
    assert screen_candidate(lead(location_text="Cambridge, UK"), profile)["state"] == "needs-clarification"
    assert not any(
        r["code"] == "location-match"
        for r in screen_candidate(lead(location_text="Cambridge, MA, Canada"), profile)["reasons"]
    )
    profile["location_regions"][0]["allow_city_only"] = False
    assert screen_candidate(lead(location_text="Cambridge"), profile)["state"] == "needs-clarification"
    assert screen_candidate(lead(location_text="Cambridge, MA"), profile)["state"] == "worth-investigating"
    assert "scope" not in PROFILE["location_regions"][0]  # Validation never mutates caller settings.


def test_large_researched_metro_membership_schema_and_validation_agree():
    region = {
        **PROFILE["location_regions"][0],
        "source_urls": ["https://regional.example/member-cities"],
        "match_terms": [f"Synthetic City {i}" for i in range(150)],
    }
    profile = validate_profile({**PROFILE, "location_regions": [region], "major_match_terms": ["STEM"]})
    jsonschema.validate(
        profile, json.loads((SCHEMAS / "workspace-screening-profile.schema.json").read_text())
    )
    with pytest.raises(WorkspaceStateError, match="match_terms"):
        validate_profile({**PROFILE, "location_regions": [{**region, "match_terms": ["x"] * 501}]})
    with pytest.raises(WorkspaceStateError, match="source_urls"):
        validate_profile({**PROFILE, "location_regions": [{**region, "source_urls": ["not a URL"]}]})


@pytest.mark.parametrize(
    "language,expected",
    [
        ("Must currently be in the first year of university education.", "worth-investigating"),
        ("Must currently be in the second year of university education.", "low-relevance"),
        ("Must be in the first or second year of college.", "worth-investigating"),
        ("Must be in the second year of college or higher.", "needs-clarification"),
        ("Must be in the second year of college by the start of the program.", "needs-clarification"),
        ("Sophomore standing is required.", "needs-clarification"),
        (
            "Must be at a minimum in your second year. Our senior engineers provide mentorship.",
            "needs-clarification",
        ),
        ("Must currently be in the 1st year of university education.", "worth-investigating"),
        ("Preferred Qualifications\nSophomore standing.", "worth-investigating"),
        (
            "Our company won an award for the second year. Senior engineers mentor our interns.",
            "worth-investigating",
        ),
    ],
)
def test_defined_year_uses_known_profile_and_ambiguous_standing_stays_question(language, expected):
    finding = screen_candidate(lead(class_year_language=language), validate_profile(PROFILE))
    assert finding["state"] == expected


def test_degree_families_match_broad_requirements_but_not_different_named_discipline():
    profile = validate_profile(
        {**PROFILE, "majors": ["Chemical Engineering"], "major_match_terms": ["Engineering", "STEM"]}
    )
    assert (
        screen_candidate(lead(major_language="Degree in Engineering or Mathematics required."), profile)[
            "state"
        ]
        == "worth-investigating"
    )
    assert (
        screen_candidate(lead(major_language="Degree in Mechanical Engineering only."), profile)["state"]
        == "needs-clarification"
    )
    assert (
        screen_candidate(lead(major_language="Degree in a STEM field required."), profile)["state"]
        == "worth-investigating"
    )
    assert (
        screen_candidate(
            lead(major_language="Degree in Engineering required, except Chemical Engineering."), profile
        )["state"]
        == "needs-clarification"
    )


def test_old_major_noise_and_optional_credentials_do_not_create_blocking_questions():
    row = lead(
        major_language="Preferred Qualifications\nCompetitive grants comprise the majority of compensation.",
        graduation_window_language="Graduating in 2034 preferred.",
        requirements_text="Preferred Qualifications\nGPA 3.0; calculus coursework; 5 years experience.",
        experience_requirement={"minimum_years": 5, "text": "5 years experience preferred"},
    )
    result = screen_candidate(row, validate_profile(PROFILE))
    assert result["state"] == "worth-investigating"
    mandatory = screen_candidate(
        {
            **row,
            "requirements_text": "GPA 3.0 required; calculus coursework required.",
            "work_auth_language": "US citizenship required.",
        },
        validate_profile(PROFILE),
    )
    assert mandatory["state"] == "needs-clarification"
    assert len(mandatory["questions"]) == 3
    mixed = screen_candidate(
        {**row, "requirements_text": "GPA 3.0 required; calculus coursework preferred."},
        validate_profile(PROFILE),
    )
    assert any("GPA" in q for q in mixed["questions"])
    actual_major_rule = screen_candidate(
        {**row, "requirements_text": "Must be majoring in Chemistry."}, validate_profile(PROFILE)
    )
    assert any("major satisfies" in q for q in actual_major_rule["questions"])


@pytest.mark.parametrize(
    "language",
    [
        "Graduating before 2037.",
        "Graduation between 2035 and 2036; program founded in 2030.",
    ],
)
def test_ambiguous_graduation_rules_are_questions(language):
    result = screen_candidate(lead(graduation_window_language=language), validate_profile(PROFILE))
    assert result["state"] == "needs-clarification"


def test_explicit_graduation_mismatch_is_recoverable(tmp_path):
    root, manifest = setup(tmp_path, [lead(), lead(2, graduation_window_language="Graduating in 2034.")])
    public_before = (manifest.parent / "candidates.jsonl").read_bytes()
    screen_collection(root, manifest)
    default = list_explore(root, manifest)
    assert default["collection_count"] == 2
    assert len(default["items"]) == 1
    low = list_explore(root, manifest, screening_state="low-relevance", uncapped=True)
    assert len(low["items"]) == 1
    assert low["items"][0]["screening"]["reasons"][0]["field"] == "graduation_window_language"
    assert (manifest.parent / "candidates.jsonl").read_bytes() == public_before
    assert not (root / ".opdisc/board.json").exists()


def test_full_collection_not_just_queue_is_screened_and_employers_cannot_dominate(tmp_path):
    candidates = [lead(index) for index in range(1, 21)]
    candidates += [
        lead(25, title="Physics Research Program", engagement_type="research", organization="Synthetic Lab"),
        lead(26, title="Physics Scholarship", engagement_type="program", organization="Synthetic Sponsor"),
        lead(27, title="Research Workshop", engagement_type="event", organization="Synthetic Campus"),
        lead(28, title="Product Internship", organization="Synthetic Startup", routing_state="excluded"),
    ]
    root, manifest = setup(tmp_path, candidates)
    assert screen_collection(root, manifest)["updated"] == 24
    page = list_personal_feed(root, manifest)
    assert page["coverage"]["screened"] == 24
    assert page["coverage"]["plausible"] == 24
    assert page["hidden_by_cap"] == 18
    assert len(page["items"]) == 6
    assert {item["screening"]["lane"] for item in page["items"]} >= {
        "research",
        "scholarships",
        "campus-networking",
        "technical-commercial",
    }
    assert list_personal_feed(root, manifest, uncapped=True)["total"] == 24
    assert list_personal_feed(root, manifest, route="excluded")["total"] == 1


def test_screening_carries_forward_and_invalidates_only_material_changes(tmp_path):
    root, manifest = setup(tmp_path, [lead()])
    screen_collection(root, manifest)
    state_path = root / ".opdisc/screening.json"
    original = state_path.read_bytes()
    jsonschema.validate(
        json.loads(original),
        json.loads((SCHEMAS / "workspace-screening-state.schema.json").read_text()),
    )
    assert screen_collection(root, manifest)["carried_forward"] == 1
    assert state_path.read_bytes() == original
    generation(tmp_path, [lead(last_seen="2035-02-01T00:00:00Z", generic_score=99)])
    assert screen_collection(root, manifest)["carried_forward"] == 1
    previous = json.loads(state_path.read_text())["records"][lead()["opportunity_id"]]["screened_at"]
    generation(tmp_path, [lead(graduation_window_language="Graduating in 2034.")])
    assert list_personal_feed(root, manifest)["coverage"]["unsaved_screening"] == 1
    assert screen_collection(root, manifest)["updated"] == 1
    record = json.loads(state_path.read_text())["records"][lead()["opportunity_id"]]
    assert record["screened_at"] >= previous
    assert record["state"] == "low-relevance"
    modified = {**PROFILE, "graduation_month": "2034-06"}
    set_screening_profile(root, modified)
    assert screen_collection(root, manifest)["updated"] == 1


def test_official_check_memory_uses_imported_snapshot_not_collection_timestamp(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    set_screening_profile(root, PROFILE)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    board_path = root / ".opdisc/board.json"
    board_before = board_path.read_bytes()
    rows = [json.loads(line) for line in (manifest.parent / "candidates.jsonl").read_text().splitlines()]
    record = json.loads(board_before)["opportunities"][rows[0]["opportunity_id"]]
    now = datetime.fromisoformat(record["verified_facts"]["checked_at"].replace("Z", "+00:00")) + timedelta(
        days=1
    )
    screen_collection(root, manifest)
    page = list_personal_feed(root, manifest, now=now, uncapped=True)
    item = next(item for item in page["items"] if item["opportunity_id"] == rows[0]["opportunity_id"])
    assert item["research_status"] == "checked-current"
    assert page["coverage"]["officially_checked"] == 4
    rows[0]["requirements_text"] = "A changed Physics requirement"
    new_manifest = generation(tmp_path, rows)
    changed = list_personal_feed(root, new_manifest, now=now, uncapped=True)
    item = next(item for item in changed["items"] if item["opportunity_id"] == rows[0]["opportunity_id"])
    assert item["research_status"] == "recheck-needed"
    assert "source-facts-changed" in item["investigation_reasons"]
    stale = list_personal_feed(root, manifest, now=now + timedelta(days=31), uncapped=True)
    assert "stale-official-check" in stale["items"][0]["investigation_reasons"]
    assert board_path.read_bytes() == board_before


def response(root, manifest, candidate, *, state="worth-investigating", questions=None):
    page = list_personal_feed(root, manifest, uncapped=True)
    return {
        "schema_version": "1.0",
        "generation_id": page["generation_id"],
        "profile_hash": page["profile_hash"],
        "decisions": [
            {
                "opportunity_id": candidate["opportunity_id"],
                "candidate_hash": candidate_fingerprint(candidate),
                "state": state,
                "questions": questions or [],
                "reasons": [
                    {
                        "code": "semantic-fit",
                        "field": "title",
                        "evidence": candidate["title"],
                        "message": "Fictional semantic interpretation of the captured title.",
                    }
                ],
            }
        ],
    }


def test_semantic_screening_is_bounded_evidence_backed_and_not_official_research(tmp_path):
    candidate = lead(engagement_type="unknown")
    root, manifest = setup(tmp_path, [candidate])
    document = response(root, manifest, candidate)
    jsonschema.validate(
        document, json.loads((SCHEMAS / "workspace-screening-response.schema.json").read_text())
    )
    assert apply_screening_response(root, document, manifest)["applied"] == 1
    assert screen_collection(root, manifest)["carried_forward"] == 1
    page = list_personal_feed(root, manifest)
    assert page["items"][0]["screening"]["origin"] == "ai-screening"
    assert page["coverage"]["plausible"] == 1
    assert page["coverage"]["officially_checked"] == 0
    assert not (root / ".opdisc/board.json").exists()
    saved = (root / ".opdisc/screening.json").read_bytes()
    document["decisions"][0]["reasons"][0]["evidence"] = "Invented qualification"
    with pytest.raises(WorkspaceStateError, match="quote"):
        apply_screening_response(root, document, manifest)
    assert (root / ".opdisc/screening.json").read_bytes() == saved


def test_semantic_pass_cannot_clear_unknown_gpa_or_promote_explicit_mismatch(tmp_path):
    candidate = lead(requirements_text="GPA 3.0 required.")
    root, manifest = setup(tmp_path, [candidate])
    with pytest.raises(WorkspaceStateError, match="preserve unresolved"):
        apply_screening_response(root, response(root, manifest, candidate), manifest)
    candidate = lead(graduation_window_language="Graduating in 2034.")
    generation(tmp_path, [candidate])
    with pytest.raises(WorkspaceStateError, match="explicit deterministic"):
        apply_screening_response(root, response(root, manifest, candidate), manifest)
    assert not (root / ".opdisc/screening.json").exists()


def test_cli_and_dashboard_preserve_sections_and_separate_screening_from_checks(tmp_path, capsys):
    root, manifest = setup(tmp_path, [lead(title='<script>alert("synthetic")</script> Physics Intern')])
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(PROFILE))
    assert main(["workspace-profile", str(root), str(profile_path)]) == 0
    assert ".opdisc/screening-profile.json" in capsys.readouterr().out
    assert main(["workspace-screen", str(root), "--manifest", str(manifest)]) == 0
    assert json.loads(capsys.readouterr().out)["updated"] == 1
    assert main(["workspace-screening", str(root), "--manifest", str(manifest), "--limit", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["items"]) == 1
    page = render_dashboard(root, "token", {"view": "explore"}, manifest_path=manifest)
    assert "Personal screening" in page and "officially checked (reported): 0" in page
    assert "&lt;script&gt;" in page and '<script>alert("synthetic")</script>' not in page
    assert "view=feed" not in page
    assert all(label in page for label in ("Home", "Explore", "Waiting", "Dismissed", "History"))


def test_manifest_or_private_state_corruption_fails_before_mutating(tmp_path):
    root, manifest = setup(tmp_path, [lead()])
    screen_collection(root, manifest)
    path = root / ".opdisc/screening.json"
    before = path.read_bytes()
    (manifest.parent / "candidates.jsonl").write_text("{}\n")
    with pytest.raises(WorkspaceStateError, match="hash"):
        screen_collection(root, manifest)
    assert path.read_bytes() == before
    generation(tmp_path, [lead()])
    path.write_text('{"schema_version":"1.0","records":[]}')
    with pytest.raises(WorkspaceStateError, match="object"):
        screen_collection(root, manifest)
    assert path.read_text() == '{"schema_version":"1.0","records":[]}'


def test_profile_cannot_be_written_in_checkout(tmp_path):
    root = make_workspace(tmp_path)
    (root.parent / ".git").mkdir()
    with pytest.raises(WorkspaceStateError, match="Git checkout"):
        set_screening_profile(root, PROFILE)
    assert not (root / ".opdisc/screening-profile.json").exists()


def test_profile_schema_and_unknown_credentials(tmp_path):
    profile = validate_profile(PROFILE)
    jsonschema.validate(
        profile, json.loads((SCHEMAS / "workspace-screening-profile.schema.json").read_text())
    )
    assert profile["max_required_experience_years"] is None
    with pytest.raises(WorkspaceStateError, match="graduation_month"):
        validate_profile({**PROFILE, "graduation_month": "2036-13"})
    with pytest.raises(WorkspaceStateError, match="unknown fields"):
        validate_profile({**PROFILE, "unhandled_credential": "not silently ignored"})
    for field in ("student_status", "degree", "unit_based_standing"):
        with pytest.raises(WorkspaceStateError, match="invalid"):
            validate_profile({**PROFILE, field: []})


def test_user_decisions_stay_out_of_suggestions_but_remain_recoverable(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    set_screening_profile(root, PROFILE)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    path = root / ".opdisc/board.json"
    board = json.loads(path.read_text())
    record = next(iter(board["opportunities"].values()))
    identifier = record["opportunity_id"]
    record["user_state"]["status"] = "done"
    path.write_text(json.dumps(board))
    saved = path.read_bytes()
    suggested = list_personal_feed(root, manifest, uncapped=True)
    assert identifier not in {item["opportunity_id"] for item in suggested["items"]}
    all_items = list_personal_feed(root, manifest, state_filter="all", uncapped=True)
    assert identifier in {item["opportunity_id"] for item in all_items["items"]}
    assert path.read_bytes() == saved


def test_new_and_changed_unreviewed_leads_precede_unchanged_backlog(tmp_path):
    now = datetime(2035, 4, 15, tzinfo=UTC)
    candidates = [
        lead(1, first_seen="2035-01-01T00:00:00Z", last_changed="2035-01-01T00:00:00Z"),
        lead(2, first_seen="2035-04-14T00:00:00Z", last_changed="2035-04-14T00:00:00Z"),
        lead(3, first_seen="2035-01-01T00:00:00Z", last_changed="2035-04-14T00:00:00Z"),
    ]
    root, manifest = setup(tmp_path, candidates)
    screen_collection(root, manifest)
    page = list_personal_feed(root, manifest, uncapped=True, now=now)
    assert [item["opportunity_id"] for item in page["items"]] == [
        candidates[index]["opportunity_id"] for index in (2, 1, 0)
    ]
    assert "new-opportunity" not in page["items"][-1]["investigation_reasons"]


@pytest.mark.parametrize(
    ("mode", "candidate", "expected"),
    [
        (
            "early-opportunities",
            lead(title="Business Discovery Program", engagement_type="program"),
            "preferred",
        ),
        ("early-opportunities", lead(title="Freshman Hardware Internship"), "preferred"),
        (
            "early-opportunities",
            lead(class_year_language="First-year and sophomore students welcome."),
            "preferred",
        ),
        (
            "early-opportunities",
            lead(class_year_language="Freshmen, sophomores, juniors and seniors welcome."),
            "related",
        ),
        ("early-opportunities", lead(class_year_language="Junior and senior students required."), "related"),
        ("standard-internships", lead(), "preferred"),
        ("standard-internships", lead(title="Sophomore Physics Internship"), "related"),
        (
            "standard-internships",
            lead(title="Junior Year Internship", engagement_type="unknown"),
            "preferred",
        ),
        (
            "new-grad",
            lead(
                title="New Graduate Hardware Engineer", engagement_type="full-time", career_stage="new-grad"
            ),
            "preferred",
        ),
        (
            "new-grad",
            lead(title="Entry Level Engineer", engagement_type="unknown", career_stage="unknown"),
            "preferred",
        ),
        ("new-grad", lead(title="New Graduate Internship"), "other"),
        ("new-grad", lead(title="New Graduate Career Fair", engagement_type="event"), "related"),
        ("new-grad", lead(title="Graduate Discovery Program", engagement_type="program"), "related"),
        ("new-grad", lead(title="Entry Level Contractor", engagement_type="contract"), "related"),
    ],
)
def test_configurable_opportunity_stage_prioritizes_source_cues(mode, candidate, expected):
    profile = validate_profile({**PROFILE, "opportunity_focus": mode})
    jsonschema.validate(
        profile, json.loads((SCHEMAS / "workspace-screening-profile.schema.json").read_text())
    )
    finding = screen_candidate(candidate, profile)
    assert finding["focus"]["match"] == expected
    assert finding["focus"]["mode"] == mode


@pytest.mark.parametrize(
    "title", ["Consumer Insights Analyst", "Drug Discovery Scientist", "Discovery Program Manager"]
)
def test_early_mode_does_not_mistake_ordinary_jobs_for_exploratory_programs(title):
    candidate = lead(
        title=title, engagement_type="full-time", career_stage="entry-level", class_year_language=None
    )
    finding = screen_candidate(
        candidate, validate_profile({**PROFILE, "opportunity_focus": "early-opportunities"})
    )
    assert finding["focus"]["match"] != "preferred"


def test_early_programs_with_unresolved_fit_precede_standard_roles_across_categories(tmp_path):
    programs = [
        lead(
            index,
            title="Business Exploration Workshop",
            engagement_type="event",
            organization=f"Synthetic Sponsor {index}",
            requirements_text="Open to undergraduate students; GPA of 3.0 required.",
            major_language=None,
            graduation_window_language=None,
        )
        for index in range(10, 14)
    ]
    ordinary = lead(1, first_seen="2035-04-14T00:00:00Z", last_changed="2035-04-14T00:00:00Z")
    root, manifest = setup(tmp_path, [ordinary, *programs])
    set_screening_profile(root, {**PROFILE, "opportunity_focus": "early-opportunities"})
    screen_collection(root, manifest)
    page = list_personal_feed(root, manifest, limit=4, now=datetime(2035, 4, 15, tzinfo=UTC))
    assert {item["opportunity_id"] for item in page["items"]} == {p["opportunity_id"] for p in programs}
    assert all(item["screening"]["state"] == "needs-clarification" for item in page["items"])
    assert all(any("GPA" in q for q in item["screening"]["questions"]) for item in page["items"])
    assert not (root / ".opdisc/board.json").exists()


def test_early_program_cap_exception_preserves_programs_but_caps_ordinary_roles(tmp_path):
    programs = [
        lead(index, title=f"Exploratory Program {index}", engagement_type="program")
        for index in range(10, 15)
    ]
    ordinary = [lead(index) for index in range(1, 6)]
    root, manifest = setup(tmp_path, [*ordinary, *programs])
    set_screening_profile(root, {**PROFILE, "opportunity_focus": "early-opportunities"})
    screen_collection(root, manifest)
    page = list_personal_feed(root, manifest)
    assert len(page["items"]) == 7
    assert page["cap_exempt_programs"] == 5
    assert page["hidden_by_cap"] == 3
    assert {p["opportunity_id"] for p in programs} <= {item["opportunity_id"] for item in page["items"]}
    assert all(item["screening"]["focus"]["match"] == "preferred" for item in page["items"][:5])


def test_focus_does_not_override_known_mismatch_and_mode_changes_preserve_identity(tmp_path):
    mismatch = lead(
        2,
        title="Exploratory Program",
        engagement_type="program",
        graduation_window_language="Graduating in 2034.",
    )
    ordinary = lead()
    root, manifest = setup(tmp_path, [ordinary, mismatch])
    before = (manifest.parent / "candidates.jsonl").read_bytes()
    set_screening_profile(root, {**PROFILE, "opportunity_focus": "early-opportunities"})
    screen_collection(root, manifest)
    low = list_personal_feed(root, manifest, state_filter="low-relevance")
    assert low["items"][0]["opportunity_id"] == mismatch["opportunity_id"]
    assert low["items"][0]["screening"]["focus"]["match"] == "preferred"
    set_screening_profile(root, {**PROFILE, "opportunity_focus": "standard-internships"})
    assert list_personal_feed(root, manifest)["coverage"]["unsaved_screening"] == 2
    assert screen_collection(root, manifest)["updated"] == 2
    assert list_personal_feed(root, manifest)["items"][0]["opportunity_id"] == ordinary["opportunity_id"]
    assert (manifest.parent / "candidates.jsonl").read_bytes() == before
    assert not (root / ".opdisc/board.json").exists()
    with pytest.raises(WorkspaceStateError, match="opportunity_focus"):
        validate_profile({**PROFILE, "opportunity_focus": "automatic"})


@pytest.mark.parametrize(
    ("title", "engagement", "language", "expected"),
    [
        ("Laboratory Scientist", "research", "Our company won an award for the second year.", "other"),
        ("Head of Technical Training", "program", "Spend your first year teaching our employees.", "other"),
        ("Career Fair", "event", "Training is provided during your first year of employment.", "related"),
        ("Senior Trading Specialist", "unknown", "Receive more vacation after your first year.", "other"),
        ("Legal Intern", "internship", "Current law school students must be in their first year.", "related"),
        (
            "Engineering Intern",
            "internship",
            "Undergraduate students in their second year may apply.",
            "preferred",
        ),
        ("Engineering Intern", "internship", "Sophomore standing or higher is required.", "related"),
        (
            "Engineering Intern",
            "internship",
            "Completed at least sophomore year before the program.",
            "related",
        ),
    ],
)
def test_early_focus_requires_academic_year_and_dedicated_early_cue(title, engagement, language, expected):
    row = lead(
        title=title, engagement_type=engagement, class_year_language=language, requirements_text=language
    )
    finding = screen_candidate(row, validate_profile({**PROFILE, "opportunity_focus": "early-opportunities"}))
    assert finding["focus"]["match"] == expected


def test_generic_program_label_does_not_make_discovery_job_an_exploratory_program():
    row = lead(
        title="Software Engineer, Discovery",
        engagement_type="program",
        career_stage="unknown",
        class_year_language=None,
        requirements_text="Build our discovery service. Five years of experience required.",
    )
    finding = screen_candidate(row, validate_profile({**PROFILE, "opportunity_focus": "early-opportunities"}))
    assert finding["focus"]["match"] == "other"
    assert not finding["focus"]["program"]


def test_old_experienced_label_on_internship_is_a_question_and_true_mismatch_stays_low():
    row = lead(title="Product Manager Intern", career_stage="experienced")
    finding = screen_candidate(row, validate_profile(PROFILE))
    assert finding["state"] == "needs-clarification"
    assert any("role level" in q for q in finding["questions"])
    finding = screen_candidate(
        {
            **row,
            "required_degree": "doctorate",
            "requirements_text": "Must currently be pursuing a doctorate degree.",
        },
        validate_profile(PROFILE),
    )
    assert finding["state"] == "low-relevance"


def test_old_screening_version_refresh_preserves_custom_fields(tmp_path):
    root, manifest = setup(tmp_path, [lead()])
    screen_collection(root, manifest)
    path = root / ".opdisc/screening.json"
    state = json.loads(path.read_text())
    record = next(iter(state["records"].values()))
    record["screening_version"] = "2"
    record.pop("focus")
    record["custom"] = {"user_note": "Preserve this correction."}
    path.write_text(json.dumps(state))
    assert screen_collection(root, manifest)["updated"] == 1
    refreshed = next(iter(json.loads(path.read_text())["records"].values()))
    assert refreshed["custom"] == record["custom"]
    assert refreshed["screening_version"] == SCREENING_VERSION


def test_configurable_region_limit_filters_explicit_mismatch_but_not_incomplete_geography():
    profile = validate_profile({**PROFILE, "location_policy": "local-jobs-funded-programs"})
    assert screen_candidate(lead(location_text="Burlington, VT"), profile)["state"] == "low-relevance"
    assert screen_candidate(lead(location_text="Singapore"), profile)["state"] == "low-relevance"
    assert screen_candidate(lead(location_text="London, UK"), profile)["state"] == "low-relevance"
    assert (
        screen_candidate(lead(location_text="Cambridge, MA; Burlington, VT"), profile)["state"]
        == "worth-investigating"
    )
    for location in (
        "Unknown City, MA",
        "Burlington, VT; Unknown City, MA",
        "Burlington, VT, Unknown City, MA",
    ):
        assert screen_candidate(lead(location_text=location), profile)["state"] == "needs-clarification"
    assert screen_candidate(lead(location_text="Burlington"), profile)["state"] == "worth-investigating"
    with pytest.raises(WorkspaceStateError, match="location_policy"):
        validate_profile({**PROFILE, "location_policy": "made-up"})


@pytest.mark.parametrize(
    "travel,duration,expected",
    [
        ("Travel, meals and housing are covered.", "A two-day exploratory program.", "worth-investigating"),
        ("Airfare is reimbursed.", "A one-day event.", "worth-investigating"),
        ("Travel is provided.", "A week-long intensive experience.", "worth-investigating"),
        ("Housing is provided.", "A two-day program.", "needs-clarification"),
        ("Travel may be covered.", "A two-day program.", "needs-clarification"),
        ("Travel is not covered.", "A two-day program.", "low-relevance"),
        ("Travel is covered.", "Apply two weeks before the program.", "needs-clarification"),
        ("Travel is covered.", "A six-month program.", "low-relevance"),
        ("Travel is covered. Travel is not reimbursed.", "A two-day program.", "needs-clarification"),
    ],
)
def test_short_program_travel_exception_uses_source_evidence(travel, duration, expected):
    row = lead(
        title="Physics Discovery Program",
        engagement_type="program",
        location_text="Burlington, VT",
        requirements_text=duration,
        relocation_text=travel,
    )
    finding = screen_candidate(
        row, validate_profile({**PROFILE, "location_policy": "local-jobs-funded-programs"})
    )
    assert finding["state"] == expected
    if expected == "worth-investigating":
        reason = next(r for r in finding["reasons"] if r["code"] == "funded-program-travel")
        assert reason["field"] == "relocation_text" and reason["evidence"] in travel
    assert (
        screen_candidate(row, validate_profile({**PROFILE, "location_policy": "local-only"}))["state"]
        == "low-relevance"
    )


def test_travel_exception_supports_event_dates_but_never_internship_relocation():
    profile = validate_profile({**PROFILE, "location_policy": "local-jobs-funded-programs"})
    row = lead(
        title="Physics Discovery Program",
        engagement_type="program",
        location_text="Burlington, VT",
        relocation_text="Travel is covered.",
        event_start_date="2035-06-01",
        event_end_date="2035-06-14",
    )
    assert screen_candidate(row, profile)["state"] == "worth-investigating"
    assert (
        screen_candidate({**row, "event_end_date": "2035-06-15"}, profile)["state"] == "needs-clarification"
    )
    row = {**row, "title": "Physics Internship", "engagement_type": "internship"}
    assert screen_candidate(row, profile)["state"] == "low-relevance"


def test_legacy_internship_label_does_not_block_explicit_short_funded_program():
    profile = validate_profile({**PROFILE, "location_policy": "local-jobs-funded-programs"})
    row = lead(
        title="Physics Spring Insight Programme",
        engagement_type="internship",
        location_text="UK",
        requirements_text="A one week work shadowing experience.",
        relocation_text="Travel is covered.",
    )
    assert screen_candidate(row, profile)["state"] == "worth-investigating"
    row["location_text"] = "Unrecognized City"
    assert screen_candidate(row, profile)["state"] == "worth-investigating"


@pytest.mark.parametrize(
    "title,engagement,stage",
    [
        ("Product Designer, International", "internship", "unknown"),
        ("Internal Systems Engineer", "internship", "unknown"),
        ("Graduate Software Engineer", "internship", "entry-level"),
        ("Discovery Programme Specialist", "program", "unknown"),
        ("Head of Discovery Program", "full-time", "unknown"),
        ("Physics Scientist", "research", "unknown"),
        ("Test Engineer", "fellowship", "student"),
    ],
)
def test_legacy_type_labels_and_body_references_do_not_create_student_focus(title, engagement, stage):
    row = lead(
        title=title,
        engagement_type=engagement,
        career_stage=stage,
        class_year_language=None,
        requirements_text="Work with our research assistant team.",
    )
    finding = screen_candidate(row, validate_profile({**PROFILE, "opportunity_focus": "early-opportunities"}))
    assert finding["focus"]["match"] == "other"
    if engagement == "internship":
        assert any("internship label conflicts" in q for q in finding["questions"])
