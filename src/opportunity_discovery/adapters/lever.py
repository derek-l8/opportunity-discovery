"""Lever public postings adapter.

Public endpoint (no credentials):
    https://api.lever.co/v0/postings/{org}?mode=json
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from ..extraction import description_location, extract_description
from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter

_PAGE_SIZE = 100
_MAX_PAGES = 25


@register_adapter("lever")
class LeverAdapter:
    name = "lever"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        org = ctx.source.endpoint_config.get("board") or ctx.source.endpoint_config.get("org")
        if not org:
            return AdapterResult(
                ok=False, state="check-failed", detail="lever adapter requires endpoint_config.board"
            )
        postings: list[dict] = []
        seen_ids: set[str] = set()
        pages_fetched = 0
        status: int | None = None
        for page in range(_MAX_PAGES):
            url = (
                f"https://api.lever.co/v0/postings/{org}"
                f"?mode=json&skip={page * _PAGE_SIZE}&limit={_PAGE_SIZE}"
            )
            out = ctx.fetcher.fetch(url)
            status = out.status or status
            if out.not_modified and not out.text:
                return AdapterResult(
                    ok=False,
                    state="check-failed",
                    detail=f"HTTP 304 without cached page {page + 1}",
                    http_status=304,
                    pages_fetched=pages_fetched,
                    truncated=True,
                )
            if not out.ok:
                failed = outcome_to_result(out)
                failed.pages_fetched = pages_fetched
                failed.truncated = True
                return failed
            pages_fetched += 1
            try:
                data = json.loads(out.text or "")
            except (ValueError, json.JSONDecodeError) as exc:
                return AdapterResult(
                    ok=False,
                    state="format-changed",
                    detail=f"bad JSON on page {page + 1}: {exc}",
                    http_status=out.status,
                    pages_fetched=pages_fetched,
                    truncated=True,
                )
            if not isinstance(data, list) or len(data) > _PAGE_SIZE:
                return AdapterResult(
                    ok=False,
                    state="format-changed",
                    detail=f"invalid or oversized JSON page {page + 1}",
                    http_status=out.status,
                    pages_fetched=pages_fetched,
                    truncated=True,
                )
            for posting in data:
                if (
                    not isinstance(posting, dict)
                    or not isinstance(posting.get("id"), str)
                    or not posting["id"]
                    or not isinstance(posting.get("hostedUrl"), str)
                    or not posting["hostedUrl"]
                ):
                    return AdapterResult(
                        ok=False,
                        state="format-changed",
                        detail=f"page {page + 1} has a posting without ID or hosted URL",
                        http_status=out.status,
                        pages_fetched=pages_fetched,
                        truncated=True,
                    )
                posting_id = posting["id"]
                if posting_id in seen_ids:
                    return AdapterResult(
                        ok=False,
                        state="coverage-warning",
                        detail=f"duplicate posting ID across pages: {posting_id}",
                        http_status=out.status,
                        pages_fetched=pages_fetched,
                        truncated=True,
                    )
                seen_ids.add(posting_id)
                postings.append(posting)
            if len(data) < _PAGE_SIZE:
                break
        else:
            return AdapterResult(
                ok=False,
                state="coverage-warning",
                detail=f"Lever pagination exceeded {_MAX_PAGES} pages",
                http_status=status,
                pages_fetched=pages_fetched,
                truncated=True,
            )
        records = []
        for posting in postings:
            sections = posting.get("lists") or []
            section_text = "\n".join(
                str(section.get("text") or "") + "\n" + str(section.get("content") or "")
                for section in sections
                if isinstance(section, dict)
            )
            content = "\n".join(
                str(posting.get(key) or "")
                for key in ("description", "descriptionPlain", "additional", "additionalPlain")
            )
            facts = extract_description(content, qualification_sections=section_text)
            categories = posting.get("categories") or {}
            loc = categories.get("location") or description_location(content) or None
            created = posting.get("createdAt")
            posted = None
            if isinstance(created, (int, float)):
                posted = datetime.fromtimestamp(created / 1000, tz=UTC).date().isoformat()
            workplace = (posting.get("workplaceType") or "").lower() or None
            records.append(
                RawOpportunity(
                    title=(posting.get("text") or "").strip(),
                    canonical_url=str(posting["hostedUrl"]),
                    organization=org.replace("-", " ").title(),
                    provider="lever",
                    provider_req_id=posting.get("id"),
                    location_text=loc,
                    remote_signal=(
                        "remote" if workplace == "remote" else "hybrid" if workplace == "hybrid" else None
                    ),
                    posted_date=posted,
                    employment_type=(
                        "internship"
                        if re.search(r"\bintern(?:ship)?\b", posting.get("text") or "", re.I)
                        else (categories.get("commitment") or "").lower() or None
                    ),
                    description_excerpt=bounded_excerpt(
                        facts["requirements_text"] or content, ctx.excerpt_chars
                    ),
                    **facts,
                    extra={"requirements_extracted": True, "workplaceType": workplace},
                )
            )
        return AdapterResult(
            ok=True,
            records=records,
            empty_ok=True,
            http_status=status,
            pages_fetched=pages_fetched,
            truncated=False,
        )
