"""Lever public postings adapter.

Public endpoint (no credentials):
    https://api.lever.co/v0/postings/{org}?mode=json
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter


@register_adapter("lever")
class LeverAdapter:
    name = "lever"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        org = ctx.source.endpoint_config.get("board") or ctx.source.endpoint_config.get("org")
        if not org:
            return AdapterResult(ok=False, state="check-failed",
                                 detail="lever adapter requires endpoint_config.board")
        url = f"https://api.lever.co/v0/postings/{org}?mode=json"
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304,
                                 detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        try:
            data = json.loads(out.text or "")
        except (ValueError, json.JSONDecodeError) as exc:
            return AdapterResult(ok=False, state="format-changed", detail=f"bad JSON: {exc}",
                                 http_status=out.status)
        if not isinstance(data, list):
            return AdapterResult(ok=False, state="format-changed", detail="expected a JSON array",
                                 http_status=out.status)
        records = []
        for posting in data:
            categories = posting.get("categories") or {}
            loc = categories.get("location") or None
            created = posting.get("createdAt")
            posted = None
            if isinstance(created, (int, float)):
                posted = (
                    datetime.fromtimestamp(created / 1000, tz=UTC).date().isoformat()
                )
            workplace = (posting.get("workplaceType") or "").lower() or None
            records.append(
                RawOpportunity(
                    title=(posting.get("text") or "").strip(),
                    canonical_url=posting.get("hostedUrl"),
                    organization=org.replace("-", " ").title(),
                    provider="lever",
                    provider_req_id=posting.get("id"),
                    location_text=loc,
                    remote_signal=("remote" if workplace == "remote"
                                   else "hybrid" if workplace == "hybrid" else None),
                    posted_date=posted,
                    employment_type=(
                        "internship" if "intern" in (posting.get("text") or "").lower()
                        else (categories.get("commitment") or "").lower() or None
                    ),
                    description_excerpt=bounded_excerpt(posting.get("description"), ctx.excerpt_chars),
                    extra={"workplaceType": workplace} if workplace else {},
                )
            )
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)
