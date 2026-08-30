"""SmartRecruiters public postings adapter.

Public endpoint (no credentials):
    https://api.smartrecruiters.com/v1/companies/{org}/postings?limit=100&q=&offset=N
"""

from __future__ import annotations

import json
from typing import Any

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, parse_json_body, register_adapter

_PAGE_SIZE = 100
_MAX_PAGES = 10


@register_adapter("smartrecruiters")
class SmartRecruitersAdapter:
    name = "smartrecruiters"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        company = ctx.source.endpoint_config.get("company") or ctx.source.endpoint_config.get("org")
        if not company:
            return AdapterResult(
                ok=False,
                state="check-failed",
                detail="smartrecruiters adapter requires endpoint_config.company",
            )
        records: list[RawOpportunity] = []
        offset = 0
        total: int | None = None
        status: int | None = None
        for _page in range(_MAX_PAGES):
            url = (
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
                f"?limit={_PAGE_SIZE}&offset={offset}"
            )
            out = ctx.fetcher.fetch(url)
            status = out.status or status
            if not out.ok:
                if out.not_modified and not out.text:
                    return AdapterResult(ok=True, empty_ok=True, http_status=304, detail="not modified")
                return outcome_to_result(out)
            try:
                data = parse_json_body(out.text)
            except (ValueError, json.JSONDecodeError) as exc:
                return AdapterResult(
                    ok=False, state="format-changed", detail=f"bad JSON: {exc}", http_status=out.status
                )
            postings = data.get("content")
            if postings is None:
                return AdapterResult(
                    ok=False, state="format-changed", detail="missing 'content' array", http_status=out.status
                )
            for posting in postings:
                records.append(self._record(posting, company, ctx.excerpt_chars))
            total = int(data.get("totalFound") or 0)
            offset += _PAGE_SIZE
            if offset >= total or not postings:
                break
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=status)

    def _record(self, posting: dict[str, Any], company: str, excerpt_chars: int) -> RawOpportunity:
        location = posting.get("location") or {}
        city = location.get("city")
        country = location.get("country")
        region = location.get("region")
        parts = [p for p in (city, region, country) if p]
        loc_text = ", ".join(parts) or None
        released = posting.get("releasedDate") or ""
        comp = posting.get("compensation") or {}
        comp_text = None
        if isinstance(comp, dict) and comp.get("description"):
            comp_text = str(comp["description"])
        name = posting.get("name") or ""
        return RawOpportunity(
            title=name.strip(),
            canonical_url=(
                f"https://careers.smartrecruiters.com/{company}/{posting.get('id')}"
                if posting.get("id")
                else ""
            ),
            organization=company.replace("-", " ").title(),
            provider="smartrecruiters",
            provider_req_id=posting.get("id"),
            location_text=loc_text,
            remote_signal=(
                "remote" if "remote" in name.lower() or "remote" in (loc_text or "").lower() else None
            ),
            posted_date=released[:10] or None,
            compensation_text=comp_text,
            employment_type=None,
            description_excerpt=bounded_excerpt((posting.get("mission") or ""), excerpt_chars),
        )
