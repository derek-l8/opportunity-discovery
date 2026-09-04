"""Bounded adapter for explicitly configured recurring public program pages.

The adapter never crawls or guesses routes. It fetches only configured overview
and application URLs (at most eight unique pages), validates redirect hosts via
the shared fetcher, and emits one record per explicitly configured cycle/session.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .. import constants as c
from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter

HARD_MAX_PAGES = 8
SUPPORTED_FIELDS = {
    "title",
    "location_text",
    "deadline",
    "event_start_date",
    "event_end_date",
    "requirements_text",
    "application_state",
    "description_excerpt",
}


@register_adapter("program-page")
class ProgramPageAdapter:
    name = "program-page"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        programs = cfg.get("programs")
        max_pages = cfg.get("max_pages", HARD_MAX_PAGES)
        if not isinstance(programs, list) or not programs or not isinstance(max_pages, int):
            return _failed("program-page requires a non-empty programs array and integer max_pages")
        if len(programs) > HARD_MAX_PAGES or not 1 <= max_pages <= HARD_MAX_PAGES:
            return _failed(f"program-page page/program limits must be from 1 to {HARD_MAX_PAGES}")

        urls = _configured_urls(cfg, programs)
        if len(urls) > max_pages:
            return _failed(f"configured {len(urls)} unique pages exceeds max_pages={max_pages}")
        allowed_hosts = {(urlsplit(url).hostname or "").lower() for url in urls}
        pages: dict[str, tuple[BeautifulSoup, str]] = {}
        statuses: list[int] = []
        for url in urls:
            outcome = ctx.fetcher.fetch(url, allowed_hosts=allowed_hosts)
            if outcome.not_modified and not outcome.text:
                return AdapterResult(
                    ok=False,
                    state=c.HEALTH_DEGRADED,
                    http_status=304,
                    detail="not modified but no cached body was available",
                )
            if not outcome.ok:
                return outcome_to_result(outcome)
            final_url = outcome.final_url or url
            pages[url] = (BeautifulSoup(outcome.text or "", "html.parser"), final_url)
            if outcome.status is not None:
                statuses.append(outcome.status)

        records: list[RawOpportunity] = []
        for index, program in enumerate(programs):
            if not isinstance(program, dict):
                return _format_changed(f"programs[{index}] is not a table", statuses)
            built, error = _build_record(ctx, cfg, program, pages)
            if error:
                return _format_changed(f"programs[{index}]: {error}", statuses)
            if built is not None:
                records.append(built)

        coverage_errors = _coverage_errors(records, cfg.get("coverage", {}))
        if coverage_errors:
            return AdapterResult(
                ok=False,
                state=c.HEALTH_COVERAGE_WARNING,
                detail="; ".join(coverage_errors),
                http_status=statuses[-1] if statuses else None,
            )
        return AdapterResult(
            ok=True,
            records=records,
            empty_ok=not records,
            state=c.HEALTH_HEALTHY,
            detail=f"{len(records)} configured program record(s) from {len(urls)} page(s)",
            http_status=statuses[-1] if statuses else None,
        )


def _configured_urls(cfg: dict[str, Any], programs: list[Any]) -> list[str]:
    ordered: list[str] = []
    source_overview = cfg.get("overview_url")
    source_application = cfg.get("application_url")
    for program in programs:
        if not isinstance(program, dict):
            continue
        for value in (
            program.get("overview_url", source_overview),
            program.get("application_url", source_application),
        ):
            if value and str(value) not in ordered:
                ordered.append(str(value))
    return ordered


def _build_record(
    ctx,  # type: ignore[no-untyped-def]
    cfg: dict[str, Any],
    program: dict[str, Any],
    pages: dict[str, tuple[BeautifulSoup, str]],
) -> tuple[RawOpportunity | None, str | None]:
    overview_configured = program.get("overview_url", cfg.get("overview_url"))
    application_configured = program.get("application_url", cfg.get("application_url"))
    primary_configured = application_configured or overview_configured
    if not primary_configured or primary_configured not in pages:
        return None, "no fetched overview_url or application_url"
    primary_soup, primary_final = pages[str(primary_configured)]
    overview_final = pages[str(overview_configured)][1] if overview_configured else None
    application_final = pages[str(application_configured)][1] if application_configured else None

    selectors = dict(cfg.get("selectors") or {})
    selectors.update(program.get("selectors") or {})
    jsonld_fields = dict(cfg.get("jsonld_fields") or {})
    jsonld_fields.update(program.get("jsonld_fields") or {})
    jsonld_type = str(program.get("jsonld_type", cfg.get("jsonld_type", "Event")))
    structured = _select_jsonld(primary_soup, jsonld_type)

    values: dict[str, str | None] = {}
    for field in SUPPORTED_FIELDS:
        static = program.get(field)
        selector_value = _selector_text(primary_soup, selectors.get(field))
        structured_value = _dot_get(structured, jsonld_fields.get(field))
        value = static if static not in (None, "") else selector_value or structured_value
        values[field] = str(value).strip() if value not in (None, "") else None

    title = values["title"]
    if not title:
        return None, "title was not found by configured static value, selector, or JSON-LD path"
    application_state = _application_state(values["application_state"], cfg, program)
    family = program.get("program_family_id", cfg.get("program_family_id"))
    cycle = program.get("cycle_id", program.get("session_id"))
    provider_req_id = f"{family}:{cycle}" if family and cycle else None
    deadline = _iso_date(values["deadline"])
    start_date = _iso_date(values["event_start_date"])
    end_date = _iso_date(values["event_end_date"])
    for name, raw_value, parsed in (
        ("deadline", values["deadline"], deadline),
        ("event_start_date", values["event_start_date"], start_date),
        ("event_end_date", values["event_end_date"], end_date),
    ):
        if raw_value and not parsed:
            return None, f"{name} did not contain an ISO YYYY-MM-DD date"
    requirements = bounded_excerpt(values["requirements_text"], min(ctx.excerpt_chars, 600))
    description = bounded_excerpt(values["description_excerpt"] or requirements, min(ctx.excerpt_chars, 600))
    return (
        RawOpportunity(
            title=title,
            canonical_url=application_final or overview_final or primary_final,
            organization=ctx.source.organization,
            provider="program-page" if provider_req_id else None,
            provider_req_id=provider_req_id,
            location_text=values["location_text"],
            deadline=deadline,
            overview_url=overview_final,
            application_url=application_final,
            program_family_id=str(family) if family else None,
            cycle_id=str(cycle) if cycle else None,
            event_start_date=start_date,
            event_end_date=end_date,
            application_state=application_state,
            requirements_text=requirements,
            description_excerpt=description,
            employment_type=str(program.get("employment_type", "program")),
            season=program.get("season"),
            extra={"configured_page_url": str(primary_configured)},
        ),
        None,
    )


def _selector_text(soup: BeautifulSoup, selector: Any) -> str | None:
    if not isinstance(selector, str) or not selector:
        return None
    element = soup.select_one(selector)
    return element.get_text(" ", strip=True) if element else None


def _select_jsonld(soup: BeautifulSoup, expected_type: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            document = json.loads(script.string or script.get_text() or "")
        except (TypeError, json.JSONDecodeError):
            continue
        candidates.extend(_jsonld_objects(document))
    for candidate in candidates:
        kind = candidate.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if expected_type in kinds:
            return candidate
    return candidates[0] if candidates and not expected_type else None


def _jsonld_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for value_item in value for item in _jsonld_objects(value_item)]
    if not isinstance(value, dict):
        return []
    graph = value.get("@graph")
    if isinstance(graph, list):
        return [value, *[item for graph_item in graph for item in _jsonld_objects(graph_item)]]
    return [value]


def _dot_get(value: dict[str, Any] | None, path: Any) -> str | None:
    if not value or not isinstance(path, str) or not path:
        return None
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if isinstance(current, dict):
        return str(current.get("name")) if current.get("name") else None
    if isinstance(current, list):
        return ", ".join(
            str(item.get("name", item)) if isinstance(item, dict) else str(item) for item in current
        )
    return str(current) if current is not None else None


def _application_state(raw: str | None, cfg: dict[str, Any], program: dict[str, Any]) -> str:
    if raw in c.ALL_APPLICATION_STATES:
        return str(raw)
    rules = program.get("state_rules", cfg.get("state_rules", []))
    text = raw or ""
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            state = rule.get("state")
            pattern = rule.get("pattern")
            if state in c.ALL_APPLICATION_STATES and isinstance(pattern, str) and re.search(pattern, text):
                return str(state)
    return c.APPLICATION_UNKNOWN


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", value)
    return match.group(0) if match else None


def _coverage_errors(records: list[RawOpportunity], coverage: Any) -> list[str]:
    if not isinstance(coverage, dict):
        return ["coverage configuration is not a table"]
    minimum = coverage.get("min_results", 1)
    maximum = coverage.get("max_results", len(records))
    errors: list[str] = []
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        return ["coverage min_results/max_results must be integers"]
    if not minimum <= len(records) <= maximum:
        errors.append(f"result count {len(records)} outside plausible range [{minimum}, {maximum}]")
    urls = [record.canonical_url for record in records]
    titles = [record.title for record in records]
    for pattern in coverage.get("expected_url_patterns", []):
        if not any(re.search(pattern, value) for value in urls):
            errors.append(f"expected URL pattern {pattern!r} did not match")
    for pattern in coverage.get("expected_title_patterns", []):
        if not any(re.search(pattern, value) for value in titles):
            errors.append(f"expected title pattern {pattern!r} did not match")
    return errors


def _failed(detail: str) -> AdapterResult:
    return AdapterResult(ok=False, state=c.HEALTH_CHECK_FAILED, detail=detail)


def _format_changed(detail: str, statuses: list[int]) -> AdapterResult:
    return AdapterResult(
        ok=False,
        state=c.HEALTH_FORMAT_CHANGED,
        detail=detail,
        http_status=statuses[-1] if statuses else None,
    )
