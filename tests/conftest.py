"""Shared pytest fixtures. Reusable utilities live in tests.helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from opportunity_discovery.config import EngineConfig, load_config
from tests.helpers import make_db, render_engine_config_toml


@pytest.fixture()
def mock_fetcher():
    from tests.helpers import MockFetcher

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
    cfg.config_path.write_text(render_engine_config_toml(cfg), encoding="utf-8")
    return cfg


@pytest.fixture()
def db(tmp_path: Path):  # type: ignore[no-untyped-def]
    conn = make_db(tmp_path)
    yield conn
    conn.close()
