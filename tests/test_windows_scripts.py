"""Static and native-Windows contracts for Windows entry points."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from opportunity_discovery.cli import build_parser
from opportunity_discovery.workspace import initialize_workspace

REPO_ROOT = Path(__file__).parent.parent


def _script(name: str) -> str:
    return (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_installer_python_probes_use_declared_launcher_args_parameter():
    script = _script("install.ps1")
    calls = re.findall(r"Test-Python311\s+-Exe\s+[^\r\n)]+", script)

    assert len(calls) == 2
    assert all("-LauncherArgs" in call for call in calls)
    assert not re.search(r"Test-Python311\b[^\r\n]*\s-Args\b", script)


def _run_installer(tmp_path: Path, py_shim: str | None, *, probe_only: bool = True):
    if sys.platform != "win32":
        pytest.skip("native PowerShell regression test")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    if py_shim not in (None, "NO_PATH_PYTHON"):
        (shim_dir / "py.cmd").write_text(py_shim, encoding="ascii")
    env = os.environ.copy()
    env["PATH"] = (
        str(shim_dir)
        if py_shim == "NO_PATH_PYTHON"
        else os.pathsep.join((str(shim_dir), str(Path(sys.executable).parent), env["PATH"]))
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REPO_ROOT / "scripts" / "install.ps1"),
        "-VenvPath",
        str(tmp_path / "venv"),
    ]
    if probe_only:
        command.append("-ProbeOnly")
    return subprocess.run(command, text=True, capture_output=True, env=env, check=False)


def test_installer_falls_back_from_unavailable_314_to_312(tmp_path):
    result = _run_installer(
        tmp_path,
        '@echo off\r\nif "%1"=="-3.12" if "%2"=="-c" exit /b 0\r\nexit /b 1\r\n',
    )

    assert result.returncode == 0, result.stderr
    assert "Using Python: py -3.12" in result.stdout


def test_installer_falls_back_to_python_on_path(tmp_path):
    result = _run_installer(tmp_path, "@echo off\r\nexit /b 1\r\n")

    assert result.returncode == 0, result.stderr
    assert "Using Python:" in result.stdout
    assert "python.exe" in result.stdout.lower()


def test_installer_reports_all_routes_when_none_are_compatible(tmp_path):
    result = _run_installer(tmp_path, "NO_PATH_PYTHON")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "No compatible Python interpreter found" in output
    assert "py -3.14, py -3.13, py -3.12, py -3.11, python.exe on PATH" in output


def test_installer_keeps_venv_creation_failure_fatal(tmp_path):
    result = _run_installer(
        tmp_path,
        '@echo off\r\nif "%2"=="-c" exit /b 0\r\nexit /b 23\r\n',
        probe_only=False,
    )

    assert result.returncode != 0
    assert "Virtual environment creation failed with exit code 23" in (result.stdout + result.stderr)


def test_installer_prompts_with_documents_workspace_default_and_supports_opt_out():
    script = _script("install.ps1")

    assert '[Environment]::GetFolderPath("MyDocuments")' in script
    assert 'Join-Path $documents "Opportunity-Workspace"' in script
    assert 'Read-Host "Private workspace location [$defaultWorkspace]"' in script
    assert "[switch]$SkipWorkspaceSetup" in script
    assert "& $venvOpdisc init-workspace $WorkspacePath --engine-path $repoRoot" in script
    assert "git clone" not in script
    assert "Copy-Item" not in script
    assert "Move-Item" not in script


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


def test_dashboard_script_uses_the_recorded_engine_and_installed_command():
    script = _script("open-dashboard.ps1")
    assert "$metadata.engine_path" in script
    assert "Set-Location -LiteralPath $engine" in script
    assert "& $opdisc workspace-dashboard $workspace" in script
    assert "exit $LASTEXITCODE" in script
    assert "git clone" not in script


def _run_dashboard_launcher(root: Path):
    if sys.platform != "win32":
        pytest.skip("native Windows dashboard launcher test")
    return subprocess.run(
        f'cmd.exe /d /s /c ""{root / "Open Dashboard.cmd"}""',
        input="\n",
        text=True,
        capture_output=True,
        check=False,
    )


def test_dashboard_launcher_handles_spaces_and_resolves_changed_engine(tmp_path):
    if sys.platform != "win32":
        pytest.skip("native Windows dashboard launcher test")
    root = tmp_path / "workspace & student's files"
    for name in ("first-engine", "next-engine"):
        engine = tmp_path / (name + " with spaces")
        (engine / "scripts").mkdir(parents=True)
        (engine / "scripts" / "open-dashboard.ps1").write_text(
            "param([string]$WorkspacePath)\n"
            f"Write-Output '{name}'\n"
            "Write-Output $WorkspacePath.TrimEnd([char]92)\n"
            "exit 0\n"
        )
        initialize_workspace(root, engine_path=engine)
        result = _run_dashboard_launcher(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert name in result.stdout
        assert str(root) in result.stdout


def test_dashboard_launcher_keeps_failure_visible_and_returns_exit_code(tmp_path):
    if sys.platform != "win32":
        pytest.skip("native Windows dashboard launcher test")
    root = tmp_path / "workspace"
    engine = tmp_path / "engine"
    (engine / "scripts").mkdir(parents=True)
    (engine / "scripts" / "open-dashboard.ps1").write_text(
        "param([string]$WorkspacePath)\nWrite-Output 'Setup needed'\nexit 7\n"
    )
    initialize_workspace(root, engine_path=engine)
    result = _run_dashboard_launcher(root)
    assert result.returncode == 7, result.stdout + result.stderr
    assert "Setup needed" in result.stdout


def test_dashboard_script_reports_missing_installation(tmp_path):
    if sys.platform != "win32":
        pytest.skip("native Windows dashboard launcher test")
    root = tmp_path / "workspace"
    engine = tmp_path / "engine"
    engine.mkdir()
    initialize_workspace(root, engine_path=engine)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "open-dashboard.ps1"),
            "-WorkspacePath",
            str(root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Run scripts\\install.ps1" in result.stdout
