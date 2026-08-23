"""Ashby public job board adapter.

Public endpoint (no credentials):
    https://api.ashbyhq.com/posting-api/job-board/{org}
"""
from __future__ import annotations

import json

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, parse_json_body, register_adapter


@register_adapter("ashby")
class AshbyAdapter:
    name = "ashby"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        org = ctx.source.endpoint_config.get("board") or ctx.source.endpoint_config.get("org")
        if not org:
            return AdapterResult(ok=False, state="check-failed",
                                 detail="ashby adapter requires endpoint_config.board")
        url = f"https://api.ashbyhq.com/posting-api/job-board/{org}"
        out = ctx.fetcher.fetch(url)
        if not out.ok:
            result = outcome_to_result(out)
            if out.not_modified:
                return AdapterResult(ok=True, state="healthy", http_status=304,
                                     detail="not modified; prior cache retained")
            return result
        try:
            data = parse_json_body(out.text)
        except (ValueError, json.JSONDecodeError) as exc:
            return AdapterResult(ok=False, state="format-changed", detail=f"bad JSON: {exc}",
                                 http_status=out.status)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return AdapterResult(ok=False, state="format-changed", detail="missing 'jobs' array",
                                 http_status=out.status)
        records = []
        for job in jobs:
            loc = job.get("location") or ""
            published = (job.get("publishedAt") or "")[:10] or None
            records.append(
                RawOpportunity(
                    title=(job.get("title") or "").strip(),
                    canonical_url=job.get("jobUrl") or job.get("applyUrl"),
                    organization=org.replace("-", " ").title(),
                    provider="ashby",
                    provider_req_id=str(job.get("id")) if job.get("id") is not None else None,
                    location_text=loc,
                    remote_signal="remote" if "remote" in str(loc).lower() else None,
                    posted_date=published,
                    employment_type=(job.get("employmentType") or "").lower() or None,
                    description_excerpt=bounded_excerpt(job.get("descriptionPlain"), ctx.excerpt_chars),
                )
            )
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)
