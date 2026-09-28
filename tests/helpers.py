"""Reusable deterministic test utilities (no pytest fixtures here; see conftest.py)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from opportunity_discovery.config import EngineConfig
from opportunity_discovery.db import connect, migrate
from opportunity_discovery.http_client import FetchOutcome
from opportunity_discovery.models import SourceSpec

FIXTURES = Path(__file__).parent / "fixtures" / "adapters"


def toml_str(value: Any) -> str:
    """Serialize a value as a safely escaped TOML basic string.

    json.dumps produces a double-quoted string with identical escaping rules
    to TOML basic strings for backslashes and quotes, so Windows paths such as
    ``C:\\Users\\x`` never leak raw backslash escapes like ``\\U`` into TOML.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_str(x) for x in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {toml_str(x)}" for k, x in value.items()) + " }"
    return json.dumps(str(value))


class MockFetcher:
    """Deterministic fetcher keyed by URL prefix -> (status, body, headers)."""

    name = "mock"

    def __init__(self, routes: dict[str, tuple[int, str] | Any] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[str] = []
        from types import SimpleNamespace

        self.cfg = SimpleNamespace(
            fetch=SimpleNamespace(
                max_retries=2,
                backoff_base_seconds=0.0,
                backoff_max_seconds=0.0,
                max_response_bytes=5_000_000,
            )
        )
        self.throttle = SimpleNamespace(wait=lambda domain: None)
        self.client = SimpleNamespace(post=self._post)

    def add(self, prefix: str, status: int, body: str, headers: dict | None = None) -> None:
        self.routes[prefix] = (status, body, headers or {})

    def _lookup(self, url: str):
        for prefix, route in self.routes.items():
            if url.startswith(prefix):
                if callable(route):
                    return route(url)
                return route
        return (404, "not found", {})

    def fetch(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        use_cache_fallback: bool = True,
        allowed_hosts: set[str] | None = None,
        max_response_bytes: int | None = None,
    ) -> FetchOutcome:
        self.calls.append(url)
        status, body, headers = self._lookup(url)
        limit = max_response_bytes if max_response_bytes is not None else self.cfg.fetch.max_response_bytes
        if len(body.encode("utf-8")) > limit:
            return FetchOutcome(
                url=url,
                status=400,
                state="failed",
                error=f"response exceeded max_response_bytes={limit}",
            )
        return FetchOutcome(
            url=url,
            final_url=url,
            status=status,
            text=body,
            content_type=headers.get("content-type"),
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            not_modified=(status == 304),
            state=(
                "not-modified"
                if status == 304
                else "ok"
                if status < 400
                else "rate-limited"
                if status == 429
                else "failed"
            ),
            error=None if status < 400 else f"HTTP {status}",
        )

    def _post(self, url: str, json: dict | None = None, headers: dict | None = None):  # noqa: A002
        from types import SimpleNamespace

        status, body, _headers = self._lookup(url)
        return SimpleNamespace(status_code=status, text=body)

    def close(self) -> None:
        pass


def make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "test.sqlite3")
    migrate(conn)
    return conn


def source(**overrides: Any) -> SourceSpec:
    base = dict(
        source_id="greenhouse-acmesilicon",
        display_name="Acme Silicon",
        organization="Acme Silicon",
        adapter="greenhouse",
        endpoint_config={"board": "acmesilicon"},
        official_source=True,
        validation_status="validated",
    )
    base.update(overrides)
    return SourceSpec(**base)


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def render_engine_config_toml(cfg: EngineConfig) -> str:
    """Render the engine config TOML with paths safely quoted for any OS."""
    return (
        'sources_file = "sources.toml"\n'
        "[paths]\n"
        f"data_dir = {toml_str(cfg.paths.data_dir)}\n"
        f"output_dir = {toml_str(cfg.paths.output_dir)}\n"
        f"logs_dir = {toml_str(cfg.paths.logs_dir)}\n"
    )


def write_sources_toml(cfg: EngineConfig, sources: list[dict]) -> None:
    blocks = []
    for s in sources:
        lines = ["[[sources]]"]
        for key, value in s.items():
            lines.append(f"{key} = {toml_str(value)}")
        blocks.append("\n".join(lines))
    cfg.sources_file.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
