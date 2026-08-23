"""Shared test fixtures: temp engine config, mock fetcher, sample sources."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from opportunity_discovery.adapters.base import FetchContext
from opportunity_discovery.config import EngineConfig, load_config
from opportunity_discovery.db import connect, migrate
from opportunity_discovery.http_client import FetchOutcome
from opportunity_discovery.models import SourceSpec

FIXTURES = Path(__file__).parent / "fixtures" / "adapters"


class MockFetcher:
    """Deterministic fetcher keyed by URL prefix -> (status, body, headers)."""

    name = "mock"

    def __init__(self, routes: dict[str, tuple[int, str] | Any] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[str] = []
        from types import SimpleNamespace

        self.cfg = SimpleNamespace(fetch=SimpleNamespace(max_retries=2,
                                                         backoff_base_seconds=0.0,
                                                         backoff_max_seconds=0.0))
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

    def fetch(self, url: str, *, extra_headers: dict[str, str] | None = None,
              use_cache_fallback: bool = True) -> FetchOutcome:
        self.calls.append(url)
        status, body, headers = self._lookup(url)
        return FetchOutcome(
            url=url, status=status, text=body,
            content_type=headers.get("content-type"),
            etag=headers.get("etag"), last_modified=headers.get("last-modified"),
            not_modified=(status == 304),
            state=("not-modified" if status == 304
                   else "ok" if status < 400
                   else "rate-limited" if status == 429 else "failed"),
            error=None if status < 400 else f"HTTP {status}",
        )

    def _post(self, url: str, json: dict | None = None, headers: dict | None = None):  # noqa: A002
        from types import SimpleNamespace

        status, body, _headers = self._lookup(url)
        return SimpleNamespace(status_code=status, text=body)

    def close(self) -> None:
        pass


@pytest.fixture()
def mock_fetcher() -> MockFetcher:
    return MockFetcher()


@pytest.fixture()
def engine_config(tmp_path: Path) -> EngineConfig:
    cfg, errors = load_config(
        base_dir=tmp_path,
        path_overrides={
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "logs_dir": str(tmp_path / "logs"),
        },
    )
    assert not errors, errors
    cfg.fetch.respect_robots = False
    cfg.sources_file = tmp_path / "sources.toml"
    # materialize a real config file so CLI --config resolution matches
    cfg.config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.config_path.write_text(
        'sources_file = "sources.toml"\n'
        "[paths]\n"
        f'data_dir = "{cfg.paths.data_dir}"\n'
        f'output_dir = "{cfg.paths.output_dir}"\n'
        f'logs_dir = "{cfg.paths.logs_dir}"\n',
        encoding="utf-8",
    )
    return cfg


def make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "test.sqlite3")
    migrate(conn)
    return conn


@pytest.fixture()
def db(tmp_path: Path):  # type: ignore[no-untyped-def]
    conn = make_db(tmp_path)
    yield conn
    conn.close()


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


def ctx_for(spec: SourceSpec, fetcher: MockFetcher) -> FetchContext:
    return FetchContext(source=spec, fetcher=fetcher, excerpt_chars=600)


def write_sources_toml(cfg: EngineConfig, sources: list[dict]) -> None:
    def toml_val(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(toml_val(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{ " + ", ".join(f"{k} = {toml_val(x)}" for k, x in v.items()) + " }"
        out = json.dumps(str(v))
        return out

    blocks = []
    for s in sources:
        lines = ["[[sources]]"]
        for key, value in s.items():
            if isinstance(value, dict):
                inner = ", ".join(f"{k} = {toml_val(v)}" for k, v in value.items())
                lines.append(f"{key} = {{ {inner} }}")
            else:
                lines.append(f"{key} = {toml_val(value)}")
        blocks.append("\n".join(lines))
    cfg.sources_file.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
