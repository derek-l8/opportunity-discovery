"""Greenhouse public job board adapter.

Public endpoints (no credentials):
    https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from ..extraction import description_location, extract_description
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
        out = ctx.fetcher.fetch(url, max_response_bytes=ctx.source.endpoint_config.get("max_response_bytes"))
        if out.not_modified and not out.text:
            return AdapterResult(
                ok=False,
                state="check-failed",
                detail="HTTP 304 without cached board body",
                http_status=304,
                truncated=True,
            )
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            failed = outcome_to_result(out)
            failed.truncated = True
            return failed
        try:
            data = parse_json_body(out.text)
        except (ValueError, json.JSONDecodeError) as exc:
            return AdapterResult(
                ok=False, state="format-changed", detail=f"bad JSON: {exc}", http_status=out.status
            )
        if not isinstance(data, dict):
            return AdapterResult(
                ok=False, state="format-changed", detail="expected a JSON object", http_status=out.status
            )
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return AdapterResult(
                ok=False, state="format-changed", detail="missing 'jobs' array", http_status=out.status
            )
        meta = data.get("meta")
        if meta is not None and not isinstance(meta, dict):
            return AdapterResult(
                ok=False, state="format-changed", detail="invalid 'meta' object", http_status=out.status
            )
        reported_total = meta.get("total") if isinstance(meta, dict) else None
        if ctx.source.endpoint_config.get("max_response_bytes") is not None and reported_total is None:
            return AdapterResult(
                ok=False,
                state="coverage-warning",
                detail="large board response lacks meta.total",
                http_status=out.status,
                truncated=True,
            )
        if reported_total is not None and (type(reported_total) is not int or reported_total != len(jobs)):
            return AdapterResult(
                ok=False,
                state="coverage-warning",
                detail=f"board reported {reported_total} jobs but returned {len(jobs)}",
                http_status=out.status,
                reported_total=reported_total if type(reported_total) is int else None,
                truncated=True,
            )
        ids = [job.get("id") for job in jobs if isinstance(job, dict)]
        if (
            len(ids) != len(jobs)
            or any(type(job_id) not in (str, int) for job_id in ids)
            or len(set(ids)) != len(ids)
            or any(not isinstance(job.get("absolute_url"), str) or not job["absolute_url"] for job in jobs)
        ):
            return AdapterResult(
                ok=False,
                state="format-changed",
                detail="board jobs require unique posting IDs and URLs",
                http_status=out.status,
                reported_total=reported_total,
                truncated=True,
            )
        records = [self._record(job, org, ctx.excerpt_chars) for job in jobs]
        return AdapterResult(
            ok=True,
            records=records,
            empty_ok=True,
            http_status=out.status,
            pages_fetched=1,
            reported_total=reported_total,
            truncated=False,
        )

    def _record(self, job: dict, org: str, excerpt_chars: int) -> RawOpportunity:
        offices = job.get("offices") or []
        locations = ", ".join(o.get("name", "") for o in offices if isinstance(o, dict) and o.get("name"))
        loc_text = locations or (job.get("location") or {}).get("name") or None
        updated = job.get("updated_at") or ""
        posted = None
        if updated:
            try:
                dt = datetime.strptime(updated.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
                posted = dt.astimezone(UTC).date().isoformat()
            except ValueError:
                posted = updated[:10]
        content = job.get("content") or ""
        facts = extract_description(content)
        loc_text = loc_text or description_location(content)
        # Inspect all content first; the displayed excerpt prioritizes requirements.
        excerpt = bounded_excerpt(facts["requirements_text"] or content, excerpt_chars)
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
            employment_type="internship" if re.search(r"\bintern(?:ship)?\b", title_l) else None,
            description_excerpt=excerpt,
            extra={"requirements_extracted": True},
            **facts,
        )
