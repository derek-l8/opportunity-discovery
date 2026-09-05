"""Configurable public JSON feed adapter.

endpoint_config:
    url: https://example.org/opps.json
    records_path: opportunities          # dot path to the array of records
    fields:
        title: title                     # dot paths within each record
        canonical_url: apply_url
        organization: company
        location_text: location
        deadline: deadline
        posted_date: posted
        compensation_text: pay
        description_excerpt: blurb
        season: season
        employment_type: type
        engagement_type: engagement_type
        career_stage: career_stage
        required_degree: required_degree
        preferred_degree: preferred_degree
        experience_requirement_text: experience_requirement
"""

from __future__ import annotations

import json
from typing import Any

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, parse_json_body, register_adapter

_DEFAULT_FIELDS = {
    "title": "title",
    "canonical_url": "url",
    "organization": "organization",
    "provider_req_id": "id",
    "location_text": "location",
    "remote_signal": "remote",
    "posted_date": "posted",
    "deadline": "deadline",
    "compensation_text": "compensation",
    "relocation_text": "relocation",
    "description_excerpt": "description",
    "season": "season",
    "employment_type": "type",
    "engagement_type": "engagement_type",
    "career_stage": "career_stage",
    "required_degree": "required_degree",
    "preferred_degree": "preferred_degree",
    "experience_requirement_text": "experience_requirement",
}


def _dig(obj: Any, dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


@register_adapter("jsonfeed")
class JsonFeedAdapter:
    name = "jsonfeed"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        url = cfg.get("url")
        if not url:
            return AdapterResult(
                ok=False, state="check-failed", detail="jsonfeed adapter requires endpoint_config.url"
            )
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304, detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        try:
            data = parse_json_body(out.text)
        except (ValueError, json.JSONDecodeError) as exc:
            return AdapterResult(
                ok=False, state="format-changed", detail=f"bad JSON: {exc}", http_status=out.status
            )
        records_path = cfg.get("records_path", "")
        items: Any = _dig(data, records_path) if records_path else data
        if not isinstance(items, list):
            return AdapterResult(
                ok=False,
                state="format-changed",
                detail=f"'{records_path or 'root'}' is not an array",
                http_status=out.status,
            )
        field_map = {**_DEFAULT_FIELDS, **(cfg.get("fields") or {})}
        records: list[RawOpportunity] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _dig(item, field_map["title"])
            link = _dig(item, field_map["canonical_url"])
            if not title or not link:
                continue
            deadline = _dig(item, field_map["deadline"])
            records.append(
                RawOpportunity(
                    title=str(title).strip(),
                    canonical_url=str(link).strip(),
                    organization=_dig(item, field_map["organization"]),
                    provider=ctx.source.source_id,
                    provider_req_id=_dig(item, field_map["provider_req_id"]),
                    location_text=_dig(item, field_map["location_text"]),
                    remote_signal=_dig(item, field_map["remote_signal"]),
                    posted_date=_dig(item, field_map["posted_date"]),
                    deadline=(str(deadline)[:10] if deadline else None),
                    compensation_text=_dig(item, field_map["compensation_text"]),
                    relocation_text=_dig(item, field_map["relocation_text"]),
                    description_excerpt=bounded_excerpt(
                        _dig(item, field_map["description_excerpt"]), ctx.excerpt_chars
                    ),
                    season=_dig(item, field_map["season"]),
                    employment_type=_dig(item, field_map["employment_type"]),
                    engagement_type=_dig(item, field_map["engagement_type"]),
                    career_stage=_dig(item, field_map["career_stage"]),
                    required_degree=_dig(item, field_map["required_degree"]),
                    preferred_degree=_dig(item, field_map["preferred_degree"]),
                    experience_requirement_text=_dig(item, field_map["experience_requirement_text"]),
                )
            )
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)
