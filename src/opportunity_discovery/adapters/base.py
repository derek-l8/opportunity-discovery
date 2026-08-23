"""Adapter interface and registry.

An adapter turns one fetched public payload into RawOpportunity records.
Adapters must distinguish a *valid empty result* from a *failure*; a network
or parser failure must never be reported as zero opportunities.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import constants as c
from ..http_client import Fetcher, FetchOutcome
from ..models import AdapterResult, SourceSpec

log = logging.getLogger(__name__)

DEFAULT_EXCERPT_CHARS = 600


@dataclass
class FetchContext:
    source: SourceSpec
    fetcher: Fetcher
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS
    extra: dict[str, Any] = field(default_factory=dict)


class Adapter(Protocol):
    name: str

    def run(self, ctx: FetchContext) -> AdapterResult: ...


def bounded_excerpt(text: str | None, limit: int = DEFAULT_EXCERPT_CHARS) -> str | None:
    """Strip markup and bound length; never returns full copyrighted pages."""
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned or None
    return cleaned[: limit - 3].rstrip() + "..."


def outcome_to_result(url_outcome: FetchOutcome) -> AdapterResult:
    """Translate a transport failure into an AdapterResult (never empty-ok)."""
    state_map = {
        c.HEALTH_RATE_LIMITED: c.HEALTH_RATE_LIMITED,
        "robots-blocked": c.HEALTH_CHECK_FAILED,
        "failed": c.HEALTH_CHECK_FAILED,
        "degraded": c.HEALTH_DEGRADED,
        "not-modified": c.HEALTH_HEALTHY,
    }
    return AdapterResult(
        ok=False,
        state=state_map.get(url_outcome.state, c.HEALTH_CHECK_FAILED),
        detail=url_outcome.error or f"HTTP {url_outcome.status}",
        http_status=url_outcome.status,
    )


def parse_json_body(result_body: str | None) -> Any:
    if not result_body or not result_body.strip():
        raise ValueError("empty response body")
    return json.loads(result_body)


REGISTRY: dict[str, Callable[[], Adapter]] = {}


def register_adapter(name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        REGISTRY[name] = cls  # type: ignore[assignment]
        cls.name = name  # type: ignore[attr-defined]
        return cls

    return deco


def get_adapter(name: str) -> Adapter:
    try:
        factory = REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown adapter: {name}") from None
    adapter = factory()
    adapter.name = name
    return adapter


def run_source(source: SourceSpec, fetcher: Fetcher, *,
               excerpt_chars: int = DEFAULT_EXCERPT_CHARS) -> AdapterResult:
    """Run one source through its adapter with full failure isolation."""
    ctx = FetchContext(source=source, fetcher=fetcher, excerpt_chars=excerpt_chars)
    try:
        adapter = get_adapter(source.adapter)
    except ValueError as exc:
        return AdapterResult(ok=False, state=c.HEALTH_CHECK_FAILED, detail=str(exc))
    try:
        result = adapter.run(ctx)
    except Exception as exc:  # isolation boundary
        log.warning("adapter %s failed for %s: %s", source.adapter, source.source_id, exc)
        return AdapterResult(ok=False, state=c.HEALTH_CHECK_FAILED,
                             detail=f"adapter error: {type(exc).__name__}: {exc}")
    if (
        result.ok
        and not result.records
        and not result.empty_ok
        and result.http_status != 304
    ):
        # Parser ran but found nothing it recognized: treat as format drift.
        # A 304 Not-Modified is a *successful* unchanged response, never drift.
        result.ok = False
        result.state = c.HEALTH_FORMAT_CHANGED
        result.detail = result.detail or "no recognizable records in response"
    return result
