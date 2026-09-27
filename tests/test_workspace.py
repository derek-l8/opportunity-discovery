"""Phase 3 private-workspace initialization contracts."""

import json
from pathlib import Path

from opportunity_discovery.cli import main
from opportunity_discovery.workspace import initialize_workspace

DEMO = Path(__file__).parent / "fixtures" / "demo" / "phase3-workspace.json"


def test_initializer_builds_synthetic_fixed_layout(tmp_path):
    fixture = json.loads(DEMO.read_text(encoding="utf-8"))
    root = tmp_path / "Opportunity-Workspace"
    engine = root / "engine" / "opportunity-discovery"
    engine.mkdir(parents=True)
    (engine / ".git").mkdir()

    result = initialize_workspace(root)

    assert all((root / relative).is_dir() for relative in fixture["expected_directories"])
    assert set(result.created_files) == set(fixture["expected_starter_files"])
    assert all((root / relative).is_file() for relative in fixture["expected_starter_files"])
    metadata = json.loads((root / ".opdisc" / "workspace.json").read_text(encoding="utf-8"))
    assert metadata["engine_path"] == str(engine.resolve())
    assert metadata["private_state_root"] == str(root.resolve())
    assert metadata["custom"] == {}
    assert result.warnings == ()
    manifest = json.loads((root / ".opdisc" / "source-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": "1.0",
        "imports": [],
        "external_references": [],
        "custom": {},
    }
    assert "Read `WORKSPACE.md`" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "explicitly designates" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == (root / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert ".opdisc/workspace.json" in (root / "WORKSPACE.md").read_text(encoding="utf-8")


def test_external_engine_is_recorded_and_does_not_create_false_canonical_directory(tmp_path):
    root = tmp_path / "workspace"
    engine = tmp_path / "external-engine"
    engine.mkdir()

    result = initialize_workspace(root, engine_path=engine)

    assert not (root / "engine" / "opportunity-discovery").exists()
    metadata = json.loads((root / ".opdisc" / "workspace.json").read_text(encoding="utf-8"))
    assert metadata["engine_path"] == str(engine.resolve())
    assert any("agent opened only at the workspace root" in warning for warning in result.warnings)


def test_initializer_preserves_user_owned_files_and_unknown_custom_metadata(tmp_path):
    fixture = json.loads(DEMO.read_text(encoding="utf-8"))
    root = tmp_path / "workspace"
    canonical_engine = root / "engine" / "opportunity-discovery"
    canonical_engine.mkdir(parents=True)
    initialize_workspace(root)
    (root / "WORKSPACE.md").write_text("# My instructions\n", encoding="utf-8")
    (root / "CLAUDE.md").unlink()
    manifest_path = root / ".opdisc" / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["custom"] = fixture["custom_manifest_example"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    workspace_path = root / ".opdisc" / "workspace.json"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    workspace["custom"] = fixture["custom_workspace_example"]
    workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
    external_engine = tmp_path / "different-engine"
    external_engine.mkdir()

    result = initialize_workspace(root, engine_path=external_engine)

    assert result.created_files == ()
    assert result.updated_files == (".opdisc/workspace.json",)
    assert set(result.preserved_files) == set(fixture["expected_starter_files"]) - {
        "CLAUDE.md",
        ".opdisc/workspace.json",
    }
    assert (root / "WORKSPACE.md").read_text(encoding="utf-8") == "# My instructions\n"
    assert not (root / "CLAUDE.md").exists()
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["custom"] == fixture["custom_manifest_example"]
    )
    updated_workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    assert updated_workspace["custom"] == fixture["custom_workspace_example"]
    assert updated_workspace["engine_path"] == str(external_engine.resolve())


def test_initializer_warns_when_workspace_is_inside_git(tmp_path):
    (tmp_path / ".git").mkdir()
    engine = tmp_path / "private" / "engine" / "opportunity-discovery"
    engine.mkdir(parents=True)

    result = initialize_workspace(tmp_path / "private")

    assert len(result.warnings) == 1
    assert "inside Git checkout" in result.warnings[0]


def test_initializer_rejects_nonexistent_explicit_engine_without_creating_workspace(tmp_path):
    root = tmp_path / "workspace"

    try:
        initialize_workspace(root, engine_path=tmp_path / "missing-engine")
    except ValueError as exc:
        assert "explicit engine path is not an existing directory" in str(exc)
    else:  # pragma: no cover - failure path assertion
        raise AssertionError("missing engine path was accepted")
    assert not root.exists()


def test_init_workspace_cli_json(tmp_path, capsys):
    root = tmp_path / "workspace"
    engine = tmp_path / "external-engine"
    engine.mkdir()

    assert main(["--json", "init-workspace", str(root), "--engine-path", str(engine)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["workspace"] == str(root.resolve())
    assert len(payload["created_files"]) == 7
    assert len(payload["warnings"]) == 1


def test_init_workspace_rejects_file_path(tmp_path, capsys):
    target = tmp_path / "not-a-directory"
    target.write_text("occupied", encoding="utf-8")

    assert main(["init-workspace", str(target), "--engine-path", str(tmp_path)]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_init_workspace_cli_rejects_missing_engine(tmp_path, capsys):
    assert (
        main(
            [
                "init-workspace",
                str(tmp_path / "workspace"),
                "--engine-path",
                str(tmp_path / "missing"),
            ]
        )
        == 2
    )
    assert "explicit engine path is not an existing directory" in capsys.readouterr().err
