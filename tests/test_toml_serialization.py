"""Regression: TOML serialization must escape backslashes (Windows-safe paths).

Raw interpolation of a Windows path such as ``C:\\Users\\x`` into a TOML
double-quoted string makes ``tomllib`` interpret ``\\U`` as a unicode escape
(``TOMLDecodeError: Invalid hex value``). All generated TOML must go through
``tests.helpers.toml_str``, which JSON-escapes the value.
"""

from __future__ import annotations

import tomllib
from types import SimpleNamespace

import pytest

from tests.helpers import render_engine_config_toml, toml_str, write_sources_toml

WINDOWS_PATHS = [
    "C:\\Users\\opdisc\\AppData\\Local\\Temp\\pytest\\data",
    "D:\\repo\\output\\",
    "\\\\server\\share\\logs",  # UNC path
]


def test_toml_str_round_trips_windows_paths() -> None:
    for value in WINDOWS_PATHS:
        line = f"path = {toml_str(value)}"
        assert tomllib.loads(line)["path"] == value


def test_render_engine_config_toml_loads_with_windows_paths() -> None:
    cfg = SimpleNamespace(
        paths=SimpleNamespace(
            data_dir=WINDOWS_PATHS[0],
            output_dir=WINDOWS_PATHS[1],
            logs_dir=WINDOWS_PATHS[2],
        )
    )
    parsed = tomllib.loads(render_engine_config_toml(cfg))
    assert parsed["paths"]["data_dir"] == WINDOWS_PATHS[0]
    assert parsed["paths"]["output_dir"] == WINDOWS_PATHS[1]
    assert parsed["paths"]["logs_dir"] == WINDOWS_PATHS[2]
    assert "\\" in parsed["paths"]["data_dir"]  # backslash survived verbatim


def test_write_sources_toml_handles_windows_style_values(engine_config, tmp_path) -> None:
    write_sources_toml(
        engine_config,
        [
            {
                "source_id": "greenhouse-acme-win",
                "display_name": 'Acme "Windows" Board',
                "organization": "Acme Silicon",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "acme", "local_path": WINDOWS_PATHS[0]},
                "official_source": True,
                "validation_status": "validated",
            },
        ],
    )
    raw = engine_config.sources_file.read_text(encoding="utf-8")
    assert '"C:\\\\Users' in raw  # backslashes are doubled in the file, not raw
    parsed = tomllib.loads(raw)
    src = parsed["sources"][0]
    assert src["endpoint_config"]["local_path"] == WINDOWS_PATHS[0]
    assert src["display_name"] == 'Acme "Windows" Board'


def test_raw_windows_path_interpolation_is_invalid_toml() -> None:
    # Documents the defect: naive f-string interpolation of a Windows path
    # produces TOML that fails to parse. Guards against regressing to it.
    bad = f'path = "{WINDOWS_PATHS[0]}"'
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(bad)
