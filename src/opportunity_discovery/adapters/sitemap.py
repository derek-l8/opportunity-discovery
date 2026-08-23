"""Bounded sitemap/index adapter for clearly public program indexes.

endpoint_config:
    url: https://example.org/sitemap.xml
    include_regex: "/opportunities/"      # only URLs matching are kept
    exclude_regex: "/(tag|category)/"     # optional
"""
from __future__ import annotations

import re

from ..models import AdapterResult, RawOpportunity
from ..urlnorm import humanize_slug
from .base import outcome_to_result, register_adapter

_MAX_URLS = 300
_NS_TAG = re.compile(r"\{[^}]+\}")


@register_adapter("sitemap")
class SitemapAdapter:
    name = "sitemap"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        url = cfg.get("url")
        if not url:
            return AdapterResult(ok=False, state="check-failed",
                                 detail="sitemap adapter requires endpoint_config.url")
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304,
                                 detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        from xml.etree import ElementTree

        try:
            root = ElementTree.fromstring(out.text or "")
        except ElementTree.ParseError as exc:
            return AdapterResult(ok=False, state="format-changed", detail=f"XML parse error: {exc}",
                                 http_status=out.status)
        include = re.compile(cfg["include_regex"]) if cfg.get("include_regex") else None
        exclude = re.compile(cfg["exclude_regex"]) if cfg.get("exclude_regex") else None
        records: list[RawOpportunity] = []
        for loc_el in root.iter():
            tag = _NS_TAG.sub("", loc_el.tag)
            if tag != "loc":
                continue
            loc = (loc_el.text or "").strip()
            if not loc.startswith("http"):
                continue
            if include and not include.search(loc):
                continue
            if exclude and exclude.search(loc):
                continue
            slug = [seg for seg in loc.split("/") if seg][-1]
            base = re.sub(r"\.(html?|php|aspx?)$", "", slug)
            records.append(
                RawOpportunity(
                    title=humanize_slug(base),
                    canonical_url=loc,
                    organization=ctx.source.organization,
                    provider=None,
                    evidence="inferred-signal",  # title inferred from URL slug
                )
            )
            if len(records) >= _MAX_URLS:
                break
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=out.status)
