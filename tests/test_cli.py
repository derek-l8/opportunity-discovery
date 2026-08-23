"""CLI behavior and Windows-safe path handling."""
import json

from opportunity_discovery.cli import main


def test_init_and_validate_config(engine_config, tmp_path, capsys):
    engine_config.sources_file.parent.mkdir(parents=True, exist_ok=True)
    from tests.conftest import write_sources_toml

    write_sources_toml(engine_config, [{
        "source_id": "a", "display_name": "A", "organization": "O",
        "adapter": "greenhouse", "endpoint_config": {"board": "a"}}])
    assert main(["--config", str(engine_config.config_path), "init"]) == 0
    assert (engine_config.paths.data_dir / "opdisc.sqlite3").exists()
    capsys.readouterr()

    assert main(["--config", str(engine_config.config_path),
                 "--json", "validate-config"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] and payload["source_count"] == 1


def test_status_and_source_health_json(engine_config, tmp_path, capsys):
    engine_config.sources_file.parent.mkdir(parents=True, exist_ok=True)
    from tests.conftest import write_sources_toml

    write_sources_toml(engine_config, [{
        "source_id": "a", "display_name": "A", "organization": "O",
        "adapter": "greenhouse", "endpoint_config": {"board": "a"}}])
    main(["--config", str(engine_config.config_path), "init"])
    capsys.readouterr()
    assert main(["--config", str(engine_config.config_path),
                 "--json", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert "opportunities" in status
    assert main(["--config", str(engine_config.config_path),
                 "--json", "source-health"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert "sources" in health and "summary" in health


def test_add_source_appends(engine_config, tmp_path):
    engine_config.sources_file.parent.mkdir(parents=True, exist_ok=True)
    engine_config.sources_file.write_text("", encoding="utf-8")
    code = main([
        "--config", str(engine_config.config_path),
        "add-source", "greenhouse-newco",
        "--organization", "NewCo", "--adapter", "greenhouse",
        '--endpoint-json', '{"board": "newco"}',
        "--category", "internship",
    ])
    assert code == 0
    text = engine_config.sources_file.read_text(encoding="utf-8")
    assert 'source_id = "greenhouse-newco"' in text
    # duplicate append fails
    assert main([
        "--config", str(engine_config.config_path),
        "add-source", "greenhouse-newco",
        "--organization", "NewCo", "--adapter", "greenhouse",
        '--endpoint-json', '{"board": "newco"}',
    ]) == 1


def test_prune_dry_run_default(engine_config, tmp_path, capsys):
    engine_config.sources_file.parent.mkdir(parents=True, exist_ok=True)
    from tests.conftest import write_sources_toml

    write_sources_toml(engine_config, [{
        "source_id": "a", "display_name": "A", "organization": "O",
        "adapter": "greenhouse", "endpoint_config": {"board": "a"}}])
    main(["--config", str(engine_config.config_path), "init"])
    capsys.readouterr()
    assert main(["--config", str(engine_config.config_path),
                 "--json", "prune"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


def test_windows_style_paths_resolve(tmp_path):
    from pathlib import Path

    from opportunity_discovery.config import PathsConfig

    overrides = {
        "data_dir": r"C:\Users\svc\AppData\Local\opdisc\data",
        "output_dir": str(tmp_path / "out"),
        "logs_dir": "logs",
    }
    paths = PathsConfig.resolve(Path(tmp_path), overrides)
    # Windows-style absolute path is preserved as-is (no POSIX mangling)
    assert str(paths.data_dir).startswith("C:") or paths.data_dir.is_absolute()
    assert (Path(str(tmp_path)) / "out") == paths.output_dir
    assert paths.logs_dir == Path(str(tmp_path)) / "logs"


def test_audit_cli_exit_codes(engine_config, tmp_path, capsys):
    (tmp_path / ".env").write_text("SECRET=x\n", encoding="utf-8")
    assert main(["audit", str(tmp_path)]) == 1
    capsys.readouterr()
