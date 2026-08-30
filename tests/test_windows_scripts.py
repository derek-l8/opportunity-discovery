"""Static contracts for Windows entry points.

These tests run on every platform. Native PowerShell execution remains a
separate integration check, but command and parameter regressions are caught.
"""

import re
from pathlib import Path

import pytest

from opportunity_discovery.cli import build_parser

REPO_ROOT = Path(__file__).parent.parent


def _script(name: str) -> str:
    return (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_installer_python_probes_use_declared_launcher_args_parameter():
    script = _script("install.ps1")
    calls = re.findall(r"Test-Python311\s+-Exe\s+[^\r\n)]+", script)

    assert len(calls) == 3
    assert all("-LauncherArgs" in call for call in calls)
    assert not re.search(r"Test-Python311\b[^\r\n]*\s-Args\b", script)


def test_scheduled_run_places_global_options_before_subcommand():
    script = _script("run.ps1")

    assert r"& .\.venv\Scripts\opdisc.exe --quiet run *>> $log" in script
    assert "opdisc.exe run --quiet" not in script


def test_scheduled_run_argument_order_matches_cli_parser():
    args = build_parser().parse_args(["--quiet", "run"])

    assert args.quiet is True
    assert args.command == "run"
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["run", "--quiet"])
    assert exc_info.value.code == 2


def test_scheduled_run_preserves_opdisc_exit_code():
    script = _script("run.ps1")

    capture = script.index("$code = $LASTEXITCODE")
    exit_statement = script.index("exit $code")
    assert capture < exit_statement
