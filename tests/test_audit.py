
from opportunity_discovery.audit import audit_repository


def write(root, relpath: str, content: str) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_clean_repo_passes(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "x = 1\n")
    write(tmp_path, "README.md", "# Safe project\n")
    report = audit_repository(tmp_path)
    assert report.errors == []


def test_credential_patterns_detected(tmp_path):
    write(tmp_path, "config/app.py", 'API_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    report = audit_repository(tmp_path)
    rules = {f.rule for f in report.errors}
    assert "aws-access-key" in rules


def test_env_and_key_files_detected(tmp_path):
    write(tmp_path, ".env", "SECRET=topsecretvalue\n")
    write(tmp_path, "server.pem", "-----BEGIN PRIVATE KEY-----\nabc\n")
    report = audit_repository(tmp_path)
    names = {f.path for f in report.errors}
    assert ".env" in names
    assert any(n.endswith(".pem") for n in names)


def test_machine_paths_detected(tmp_path):
    write(tmp_path, "docs/notes.md", r"run it from C:\Users\derek\projects\here" + "\n")
    write(tmp_path, "scripts/x.sh", "cd /home/derek/secret-stuff && ls\n")
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


def test_fixtures_are_allowed(tmp_path):
    write(tmp_path, "tests/fixtures/adapters/feed.csv", "a,b\n")
    write(tmp_path, "examples/sample.jsonl", '{"ok": true}\n')
    report = audit_repository(tmp_path)
    assert not [f for f in report.findings if "fixtures" in f.path or "examples" in f.path]
