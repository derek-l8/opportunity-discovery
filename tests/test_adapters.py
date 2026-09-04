import json

from opportunity_discovery.adapters.base import run_source
from opportunity_discovery.constants import HEALTH_FORMAT_CHANGED
from tests.helpers import load_fixture, source


def test_greenhouse_success(mock_fetcher):
    mock_fetcher.add("https://boards-api.greenhouse.io", 200, load_fixture("greenhouse_jobs.json"))
    result = run_source(source(), mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.provider == "greenhouse"
    assert rec.title == "FPGA Design Intern"
    assert rec.location_text == "Santa Clara, CA"
    assert rec.remote_signal is None


def test_greenhouse_empty_is_valid_empty(mock_fetcher):
    mock_fetcher.add("https://boards-api.greenhouse.io", 200, '{"jobs": []}')
    result = run_source(source(), mock_fetcher)
    assert result.ok and not result.records and result.empty_ok


def test_lever_success_and_remote_signal(mock_fetcher):
    from tests.helpers import source as src

    spec = src(source_id="lever-acmehw", adapter="lever", endpoint_config={"board": "acmehw"})
    mock_fetcher.add("https://api.lever.co/v0/postings/acmehw", 200, load_fixture("lever_postings.json"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    remote = result.records[1]
    assert remote.remote_signal == "remote"
    assert result.records[0].posted_date == "2025-08-10"


def test_ashby_success(mock_fetcher):
    from tests.helpers import source as src

    spec = src(source_id="ashby-acmerobotics", adapter="ashby", endpoint_config={"board": "acmerobotics"})
    mock_fetcher.add(
        "https://api.ashbyhq.com/posting-api/job-board/acmerobotics", 200, load_fixture("ashby_board.json")
    )
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    assert result.records[0].provider == "ashby"
    assert "SLAM" in (result.records[0].description_excerpt or "")


def test_smartrecruiters_success(mock_fetcher):
    from tests.helpers import source as src

    spec = src(source_id="sr-acmesemi", adapter="smartrecruiters", endpoint_config={"company": "acmesemi"})
    mock_fetcher.add(
        "https://api.smartrecruiters.com/v1/companies/acmesemi/postings",
        200,
        load_fixture("smartrecruiters_postings.json"),
    )
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.provider_req_id == "A94C7F2B"
    assert rec.location_text == "Boise, ID, US"
    assert "$25.00" in (rec.compensation_text or "")
    assert result.pages_fetched == 1
    assert result.reported_total == 2
    assert result.truncated is False


def test_smartrecruiters_reports_known_truncation(mock_fetcher, monkeypatch):
    from opportunity_discovery.adapters import smartrecruiters
    from tests.helpers import source as src

    monkeypatch.setattr(smartrecruiters, "_MAX_PAGES", 1)
    payload = json.loads(load_fixture("smartrecruiters_postings.json"))
    payload["totalFound"] = 101
    spec = src(
        source_id="sr-truncated",
        adapter="smartrecruiters",
        endpoint_config={"company": "acmesemi"},
    )
    mock_fetcher.add(
        "https://api.smartrecruiters.com/v1/companies/acmesemi/postings",
        200,
        json.dumps(payload),
    )
    result = run_source(spec, mock_fetcher)
    assert result.ok
    assert result.pages_fetched == 1
    assert result.reported_total == 101
    assert result.truncated is True


def test_workday_success_uses_post(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="workday-acme",
        adapter="workday",
        endpoint_config={
            "url": "https://acme.wd1.myworkdayjobs.com/External",
            "tenant": "acme",
            "site": "External",
        },
    )
    api = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/jobs"
    mock_fetcher.add(api, 200, load_fixture("workday_jobs.json"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.provider == "workday"
    assert rec.canonical_url.endswith("/job/Power-Electronics-Systems-Intern_Hillsboro/OR/1234567/")
    assert result.pages_fetched == 1
    assert result.reported_total == 2
    assert result.truncated is False


def test_jsonfeed_field_mapping(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="json-acmechips",
        adapter="jsonfeed",
        organization="Acme Chips",
        endpoint_config={
            "url": "https://acmechips.example.com/feed.json",
            "records_path": "jobs",
            "fields": {
                "title": "title",
                "canonical_url": "jobUrl",
                "season": "season",
                "deadline": "deadline",
                "compensation_text": "compensation",
            },
        },
    )
    mock_fetcher.add("https://acmechips.example.com/feed.json", 200, load_fixture("feed.json"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    first = result.records[0]
    assert first.deadline == "2026-10-15"
    assert "relocation support" in (first.compensation_text or "")
    # tracking params stripped later at normalization; url preserved here
    second = result.records[1]
    assert second.canonical_url.startswith("https://acmechips.example.com/apply/1002")


def test_csvfeed_column_mapping(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="csv-community",
        adapter="csvfeed",
        endpoint_config={"url": "https://community.example.org/list.csv"},
    )
    mock_fetcher.add("https://community.example.org/list.csv", 200, load_fixture("feed.csv"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.organization == "Omega Energy"
    assert rec.season.lower().startswith("summer")


def test_rss_feed(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="rss-acme",
        adapter="rss",
        organization="Acme Labs",
        endpoint_config={"url": "https://acmelabs.example.org/feed.xml"},
    )
    mock_fetcher.add("https://acmelabs.example.org/feed.xml", 200, load_fixture("feed.xml"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.posted_date == "2026-08-03"
    assert "travel grant" in (rec.description_excerpt or "").lower()


def test_github_markdown_table(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="gh-board",
        adapter="githublist",
        endpoint_config={"url": "https://raw.example.org/board.md", "format": "table"},
    )
    mock_fetcher.add("https://raw.example.org/board.md", 200, load_fixture("board.md"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.organization == "Delta Semis"
    assert rec.canonical_url == "https://deltasemis.example.com/analog-intern"


def test_htmllist_selectors(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="html-acme",
        adapter="htmllist",
        endpoint_config={
            "url": "https://acme.example.com/opps",
            "item_selector": "ul.programs li",
            "title_selector": "h3 a",
            "deadline_selector": ".deadline",
        },
    )
    mock_fetcher.add("https://acme.example.com/opps", 200, load_fixture("list.html"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.title == "FPGA Verification Intern"
    assert rec.deadline == "2026-10-01"


def test_sitemap_include_exclude(mock_fetcher):
    from tests.helpers import source as src

    spec = src(
        source_id="sitemap-acmelab",
        adapter="sitemap",
        endpoint_config={
            "url": "https://acmelab.example.com/sitemap.xml",
            "include_regex": "/opportunities/",
            "exclude_regex": "/(tag|category)/",
        },
    )
    mock_fetcher.add("https://acmelab.example.com/sitemap.xml", 200, load_fixture("sitemap.xml"))
    result = run_source(spec, mock_fetcher)
    assert result.ok and len(result.records) == 2
    rec = result.records[0]
    assert rec.evidence == "inferred-signal"
    assert rec.title == "Summer Photonics Reu"


def test_timeout_maps_to_check_failed_not_empty(mock_fetcher):
    def timeout_route(url):
        return (None, "", {}) if False else (503, "upstream timeout", {})

    mock_fetcher.routes["https://boards-api.greenhouse.io"] = timeout_route
    result = run_source(source(), mock_fetcher)
    assert not result.ok
    assert result.state in ("check-failed", "rate-limited")


def test_malformed_json_is_format_changed(mock_fetcher):
    mock_fetcher.add("https://boards-api.greenhouse.io", 200, "<html>not json</html>")
    result = run_source(source(), mock_fetcher)
    assert not result.ok
    assert result.state == HEALTH_FORMAT_CHANGED


def test_format_drift_missing_jobs_key(mock_fetcher):
    mock_fetcher.add("https://boards-api.greenhouse.io", 200, '{"postings": []}')
    result = run_source(source(), mock_fetcher)
    assert not result.ok
    assert result.state == HEALTH_FORMAT_CHANGED


def test_adapter_failure_isolated_per_source(mock_fetcher):
    # unknown adapter must fail softly with a detail message
    result = run_source(source(adapter="nonexistent"), mock_fetcher)
    assert not result.ok
    assert "unknown adapter" in (result.detail or "")


def test_not_modified_304_is_healthy_not_drift(mock_fetcher):
    mock_fetcher.routes["https://boards-api.greenhouse.io"] = lambda url: (304, "", {"etag": '"v1"'})
    result = run_source(source(), mock_fetcher)
    assert result.ok
    assert result.state == "healthy"
    assert result.http_status == 304


def test_304_with_cached_body_is_parsed(mock_fetcher):
    """A 304 must parse its cached body so observations (and closures) stay accurate."""
    cached = load_fixture("greenhouse_jobs.json")
    mock_fetcher.routes["https://boards-api.greenhouse.io"] = lambda url: (304, cached, {"etag": '"v1"'})
    result = run_source(source(), mock_fetcher)
    assert result.ok and len(result.records) == 2
