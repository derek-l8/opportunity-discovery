"""Repository publication audit.

Scans tracked files (or working tree) for material that must never be
published: credentials, .env files, private keys, machine-specific absolute
paths, databases/logs/caches, live payloads, and obvious personal
application data.

Known limitations are documented in docs/SECURITY_AND_PRIVACY.md; the audit
is a heuristic net, not a guarantee.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- patterns ---------------------------------------------------------------
CREDENTIAL_PATTERNS = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("openai-key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("generic-secret-assignment", re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9+/_-]{16,}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("connection-string", re.compile(
        r"(?i)\b(postgres|mysql|mongodb(\+srv)?|amqp)://[^\s'\"]+:[^\s'\"]+@")),
]

PATH_PATTERNS = [
    ("windows-user-path", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z][\w.-]*", )),
    ("windows-profile-path", re.compile(r"(?i)[A-Za-z]:\\Documents and Settings\\")),
    ("wsl-user-mount", re.compile(r"/mnt/c/Users/[A-Za-z][\w.-]*")),
    ("home-abs-path", re.compile(r"(?<![\w/])/home/[A-Za-z][\w.-]*/")),
]

BANNED_FILENAMES = [
    ".env", ".env.local", ".env.production",
    "id_rsa", "id_ed25519", "id_ecdsa",
    "credentials.json", "client_secret.json",
]

BANNED_SUFFIXES = [
    ".sqlite", ".sqlite3", ".db", ".db-journal", ".sqlite-wal", ".sqlite-shm",
    ".log", ".pem", ".key", ".p12", ".pdf",
    # live payload artifacts that should never be committed
    "-packet.json", "_health.json",
]

BANNED_DIR_PARTS = {"node_modules", "__pycache__", ".venv", "venv", "data", "output", "logs"}

PERSONAL_DATA_HINTS = [
    ("resume-file", re.compile(r"(?i)\b(resume|cv|transcript)[\w-]*\.(pdf|docx?)\b")),
    ("application-status-language", re.compile(
        r"(?i)\b(my application (status|outcome)|i applied|interviewed at)\b")),
]


@dataclass
class Finding:
    severity: str  # error | warning | info
    rule: str
    path: str
    line: int | None = None
    detail: str | None = None


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def to_dict(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "finding_count": len(self.findings),
            "error_count": len(self.errors),
            "findings": [
                {
                    "severity": f.severity,
                    "rule": f.rule,
                    "path": f.path,
                    "line": f.line,
                    "detail": (f.detail or "")[:200],
                }
                for f in self.findings
            ],
        }


def _tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=str(root), capture_output=True, text=True, check=True
        )
        if out.stdout.strip():
            return sorted(root / line for line in out.stdout.splitlines() if line.strip())
        # Nothing tracked yet: fall through to a working-tree preview so the
        # audit remains useful before the first commit.
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # fallback: filesystem walk when git is unavailable. Vendored/environment
    # directories are never publishable and are skipped for speed; generated
    # data/output/logs directories are intentionally *included* so they can be
    # reported as findings.
    results: list[Path] = []
    # Vendored/env dirs are never publishable and are skipped for speed.
    # Generated data/output/logs dirs are intentionally NOT skipped so that
    # files inside them are reported as findings.
    skip_dirs = {
        "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
        ".mypy_cache", ".ruff_cache", ".pytest_cache", ".git",
    }
    for path in root.rglob("*"):
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & skip_dirs or ".git" in rel_parts:
            continue
        if path.is_file():
            results.append(path)
    return sorted(results)


def _is_allowed(path: Path, root: Path) -> bool:
    """Files that legitimately match generic rules.

    tests/ contains deliberate synthetic examples of every detection rule;
    fixtures/examples hold synthetic data. This is a documented trade-off:
    never place real credentials or personal data under tests/.
    """
    rel = path.relative_to(root).as_posix()
    if rel.startswith(("tests/", "examples")):
        return True
    return rel in ("docs/TROUBLESHOOTING.md", "scripts/run.ps1",
                   "scripts/register-task.ps1", "scripts/unregister-task.ps1",
                   "src/opportunity_discovery/audit.py")


def audit_repository(root: Path) -> AuditReport:
    root = Path(root).resolve()
    report = AuditReport()
    for path in _tracked_files(root):
        rel = path.relative_to(root).as_posix()
        report.files_scanned += 1

        name = path.name.lower()
        if name in BANNED_FILENAMES and not _is_allowed(path, root):
            report.findings.append(Finding("error", "banned-file", rel))
            continue
        suffix = path.suffix.lower()
        if suffix in BANNED_SUFFIXES and not _is_allowed(path, root):
            report.findings.append(Finding("error", "banned-suffix", rel))
            continue
        rel_parts = set(path.relative_to(root).parts[:-1])
        if rel_parts & BANNED_DIR_PARTS and not _is_allowed(path, root):
            report.findings.append(Finding("error", "generated-directory", rel))
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: filename checks above still applied

        lines = text.splitlines()
        for lineno, line in enumerate(lines, start=1):
            for rule_name, pattern in CREDENTIAL_PATTERNS:
                m = pattern.search(line)
                if m and not _is_allowed(path, root):
                    report.findings.append(Finding(
                        "error", rule_name, rel, lineno,
                        "possible credential literal (value not recorded)", ))
            for rule_name, pattern in PATH_PATTERNS:
                m = pattern.search(line)
                if m and not _is_allowed(path, root):
                    report.findings.append(Finding(
                        "error", rule_name, rel, lineno, m.group(0)[:60]))
            if rel.endswith(".md") or rel.startswith(("docs/",)):
                for rule_name, pattern in PERSONAL_DATA_HINTS:
                    m = pattern.search(line)
                    if m:
                        report.findings.append(Finding(
                            "warning", rule_name, rel, lineno, m.group(0)[:60]))
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI glue
    argv = argv or sys.argv[1:]
    root = Path(argv[0]) if argv else Path.cwd()
    report = audit_repository(root)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if not report.errors else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
