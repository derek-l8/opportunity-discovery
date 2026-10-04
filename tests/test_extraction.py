"""Synthetic late-section extraction and source-language boundary regressions."""

import json

import pytest

from opportunity_discovery.adapters.base import bounded_excerpt, run_source
from opportunity_discovery.adapters.smartrecruiters import SmartRecruitersAdapter
from opportunity_discovery.export import export_all
from opportunity_discovery.extraction import extract_description
from opportunity_discovery.models import RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
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
    payload["jobs"][0]["content"] = payload["jobs"][0]["content"].replace("August 2036", "August 2037")
    fetcher.routes["https://boards-api.greenhouse.io/"] = (200, json.dumps(payload), {})
    Pipeline(conn, engine_config, "extract-2", RunSummary("extract-2", "now")).process_source(spec, fetcher)
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert row["opportunity_id"] == identifier
    assert "2037" in row["graduation_window_language"]
    assert "requirements-changed" in row["last_change_events_json"]
    assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
    conn.close()
