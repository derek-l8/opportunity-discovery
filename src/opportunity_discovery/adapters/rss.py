"""RSS / Atom feed adapter."""

from __future__ import annotations

import email.utils

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter


def _to_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return value[:10] if isinstance(value, str) else None


@register_adapter("rss")
class RssAdapter:
    name = "rss"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        url = cfg.get("url")
        if not url:
            return AdapterResult(
                ok=False, state="check-failed", detail="rss adapter requires endpoint_config.url"
            )
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304, detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        import feedparser

        parsed = feedparser.parse(out.text or "")
        if parsed.bozo and not parsed.entries:
            return AdapterResult(
                ok=False,
                state="format-changed",
                detail=f"feed parse error: {parsed.bozo_exception}",
                http_status=out.status,
            )
        records: list[RawOpportunity] = []
        for entry in parsed.entries:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            published = _to_date(entry.get("published") or entry.get("updated"))
            summary = entry.get("summary")
            records.append(
                RawOpportunity(
                    title=str(title).strip(),
                    canonical_url=str(link).strip(),
                    organization=ctx.source.organization,
                    provider=None,
                    location_text=entry.get("location") or None,
                    posted_date=published,
                    deadline=_to_date(entry.get("deadline")),
                    description_excerpt=bounded_excerpt(summary, ctx.excerpt_chars),
                )
            )
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)
