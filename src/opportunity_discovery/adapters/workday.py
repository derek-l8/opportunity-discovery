"""Workday CXS public adapter for explicitly configured tenants/sites.

Public endpoint pattern (no credentials):
    POST https://{tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    body: {"limit":20,"offset":0,"searchText":""}

Only configured tenants/sites are contacted; no tenant discovery is performed.
"""

from __future__ import annotations

import json
import re
import time as _time
from urllib.parse import urlsplit

from ..models import AdapterResult, RawOpportunity
from .base import register_adapter

_PAGE = 20
_MAX_PAGES = 25
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


@register_adapter("workday")
class WorkdayAdapter:
    name = "workday"

    def run(self, ctx) -> AdapterResult:  # type: ignore[no-untyped-def]
        cfg = ctx.source.endpoint_config
        base = cfg.get("url")  # e.g. https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternal
        if not base:
            return AdapterResult(
                ok=False, state="check-failed", detail="workday adapter requires endpoint_config.url"
            )
        parts = urlsplit(base)
        host_m = re.match(
            r"^(?:www\.)?(?P<tenant>[^.]+)\.(?P<host>wd\d+\.myworkday(?:jobs|sites)\.com)$",
            parts.hostname or "",
        )
        path_parts = [p for p in parts.path.split("/") if p]
        site = cfg.get("site") or (path_parts[-1] if path_parts else None)
        if not host_m or not site:
            return AdapterResult(
                ok=False, state="check-failed", detail=f"cannot determine workday tenant/site from {base}"
            )
        tenant = cfg.get("tenant") or host_m.group("tenant")
        api = f"https://{host_m.group('tenant')}.{host_m.group('host')}/wday/cxs/{tenant}/{site}/jobs"
        records: list[RawOpportunity] = []
        offset = 0
        status: int | None = None
        headers = {"Content-Type": "application/json"}
        backoff = max(ctx.fetcher.cfg.fetch.backoff_base_seconds, 1.0)
        for _page in range(_MAX_PAGES):
            attempt = 0
            data: dict | None = None
            while True:
                attempt += 1
                ctx.fetcher.throttle.wait(urlsplit(api).hostname or "")
                try:
                    resp = ctx.fetcher.client.post(
                        api,
                        json={"limit": _PAGE, "offset": offset, "searchText": ""},
                        headers=headers,
                    )
                except Exception as exc:
                    return AdapterResult(
                        ok=False, state="check-failed", detail=f"workday request failed: {exc}"
                    )
                status = resp.status_code
                if status in _RETRY_STATUS and attempt <= ctx.fetcher.cfg.fetch.max_retries:
                    _time.sleep(backoff)
                    backoff = min(backoff * 2, ctx.fetcher.cfg.fetch.backoff_max_seconds)
                    continue
                break
            if status == 429:
                return AdapterResult(
                    ok=False, state="rate-limited", http_status=status, detail="HTTP 429 from workday CXS"
                )
            if status != 200:
                state = "format-changed" if status in (404, 410) else "check-failed"
                return AdapterResult(
                    ok=False, state=state, http_status=status, detail=f"HTTP {status} from {api}"
                )
            try:
                data = json.loads(resp.text)
            except ValueError as exc:
                return AdapterResult(
                    ok=False, state="format-changed", detail=f"bad JSON: {exc}", http_status=status
                )
            total = int(data.get("total") or 0)
            postings = data.get("jobPostings") or []
            for posting in postings:
                records.append(self._record(posting, base, tenant, ctx.excerpt_chars))
            offset += _PAGE
            if offset >= total or not postings:
                break
        return AdapterResult(ok=True, records=records, empty_ok=True, http_status=status)

    def _record(self, posting: dict, base: str, tenant: str, excerpt_chars: int) -> RawOpportunity:
        title = posting.get("title") or ""
        locations = posting.get("locationsText") or posting.get("location") or ""
        external_path = posting.get("externalPath") or ""
        canonical = f"{base.rstrip('/')}/job/{external_path.lstrip('/')}" if external_path else base
        req_id = None
        bullet_fields = posting.get("bulletFields")
        if isinstance(bullet_fields, list) and bullet_fields:
            req_id = str(bullet_fields[-1])
        elif external_path:
            req_id = external_path.rsplit("/", 1)[-1]
        posted_on = posting.get("postedOn") or ""
        return RawOpportunity(
            title=title.strip(),
            canonical_url=canonical,
            organization=tenant.replace("-", " ").title(),
            provider="workday",
            provider_req_id=req_id,
            location_text=str(locations) if locations else None,
            remote_signal="remote" if "remote" in str(locations).lower() else None,
            employment_type="internship" if "intern" in title.lower() else None,
            description_excerpt=None,
            extra={"raw_posted_on": posted_on},
        )
