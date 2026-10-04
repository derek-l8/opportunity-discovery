import json
from pathlib import Path

import pytest

from opportunity_discovery import constants as c
from opportunity_discovery.config import load_config
from opportunity_discovery.export import export_all
from opportunity_discovery.models import RawOpportunity, RunSummary
from opportunity_discovery.pipeline import Pipeline
from opportunity_discovery.registry import sync_sources_to_db
from opportunity_discovery.routing import normalize_routing_fields, route_profiles
from tests.helpers import MockFetcher, make_db, source

DEMO_FIXTURE = Path(__file__).parent / "fixtures" / "demo" / "phase1-opportunities.json"


def candidate(title: str, description: str = "", employment_type: str | None = None):
    raw = RawOpportunity(
        title=title,
        canonical_url="https://example.test/opportunity",
        description_excerpt=description,
        employment_type=employment_type,
    )
    fields = normalize_routing_fields(raw)
    return fields, route_profiles(fields)


def test_student_profile_includes_student_lanes_and_excludes_full_time():
    _, internship = candidate("Firmware Intern")
    assert internship[c.PROFILE_STUDENT].state == c.ROUTE_INCLUDED

    _, full_time = candidate("New Graduate Engineer — Full-Time")
    assert full_time[c.PROFILE_STUDENT].state == c.ROUTE_EXCLUDED

    fields, _ = candidate("Senior Hardware Engineer — Full-Time")
    assert fields["career_stage"] == c.CAREER_EXPERIENCED

    fields, routes = candidate("Director, Site Reliability Engineering")
    assert fields["career_stage"] == c.CAREER_EXPERIENCED
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_EXCLUDED

    _, internship = candidate("Firmware Intern", "Collaborate with the director of engineering.")
    assert internship[c.PROFILE_STUDENT].state == c.ROUTE_INCLUDED


def test_student_profile_excludes_required_graduate_degree_not_broad_degree_list():
    fields, routes = candidate("Research Internship", "Master's degree required. PhD preferred.")
    assert fields["required_degree"] == c.DEGREE_MASTERS
    assert fields["preferred_degree"] == c.DEGREE_DOCTORATE
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_EXCLUDED

    fields, routes = candidate(
        "Hardware Internship", "Open to bachelor's, master's, and doctoral candidates."
    )
    assert fields["required_degree"] == c.UNKNOWN
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_INCLUDED


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Product Manager Intern", "Currently pursuing an undergraduate degree."),
        ("Product Design Intern", "Work with your intern manager on a design project."),
        ("Platform Engineer Intern", "A senior engineer will mentor your project."),
    ],
)
def test_internship_role_is_not_experienced_because_of_manager_or_mentor(title, description):
    fields, routes = candidate(title, description)
    assert fields["career_stage"] == c.CAREER_STUDENT
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_INCLUDED


def test_colleague_seniority_does_not_define_ambiguous_role_stage():
    fields, routes = candidate("Hardware Technician", "Collaborate with a senior engineer and a manager.")
    assert fields["career_stage"] == c.UNKNOWN
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_RESEARCH


def test_phd_in_intern_title_requires_research_without_inventing_degree_requirement():
    fields, routes = candidate("PhD Quantitative Researcher Intern")
    assert fields["required_degree"] == c.UNKNOWN
    assert fields["graduate_degree_title_signal"] is True
    assert routes[c.PROFILE_STUDENT].state == c.ROUTE_RESEARCH
    assert routes[c.PROFILE_STUDENT].confidence == c.CONFIDENCE_LOW
    assert "profile:graduate-degree-title-unverified" in routes[c.PROFILE_STUDENT].reason_codes
    assert routes[c.PROFILE_NEW_GRAD].state == c.ROUTE_EXCLUDED
    assert routes[c.PROFILE_ALL].state == c.ROUTE_INCLUDED


def test_new_grad_profile_accepts_up_to_four_and_excludes_five_plus():
    fields, routes = candidate(
        "New Graduate Software Engineer — Full-Time", "Up to 4 years of relevant experience."
    )
    assert fields["experience_max_years"] == 4
    assert routes[c.PROFILE_NEW_GRAD].state == c.ROUTE_INCLUDED

    fields, routes = candidate(
        "Senior Software Engineer — Full-Time", "Requires at least 5 years of experience."
    )
    assert fields["experience_min_years"] == 5
    assert routes[c.PROFILE_NEW_GRAD].state == c.ROUTE_EXCLUDED


def test_new_grad_excludes_internships_and_ambiguous_leads_are_researched():
    _, internship = candidate("Software Engineering Intern")
    assert internship[c.PROFILE_NEW_GRAD].state == c.ROUTE_EXCLUDED

    _, ambiguous = candidate("Robotics Technical Opportunity")
    assert ambiguous[c.PROFILE_STUDENT].state == c.ROUTE_RESEARCH
    assert ambiguous[c.PROFILE_NEW_GRAD].state == c.ROUTE_RESEARCH
    assert ambiguous[c.PROFILE_STUDENT].confidence == c.CONFIDENCE_LOW


def test_all_opportunities_includes_every_normalized_case():
    for title, description in (
        ("Software Intern", ""),
        ("Principal Engineer — Full-Time", "10+ years of experience"),
        ("Unclassified Technical Opportunity", ""),
    ):
        _, routes = candidate(title, description)
        assert routes[c.PROFILE_ALL].state == c.ROUTE_INCLUDED


def test_active_profile_configuration_is_validated(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[routing]\nactive_profile = "not-a-profile"\n', encoding="utf-8")
    _, errors = load_config(config_path=config_path, base_dir=tmp_path)
    assert any("routing.active_profile must be one of" in error for error in errors)


@pytest.mark.parametrize(
    ("profile", "expected_routes"),
    [
        (
            c.PROFILE_STUDENT,
            {
                "Embedded Firmware Intern": c.ROUTE_INCLUDED,
                "Senior Hardware Engineer — Full-Time": c.ROUTE_EXCLUDED,
                "New Graduate Software Engineer — Full-Time": c.ROUTE_EXCLUDED,
                "Machine Learning Research Internship": c.ROUTE_EXCLUDED,
                "Robotics Technical Opportunity": c.ROUTE_RESEARCH,
                "Student Engineering Recruiting Event": c.ROUTE_INCLUDED,
                "Embedded Firmware Intern Summer 2027": c.ROUTE_INCLUDED,
                "Embedded Firmware Intern Summer": c.ROUTE_INCLUDED,
            },
        ),
        (
            c.PROFILE_NEW_GRAD,
            {
                "Embedded Firmware Intern": c.ROUTE_EXCLUDED,
                "Senior Hardware Engineer — Full-Time": c.ROUTE_EXCLUDED,
                "New Graduate Software Engineer — Full-Time": c.ROUTE_INCLUDED,
                "Machine Learning Research Internship": c.ROUTE_EXCLUDED,
                "Robotics Technical Opportunity": c.ROUTE_RESEARCH,
                "Student Engineering Recruiting Event": c.ROUTE_EXCLUDED,
                "Embedded Firmware Intern Summer 2027": c.ROUTE_EXCLUDED,
                "Embedded Firmware Intern Summer": c.ROUTE_EXCLUDED,
            },
        ),
        (
            c.PROFILE_ALL,
            {
                "Embedded Firmware Intern": c.ROUTE_INCLUDED,
                "Senior Hardware Engineer — Full-Time": c.ROUTE_INCLUDED,
                "New Graduate Software Engineer — Full-Time": c.ROUTE_INCLUDED,
                "Machine Learning Research Internship": c.ROUTE_INCLUDED,
                "Robotics Technical Opportunity": c.ROUTE_INCLUDED,
                "Student Engineering Recruiting Event": c.ROUTE_INCLUDED,
                "Embedded Firmware Intern Summer 2027": c.ROUTE_INCLUDED,
                "Embedded Firmware Intern Summer": c.ROUTE_INCLUDED,
            },
        ),
    ],
)
def test_synthetic_demo_routes_every_profile_and_retains_all_records(
    engine_config, tmp_path, profile, expected_routes
):
    engine_config.routing.active_profile = profile
    conn = make_db(tmp_path)
    fetcher = MockFetcher()
    feed_url = "https://synthetic.example/feed.json"
    fetcher.add(feed_url, 200, DEMO_FIXTURE.read_text(encoding="utf-8"))
    spec = source(
        source_id="synthetic-phase1",
        organization="Synthetic Opportunities",
        adapter="jsonfeed",
        endpoint_config={"url": feed_url, "records_path": "jobs"},
    )
    sync_sources_to_db(conn, [spec])
    summary = RunSummary(run_id=f"run-{profile}", started_at="2026-09-05T00:00:00Z")
    Pipeline(conn, engine_config, summary.run_id, summary).process_source(spec, fetcher)

    rows = {row["title"]: row for row in conn.execute("SELECT * FROM opportunities")}
    assert len(rows) == 8  # exact URL duplicate collapsed; possible duplicates remain separate
    assert {title: row["routing_state"] for title, row in rows.items()} == expected_routes
    assert all(row["active_profile"] == profile for row in rows.values())
    assert all(set(json.loads(row["profile_routes_json"])) == set(c.ALL_PROFILES) for row in rows.values())
    check = conn.execute("SELECT records_seen, new_records FROM source_checks").fetchone()
    assert (check["records_seen"], check["new_records"]) == (9, 8)

    export_all(conn, engine_config, summary.run_id)
    exported = [
        json.loads(line)
        for line in (engine_config.paths.output_dir / "candidates.jsonl").read_text().splitlines()
    ]
    assert len(exported) == 8
    assert all(item["active_profile"] == profile for item in exported)
    possible = [item for item in exported if item["duplicate_state"] == "possible_duplicate"]
    assert len(possible) == 2
    assert all(len(item["possible_duplicate_ids"]) == 1 for item in possible)
    review_titles = {
        json.loads(line)["title"]
        for line in (engine_config.paths.output_dir / "review_queue.jsonl").read_text().splitlines()
    }
    for title, route in expected_routes.items():
        if route == c.ROUTE_EXCLUDED:
            assert title not in review_titles

    # Profile switches reroute existing stored candidates during export; a
    # refetch is not required and the broad candidate store is unchanged.
    switched = c.PROFILE_ALL if profile != c.PROFILE_ALL else c.PROFILE_STUDENT
    engine_config.routing.active_profile = switched
    export_all(conn, engine_config, summary.run_id)
    switched_export = [
        json.loads(line)
        for line in (engine_config.paths.output_dir / "candidates.jsonl").read_text().splitlines()
    ]
    assert all(item["active_profile"] == switched for item in switched_export)
    assert len(switched_export) == 8
    conn.close()
