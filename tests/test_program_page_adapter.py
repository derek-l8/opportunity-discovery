from opportunity_discovery.adapters.base import run_source
from opportunity_discovery.constants import HEALTH_COVERAGE_WARNING
from opportunity_discovery.identity import identity_key
from tests.helpers import load_fixture, source


def overview_application_spec(**endpoint_overrides):
    endpoint = {
        "overview_url": "https://programs.example.com/systems-exploration",
        "max_pages": 2,
        "selectors": {
            "title": "h1",
            "application_state": ".status",
            "location_text": ".location",
            "deadline": ".deadline",
            "event_start_date": ".event-start",
            "event_end_date": ".event-end",
            "requirements_text": ".requirements",
        },
        "state_rules": [
            {"state": "application-open", "pattern": "(?i)applications? open"},
            {"state": "notification-only", "pattern": "(?i)notification list"},
            {"state": "closed", "pattern": "(?i)applications? closed"},
        ],
        "coverage": {
            "min_results": 1,
            "max_results": 1,
            "expected_url_patterns": [r"/apply/systems-harbor-2027$"],
            "expected_title_patterns": [r"Harbor 2027$"],
        },
        "programs": [
            {
                "application_url": "https://programs.example.com/apply/systems-harbor-2027",
                "program_family_id": "systems-exploration",
                "session_id": "harbor-2027",
                "season": "spring-2027",
            }
        ],
    }
    endpoint.update(endpoint_overrides)
    return source(
        source_id="program-synthetic-systems",
        organization="Synthetic Organization Alpha",
        adapter="program-page",
        endpoint_config=endpoint,
    )


def add_overview_application_routes(mock_fetcher):
    mock_fetcher.add(
        "https://programs.example.com/systems-exploration",
        200,
        load_fixture("program_overview_notification.html"),
    )
    mock_fetcher.add(
        "https://programs.example.com/apply/systems-harbor-2027",
        200,
        load_fixture("program_application_open.html"),
    )


def test_direct_application_overrides_notification_only_overview(mock_fetcher):
    add_overview_application_routes(mock_fetcher)
    spec = overview_application_spec()
    assert not spec.validate()

    result = run_source(spec, mock_fetcher)

    assert result.ok and len(result.records) == 1
    assert mock_fetcher.calls == [
        "https://programs.example.com/systems-exploration",
        "https://programs.example.com/apply/systems-harbor-2027",
    ]
    record = result.records[0]
    assert record.application_state == "application-open"
    assert record.overview_url.endswith("/systems-exploration")
    assert record.application_url.endswith("/apply/systems-harbor-2027")
    assert record.deadline == "2026-11-15"
    assert record.event_start_date == "2027-03-21"
    assert record.event_end_date == "2027-03-25"
    assert record.provider_req_id == "systems-exploration:harbor-2027"


def test_recurring_location_cycles_use_selectors_and_jsonld_without_merging(mock_fetcher):
    overview = "https://events.example.com/applied-circuits"
    harbor = "https://events.example.com/apply/harbor-2027"
    mesa = "https://events.example.com/apply/mesa-2028"
    mock_fetcher.add(overview, 200, load_fixture("recurring_overview.html"))
    mock_fetcher.add(harbor, 200, load_fixture("recurring_harbor_2027.html"))
    mock_fetcher.add(mesa, 200, load_fixture("recurring_mesa_2028.html"))
    spec = source(
        source_id="program-synthetic-recurring",
        organization="Synthetic Organization Beta",
        adapter="program-page",
        endpoint_config={
            "overview_url": overview,
            "max_pages": 3,
            "selectors": {
                "title": "h1",
                "application_state": ".status",
                "location_text": ".location",
                "deadline": ".deadline",
                "event_start_date": ".event-start",
                "event_end_date": ".event-end",
                "requirements_text": ".requirements",
            },
            "jsonld_type": "Event",
            "jsonld_fields": {
                "title": "name",
                "location_text": "location.name",
                "deadline": "applicationDeadline",
                "event_start_date": "startDate",
                "event_end_date": "endDate",
                "requirements_text": "description",
            },
            "state_rules": [
                {"state": "application-open", "pattern": "(?i)applications? open"},
                {"state": "notification-only", "pattern": "(?i)notification list"},
            ],
            "coverage": {
                "min_results": 2,
                "max_results": 2,
                "expected_url_patterns": [r"harbor-2027$", r"mesa-2028$"],
                "expected_title_patterns": [r"Harbor 2027$", r"Mesa 2028$"],
            },
            "programs": [
                {
                    "application_url": harbor,
                    "program_family_id": "applied-circuits",
                    "cycle_id": "harbor-2027",
                },
                {
                    "application_url": mesa,
                    "program_family_id": "applied-circuits",
                    "cycle_id": "mesa-2028",
                },
            ],
        },
    )
    assert not spec.validate()

    result = run_source(spec, mock_fetcher)

    assert result.ok and len(result.records) == 2
    harbor_record, mesa_record = result.records
    assert harbor_record.application_state == "application-open"
    assert harbor_record.deadline == "2027-02-01"
    assert harbor_record.event_start_date == "2027-06-10"
    assert mesa_record.application_state == "notification-only"
    assert mesa_record.event_start_date == "2028-01-18"
    harbor_id = identity_key(
        provider=harbor_record.provider,
        provider_req_id=harbor_record.provider_req_id,
        canonical_url=harbor_record.canonical_url,
    )[0]
    mesa_id = identity_key(
        provider=mesa_record.provider,
        provider_req_id=mesa_record.provider_req_id,
        canonical_url=mesa_record.canonical_url,
    )[0]
    assert harbor_id != mesa_id


def test_overview_only_program_supports_notification_state(mock_fetcher):
    overview = "https://programs.example.com/systems-exploration"
    mock_fetcher.add(overview, 200, load_fixture("program_overview_notification.html"))
    spec = overview_application_spec(
        max_pages=1,
        coverage={"min_results": 1, "max_results": 1},
        programs=[
            {
                "program_family_id": "systems-exploration",
                "cycle_id": "next-cycle",
            }
        ],
    )

    result = run_source(spec, mock_fetcher)

    assert result.ok
    assert result.records[0].application_url is None
    assert result.records[0].application_state == "notification-only"


def test_coverage_canary_warns_even_when_http_and_parsing_succeed(mock_fetcher):
    add_overview_application_routes(mock_fetcher)
    spec = overview_application_spec(
        coverage={
            "min_results": 1,
            "max_results": 1,
            "expected_title_patterns": [r"Unexpected Cycle$"],
        }
    )

    result = run_source(spec, mock_fetcher)

    assert not result.ok
    assert result.state == HEALTH_COVERAGE_WARNING
    assert "expected title pattern" in (result.detail or "")


def test_program_page_config_rejects_page_overflow_and_weak_repeated_identity():
    spec = overview_application_spec(
        max_pages=1,
        programs=[
            {"application_url": "https://programs.example.com/shared"},
            {"application_url": "https://programs.example.com/shared"},
        ],
    )

    errors = spec.validate()

    assert any("repeated canonical URL" in error for error in errors)
    assert any("exceeding max_pages" in error for error in errors)
