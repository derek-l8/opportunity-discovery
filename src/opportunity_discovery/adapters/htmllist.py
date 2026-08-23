"""Explicitly configured HTML list-page adapter (bounded, source-specific selectors).

endpoint_config:
    url: https://example.org/programs
    item_selector: "ul.programs li"
    title_selector: "h3 a"          # optional; falls back to item text
    link_attribute: href            # optional
    deadline_selector: ".deadline"  # optional
"""
from __future__ import annotations

import re

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter


@register_adapter("htmllist")
class HtmlListAdapter:
    name = "htmllist"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        url = cfg.get("url")
        item_selector = cfg.get("item_selector")
        if not url or not item_selector:
            return AdapterResult(ok=False, state="check-failed",
                                 detail="htmllist adapter requires endpoint_config.url and item_selector")
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304,
                                 detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        from bs4 import BeautifulSoup
        from bs4.element import Tag

        soup = BeautifulSoup(out.text or "", "html.parser")
        items = soup.select(item_selector)
        if not items:
            return AdapterResult(ok=False, state="format-changed",
                                 detail=f"selector '{item_selector}' matched nothing",
                                 http_status=out.status)
        title_sel = cfg.get("title_selector")
        deadline_sel = cfg.get("deadline_selector")
        base_url = url
        records: list[RawOpportunity] = []
        for item in items[:200]:  # bounded
            link_el = None
            title = ""
            if title_sel:
                el = item.select_one(title_sel)
                if el is None:
                    continue
                link_el = el if el.name == "a" else el.find("a")
                title = el.get_text(strip=True)
            else:
                link_el = item.find("a")
                title = item.get_text(strip=True)
            href_attr = str(cfg.get("link_attribute", "href"))
            if (not title or link_el is None
                    or not isinstance(link_el, Tag) or not link_el.get(href_attr)):
                continue
            from urllib.parse import urljoin

            link = urljoin(base_url, str(link_el.get(href_attr)))
            deadline = None
            if deadline_sel:
                d_el = item.select_one(deadline_selector_safe(deadline_sel))
                if d_el:
                    m = re.search(r"\d{4}-\d{2}-\d{2}", d_el.get_text(" ", strip=True))
                    deadline = m.group(0) if m else None
            records.append(
                RawOpportunity(
                    title=title,
                    canonical_url=link,
                    organization=ctx.source.organization,
                    provider=None,
                    deadline=deadline,
                    description_excerpt=bounded_excerpt(
                        item.get_text(" ", strip=True), min(ctx.excerpt_chars, 400)
                    ),
                )
            )
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)


def deadline_selector_safe(sel: str) -> str:
    """Selectors are source-specific config; pass through unchanged (kept for clarity)."""
    return sel
