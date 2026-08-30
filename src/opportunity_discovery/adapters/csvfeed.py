"""Configurable public CSV feed adapter (including GitHub-hosted CSV lists).

endpoint_config:
    url: https://raw.githubusercontent.com/.../file.csv
    delimiter: ","            # optional
    columns:
        title: Role
        canonical_url: Application/Link
        organization: Company
        location_text: Location
        season: Term
"""

from __future__ import annotations

import csv
import io

from ..models import AdapterResult, RawOpportunity
from .base import bounded_excerpt, outcome_to_result, register_adapter

_DEFAULT_COLUMNS = {
    "title": "title",
    "canonical_url": "url",
    "organization": "company",
    "location_text": "location",
    "season": "season",
    "deadline": "deadline",
    "compensation_text": "compensation",
}


@register_adapter("csvfeed")
class CsvFeedAdapter:
    name = "csvfeed"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        url = cfg.get("url")
        if not url:
            return AdapterResult(
                ok=False, state="check-failed", detail="csvfeed adapter requires endpoint_config.url"
            )
        out = ctx.fetcher.fetch(url)
        if out.not_modified and not out.text:
            # Unchanged upstream but no cached body available.
            return AdapterResult(ok=True, empty_ok=True, http_status=304, detail="not modified")
        # A 304 carries the cached body in out.text; parse it like a normal
        # response so observations continue and closures stay accurate.
        if not out.ok:
            return outcome_to_result(out)
        text = out.text or ""
        delimiter = cfg.get("delimiter", ",")
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
        except csv.Error as exc:
            return AdapterResult(
                ok=False, state="format-changed", detail=f"CSV parse error: {exc}", http_status=out.status
            )
        if not rows and not text.strip():
            return AdapterResult(
                ok=True, records=[], empty_ok=True, http_status=out.status, detail="empty csv"
            )
        columns = {**_DEFAULT_COLUMNS, **(cfg.get("columns") or {})}

        def col(row: dict, logical: str):
            name = columns.get(logical)
            if not name:
                return None
            # case-insensitive header lookup
            for key in row:
                if key and key.strip().lower() == str(name).strip().lower():
                    value = row[key]
                    return str(value).strip() or None
            return None

        records: list[RawOpportunity] = []
        for row in rows:
            title = col(row, "title")
            link = col(row, "canonical_url")
            if not title or not link:
                continue
            records.append(
                RawOpportunity(
                    title=title,
                    canonical_url=link,
                    organization=col(row, "organization"),
                    provider=None,
                    provider_req_id=col(row, "provider_req_id"),
                    location_text=col(row, "location_text"),
                    posted_date=col(row, "posted_date"),
                    deadline=(col(row, "deadline") or None),
                    compensation_text=col(row, "compensation_text"),
                    relocation_text=col(row, "relocation_text"),
                    description_excerpt=bounded_excerpt(col(row, "description_excerpt"), ctx.excerpt_chars),
                    season=col(row, "season"),
                    employment_type=col(row, "employment_type"),
                )
            )
        # If the file parsed but yielded nothing while having rows -> format drift.
        empty_ok = len(records) > 0 or len(rows) == 0
        return AdapterResult(
            ok=empty_ok,
            records=records,
            empty_ok=True,
            state="healthy" if empty_ok else "format-changed",
            detail=None if empty_ok else "rows present but no recognizable columns",
            http_status=out.status,
        )
