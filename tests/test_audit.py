
from opportunity_discovery.audit import audit_repository


def write(root, relpath: str, content: str) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# Detection-shaped values are built from runtime fragments so that no literal
# matching an audit rule exists in tracked source (the hardened audit scans
# tests/ like everything else).
AWS_LIKE_KEY = "AKIA" + "IOSFODNN7EXAMPL" + "E"
PRIVATE_KEY_HEADER = "-----BEGIN " + "PRIVATE KEY-----"
WIN_USER_PATH = "C:" + "\\" + "Users" + "\\" + "derek" + "\\" + "projects"
HOME_ABS_PATH = "/ho" + "me/derek/secret-stuff"


def test_clean_repo_passes(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "x = 1\n")
    write(tmp_path, "README.md", "# Safe project\n")
    report = audit_repository(tmp_path)
    assert report.errors == []


def test_credential_patterns_detected(tmp_path):
    write(tmp_path, "config/app.py", f'API_KEY = "{AWS_LIKE_KEY}"\n')
    report = audit_repository(tmp_path)
    rules = {f.rule for f in report.errors}
    assert "aws-access-key" in rules


def test_env_and_key_files_detected(tmp_path):
    write(tmp_path, ".env", "SECRET=topsecretvalue\n")
    write(tmp_path, "server.pem", PRIVATE_KEY_HEADER + "\nabc\n")
    report = audit_repository(tmp_path)
    names = {f.path for f in report.errors}
    assert ".env" in names
    assert any(n.endswith(".pem") for n in names)


def test_machine_paths_detected(tmp_path):
    write(tmp_path, "docs/notes.md", "run it from " + WIN_USER_PATH + "\\here" + "\n")
    write(tmp_path, "scripts/x.sh", "cd " + HOME_ABS_PATH + " && ls\n")
    report = audit_repository(tmp_path)
    rules = {f.rule for f in report.findings if f.severity == "error"}
    assert "windows-user-path" in rules
    assert "home-abs-path" in rules


def test_database_and_output_detected(tmp_path):
    write(tmp_path, "data/opdisc.sqlite3", "junk")
    write(tmp_path, "output/run_summary.json", "{}")
    report = audit_repository(tmp_path)
    paths = {f.path for f in report.errors}
    assert any("opdisc.sqlite3" in p for p in paths)


def test_benign_fixture_content_is_not_flagged(tmp_path):
    # Synthetic fixture/example data that matches no rule stays clean.
    write(tmp_path, "tests/fixtures/adapters/feed.csv", "a,b\n")
    write(tmp_path, "examples/sample.jsonl", '{"ok": true}\n')
    report = audit_repository(tmp_path)
    assert not [f for f in report.findings if "fixtures" in f.path or "examples" in f.path]


def test_credential_under_test_fixture_still_detected(tmp_path):
    """Regression: the old blanket tests//examples exemption is gone."""
    write(tmp_path, "tests/fixtures/adapters/app.py",
          f'API_KEY = "{AWS_LIKE_KEY}"\n')
    report = audit_repository(tmp_path)
    hits = {f.rule: f.path for f in report.errors}
    assert hits.get("aws-access-key") == "tests/fixtures/adapters/app.py"


def test_prohibited_file_under_tests_still_detected(tmp_path):
    write(tmp_path, "tests/fixtures/.env", "SECRET=topsecretvalue\n")
    report = audit_repository(tmp_path)
    assert "tests/fixtures/.env" in {f.path for f in report.errors}


def test_machine_path_under_example_still_detected(tmp_path):
    write(tmp_path, "examples/notes.md", "see " + WIN_USER_PATH + "\\here" + "\n")
    report = audit_repository(tmp_path)
    assert any(f.rule == "windows-user-path" and f.path == "examples/notes.md"
               for f in report.errors)


def test_tracked_test_source_contains_no_scan_matching_literals():
    """Guard: this repository's own tests must not trip the publication audit.

    Runs the real audit against the repo root; any error here means a
    scan-matching credential/path literal leaked into tracked source.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():  # not a checkout (e.g. installed wheel)
        return
    report = audit_repository(root)
    assert report.errors == [], "\n".join(
        f"{f.rule} {f.path}:{f.line}" for f in report.errors)
