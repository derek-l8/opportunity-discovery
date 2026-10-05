"""Synthetic late-section extraction and source-language boundary regressions."""

import json

import pytest

from opportunity_discovery.adapters.base import bounded_excerpt, run_source
from opportunity_discovery.adapters.smartrecruiters import SmartRecruitersAdapter
from opportunity_discovery.export import export_all
from opportunity_discovery.extraction import extract_description
from opportunity_discovery.models import RawOpportunity, RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from opportunity_discovery.scoring import extract_explicit_language
from tests.helpers import MockFetcher, load_fixture, make_db, source

PAYLOADS = json.loads(load_fixture("qualifications_payloads.json"))


def record(adapter):
    payload = PAYLOADS[adapter]
    if adapter == "smartrecruiters":
        return SmartRecruitersAdapter()._record(payload, "synthetic", 80)
    base = {
        "greenhouse": "https://boards-api.greenhouse.io/",
        "lever": "https://api.lever.co/",
        "ashby": "https://api.ashbyhq.com/",
    }[adapter]
    fetcher = MockFetcher({base: (200, json.dumps(payload), {})})
    result = run_source(
        source(adapter=adapter, endpoint_config={"board": "synthetic"}), fetcher, excerpt_chars=80
    )
    assert result.ok
    assert len(result.records) == 1
    return result.records[0]


@pytest.mark.parametrize("adapter", list(PAYLOADS))
def test_full_qualifications_extracted_before_short_excerpt(adapter):
    raw = record(adapter)
    assert len(raw.description_excerpt) <= 80
    assert "fictional company introduction" not in raw.description_excerpt.lower()
    assert raw.class_year_language and "undergraduate" in raw.class_year_language
    assert "2035" in raw.graduation_window_language and "2036" in raw.graduation_window_language
    assert "Physics" in raw.major_language
    assert raw.location_text == "Boston, MA"
    assert raw.deadline == "2035-02-15"
    assert "$28" in raw.compensation_text
    assert "&lt;" not in raw.description_excerpt and "<li>" not in raw.description_excerpt


def test_lever_separate_lists_preserve_required_vs_preferred_experience():
    raw = record("lever")
    assert "2 years" in raw.experience_requirement_text
    assert "5 years" not in raw.experience_requirement_text
    assert "Preferred Qualifications" in raw.requirements_text


def test_required_degree_at_end_survives_bounded_requirements():
    text = "<h2>Basic Qualifications</h2>" + "".join(
        f"<li>Relevant laboratory experience with fictional apparatus {index}.</li>" for index in range(120)
    )
    text += "<li>Doctorate is required.</li>"
    facts = extract_description(text)
    assert len(facts["requirements_text"]) <= 2400
    assert facts["required_degree"] == "doctorate"
    assert "Doctorate" not in facts["requirements_text"]


def test_requirement_sections_precede_intro_and_preference_context_ends():
    text = "<p>Our founding team has a doctorate and 20 years of experience.</p>"
    text += "<h2>Required Qualifications</h2><p>Undergraduate Physics major required.</p>"
    text += "<h2>Desired Qualifications</h2><p>5 years of experience.</p>"
    text += "<h2>Compensation</h2><p>Salary: $28 per hour.</p>"
    facts = extract_description(text)
    assert facts["requirements_text"].startswith("Required Qualifications")
    assert "5 years" not in (facts["experience_requirement_text"] or "")
    assert "20 years" not in (facts["experience_requirement_text"] or "")
    assert facts["required_degree"] != "doctorate"
    assert "Desired Qualifications" not in facts["compensation_text"]


@pytest.mark.parametrize(
    "text",
    [
        "Application deadline: February 15.",
        "Applications open February 15, 2035.",
        "Our company was founded in 2035.",
        "Apply by February 30, 2035.",
        "Application deadline: 2035-02-15. Apply by 2035-03-15.",
    ],
)
def test_ambiguous_or_unstated_deadline_remains_unknown(text):
    assert extract_description(text)["deadline"] is None


def test_nested_entities_and_scripts_are_removed():
    assert (
        bounded_excerpt("&amp;lt;p&amp;gt;A &amp;amp; B&amp;lt;/p&amp;gt;<script>bad()</script>") == "A & B"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Our majority investment supports computer science research.",
        "Lead major technical initiatives in electrical engineering.",
        "We work across science, engineering and other major markets.",
        "Our founders earned a degree in Physics.",
        "Our founders earned a degree in Physics.\nRequired Qualifications\n"
        "Must be enrolled as an undergraduate.",
    ],
)
def test_company_mentions_are_not_major_requirements(text):
    facts = extract_description(text)
    assert facts["major_language"] is None
    raw = RawOpportunity(title="Intern", canonical_url="https://synthetic.example/1", **facts)
    assert extract_explicit_language(raw)["major_language"] is None


@pytest.mark.parametrize(
    "text",
    [
        "Required Qualifications\nBachelor's degree in Physics, Engineering or a related STEM field.",
        "Undergraduate Physics major required.",
        "Must be majoring in Chemistry or Biology.",
        "Fields of study: Mathematics or Physics.",
        "Majors: Physics or Mathematics.",
    ],
)
def test_academic_field_clauses_preserve_complete_source_statement(text):
    assert extract_description(text)["major_language"] == text


def test_pipeline_exports_extracted_facts_and_identity_survives_requirements_change(tmp_path, engine_config):
    spec = source()
    conn = make_db(tmp_path)
    sync_sources_to_db(conn, [spec])
    payload = json.loads(json.dumps(PAYLOADS["greenhouse"]))
    engine_config.export.excerpt_chars = 80
    fetcher = MockFetcher({"https://boards-api.greenhouse.io/": (200, json.dumps(payload), {})})
    Pipeline(conn, engine_config, "extract-1", RunSummary("extract-1", "now")).process_source(spec, fetcher)
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert "2035" in row["graduation_window_language"]
    assert row["experience_min_years"] == 2
    assert row["deadline"] == "2035-02-15"
    identifier = row["opportunity_id"]
    export_all(conn, engine_config, "extract-1")
    candidate = json.loads((engine_config.paths.output_dir / "candidates.jsonl").read_text().splitlines()[0])
    assert candidate["opportunity_id"] == identifier
    assert candidate["stated_deadline"] == "2035-02-15"
    assert candidate["graduation_window_language"] == row["graduation_window_language"]
    assert candidate["experience_requirement"]["minimum_years"] == 2
    assert candidate["source_constraints"] == json.loads(row["source_constraints_json"])
    assert any(rule["kind"] == "graduation" for rule in candidate["source_constraints"])
    payload["jobs"][0]["content"] = payload["jobs"][0]["content"].replace("August 2036", "August 2037")
    fetcher.routes["https://boards-api.greenhouse.io/"] = (200, json.dumps(payload), {})
    Pipeline(conn, engine_config, "extract-2", RunSummary("extract-2", "now")).process_source(spec, fetcher)
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert row["opportunity_id"] == identifier
    assert "2037" in row["graduation_window_language"]
    assert "requirements-changed" in row["last_change_events_json"]
    assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
    conn.close()


def test_constraint_change_beyond_excerpts_keeps_identity_and_failure_preserves_state(
    tmp_path, engine_config
):
    spec = source()
    conn = make_db(tmp_path)
    sync_sources_to_db(conn, [spec])
    payload = json.loads(json.dumps(PAYLOADS["greenhouse"]))
    prefix = "<h3>Required Qualifications</h3>" + "".join(
        f"<p>Must communicate effectively on task {i}.</p>" for i in range(120)
    )
    payload["jobs"][0]["content"] = prefix + "<p>Graduating in spring 2035.</p>"
    endpoint = "https://boards-api.greenhouse.io/"
    fetcher = MockFetcher({endpoint: (200, json.dumps(payload), {})})
    Pipeline(conn, engine_config, "constraints-1", RunSummary("constraints-1", "now")).process_source(
        spec, fetcher
    )
    before = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    payload["jobs"][0]["content"] = prefix + "<p>Graduating in spring 2036.</p>"
    fetcher.routes[endpoint] = (200, json.dumps(payload), {})
    Pipeline(conn, engine_config, "constraints-2", RunSummary("constraints-2", "now")).process_source(
        spec, fetcher
    )
    after = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    assert before["opportunity_id"] == after["opportunity_id"]
    assert before["description_excerpt"] == after["description_excerpt"]
    assert before["requirements_text"] == after["requirements_text"]
    assert before["source_constraints_json"] != after["source_constraints_json"]
    assert "requirements-changed" in after["last_change_events_json"]
    fetcher.routes[endpoint] = (500, "failure", {})
    Pipeline(conn, engine_config, "constraints-3", RunSummary("constraints-3", "now")).process_source(
        spec, fetcher
    )
    failed = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    assert failed["source_constraints_json"] == after["source_constraints_json"]
    assert failed["active"] == after["active"]
    conn.close()


def test_successful_full_refresh_clears_removed_constraints_but_missing_text_preserves_them(
    tmp_path, engine_config
):
    spec = source()
    conn = make_db(tmp_path)
    sync_sources_to_db(conn, [spec])
    payload = json.loads(json.dumps(PAYLOADS["greenhouse"]))
    endpoint = "https://boards-api.greenhouse.io/"
    fetcher = MockFetcher({endpoint: (200, json.dumps(payload), {})})
    Pipeline(conn, engine_config, "clear-1", RunSummary("clear-1", "now")).process_source(spec, fetcher)
    before = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    assert before["graduation_window_language"] and before["experience_min_years"] == 2
    payload["jobs"][0]["content"] = None
    fetcher.routes[endpoint] = (200, json.dumps(payload), {})
    Pipeline(conn, engine_config, "clear-2", RunSummary("clear-2", "now")).process_source(spec, fetcher)
    partial = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    assert partial["source_constraints_json"] == before["source_constraints_json"]
    assert partial["graduation_window_language"] == before["graduation_window_language"]
    payload["jobs"][0]["content"] = "<h3>Qualifications</h3><p>Interest in technology.</p>"
    fetcher.routes[endpoint] = (200, json.dumps(payload), {})
    Pipeline(conn, engine_config, "clear-3", RunSummary("clear-3", "now")).process_source(spec, fetcher)
    after = dict(conn.execute("SELECT * FROM opportunities").fetchone())
    assert after["opportunity_id"] == before["opportunity_id"]
    assert json.loads(after["source_constraints_json"]) == []
    for field in (
        "graduation_window_language",
        "class_year_language",
        "major_language",
        "work_auth_language",
        "experience_requirement_text",
        "experience_min_years",
        "deadline",
    ):
        assert after[field] is None
    assert after["required_degree"] == "unknown"
    assert "requirements-changed" in after["last_change_events_json"]
    conn.close()
