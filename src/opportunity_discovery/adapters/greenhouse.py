"""Greenhouse public job board adapter.

Public endpoints (no credentials):
    https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, parse_json_body, register_adapter


@register_adapter("greenhouse")
class GreenhouseAdapter:
    name = "greenhouse"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        org = ctx.source.endpoint_config.get("board") or ctx.source.endpoint_config.get("org")
        if not org:
            return AdapterResult(
                ok=False, state="check-failed", detail="greenhouse adapter requires endpoint_config.board"
            )
        url = f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true"
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
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return AdapterResult(
                ok=False, state="format-changed", detail="missing 'jobs' array", http_status=out.status
            )
        records = [self._record(job, org, ctx.excerpt_chars) for job in jobs]
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)

    def _record(self, job: dict, org: str, excerpt_chars: int) -> RawOpportunity:
        offices = job.get("offices") or []
        locations = ", ".join(o.get("name", "") for o in offices if isinstance(o, dict) and o.get("name"))
        loc_text = locations or None
        updated = job.get("updated_at") or ""
        posted = None
        if updated:
            try:
                dt = datetime.strptime(updated.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
                posted = dt.astimezone(UTC).date().isoformat()
            except ValueError:
                posted = updated[:10]
        content = job.get("content") or ""
        # Greenhouse content is HTML when content=true.
        excerpt = bounded_excerpt(content, excerpt_chars)
        title_l = (job.get("title") or "").lower()
        return RawOpportunity(
            title=(job.get("title") or "").strip(),
            canonical_url=job.get("absolute_url") or "",
            organization=org.replace("-", " ").title(),
            provider="greenhouse",
            provider_req_id=str(job.get("id")) if job.get("id") is not None else None,
            location_text=loc_text,
            remote_signal=(
                "remote"
                if loc_text and ("remote" in loc_text.lower() or "anywhere" in loc_text.lower())
                else None
            ),
            posted_date=posted,
            employment_type="internship" if "intern" in title_l else None,
            description_excerpt=excerpt,
        )
