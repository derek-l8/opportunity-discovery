"""Phase 5 private-workspace recovery, backup, and audit contracts."""

import hashlib
import json
import shutil
import subprocess
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import pytest

import opportunity_discovery.workspace_recovery as recovery
from opportunity_discovery.cli import main
from opportunity_discovery.workspace import initialize_workspace
from opportunity_discovery.workspace_recovery import (
    audit_workspace,
    backup_workspace,
    compare_knowledge_snapshot,
    create_knowledge_snapshot,
    list_knowledge_snapshots,
    prune_knowledge_snapshots,
    restore_knowledge_snapshot,
    restore_workspace_backup,
)
from opportunity_discovery.workspace_state import WorkspaceStateError

RECOVERY_FIXTURE = Path(__file__).parent / "fixtures" / "demo" / "phase5-recovery.json"


def make_workspace(tmp_path: Path, *, inside_git: bool = False) -> Path:
    parent = tmp_path / "repository" if inside_git else tmp_path
    parent.mkdir(exist_ok=True)
    if inside_git:
        subprocess.run(["git", "init", "-q"], cwd=parent, check=True)
    root = parent / "Opportunity-Workspace"
    engine = tmp_path / "engine-checkout"
    engine.mkdir(exist_ok=True)
    initialize_workspace(root, engine_path=engine)
    return root


def test_snapshot_compare_and_restore_are_recoverable(tmp_path):
    root = make_workspace(tmp_path)
    knowledge = root / "knowledge" / "AUTOMATED.md"
    knowledge.write_text("before\n", encoding="utf-8")
    snapshot = create_knowledge_snapshot(
        root,
        operation_id="synthetic-review-1",
        paths=[knowledge, root / "knowledge" / "NEW.json"],
        created_at="2026-09-10T10:00:00Z",
    )
    knowledge.write_text("after\n", encoding="utf-8")
    (root / "knowledge" / "NEW.json").write_text("{}\n", encoding="utf-8")

    comparison = compare_knowledge_snapshot(root, snapshot.snapshot_id)
    assert comparison["changes"] == [
        {"path": "knowledge/AUTOMATED.md", "change": "changed"},
        {"path": "knowledge/NEW.json", "change": "added"},
    ]
    restored = restore_knowledge_snapshot(root, snapshot.snapshot_id)

    assert knowledge.read_text(encoding="utf-8") == "before\n"
    assert not (root / "knowledge" / "NEW.json").exists()
    assert restored["pre_restore_snapshot_id"].startswith("pre-restore-")
    assert compare_knowledge_snapshot(root, snapshot.snapshot_id)["identical"] is True
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["operation"] == "restore-knowledge"
    assert checkpoint["status"] == "complete"


def test_knowledge_snapshot_operations_reject_symlinked_ancestor_without_outside_access(
    tmp_path, monkeypatch
):
    root = make_workspace(tmp_path)
    knowledge = root / "knowledge" / "AUTOMATED.md"
    knowledge.write_text("inside before\n", encoding="utf-8")
    snapshot = create_knowledge_snapshot(
        root,
        operation_id="before-symlink",
        paths=[knowledge],
        created_at="2026-09-10T10:00:00Z",
    )
    outside = tmp_path / "outside-knowledge"
    outside.mkdir()
    outside_file = outside / "AUTOMATED.md"
    outside_file.write_text("outside sentinel\n", encoding="utf-8")
    shutil.rmtree(root / "knowledge")
    try:
        (root / "knowledge").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    real_sha256 = recovery._sha256

    def reject_outside_read(path):
        if Path(path).resolve(strict=False).is_relative_to(outside.resolve()):
            raise AssertionError("outside knowledge file was read")
        return real_sha256(path)

    monkeypatch.setattr(recovery, "_sha256", reject_outside_read)
    for operation in (
        lambda: create_knowledge_snapshot(root, operation_id="blocked", paths=[knowledge]),
        lambda: compare_knowledge_snapshot(root, snapshot.snapshot_id),
        lambda: restore_knowledge_snapshot(root, snapshot.snapshot_id),
    ):
        with pytest.raises(WorkspaceStateError, match="symlink component"):
            operation()
    assert outside_file.read_text(encoding="utf-8") == "outside sentinel\n"


def test_knowledge_snapshot_operations_reject_final_symlink_without_outside_access(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    knowledge = root / "knowledge" / "AUTOMATED.md"
    knowledge.write_text("inside before\n", encoding="utf-8")
    snapshot = create_knowledge_snapshot(
        root,
        operation_id="before-final-symlink",
        paths=[knowledge],
        created_at="2026-09-10T10:00:00Z",
    )
    outside_file = tmp_path / "outside-knowledge.txt"
    outside_file.write_text("outside sentinel\n", encoding="utf-8")
    knowledge.unlink()
    try:
        knowledge.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    real_sha256 = recovery._sha256

    def reject_outside_read(path):
        if Path(path).resolve(strict=False) == outside_file.resolve():
            raise AssertionError("outside knowledge file was read")
        return real_sha256(path)

    monkeypatch.setattr(recovery, "_sha256", reject_outside_read)
    for operation in (
        lambda: create_knowledge_snapshot(root, operation_id="blocked-final", paths=[knowledge]),
        lambda: compare_knowledge_snapshot(root, snapshot.snapshot_id),
        lambda: restore_knowledge_snapshot(root, snapshot.snapshot_id),
    ):
        with pytest.raises(WorkspaceStateError, match="symlink component"):
            operation()
    assert outside_file.read_text(encoding="utf-8") == "outside sentinel\n"


def test_failed_knowledge_restore_records_recovery_snapshot_and_reruns(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    knowledge = root / "knowledge" / "AUTOMATED.md"
    knowledge.write_text("before\n", encoding="utf-8")
    snapshot = create_knowledge_snapshot(
        root,
        operation_id="restore-failure-source",
        paths=[knowledge],
        created_at="2026-09-10T10:00:00Z",
    )
    knowledge.write_text("after\n", encoding="utf-8")
    real_replace = recovery.os.replace

    def fail_knowledge_replace(source, destination):
        if Path(destination) == knowledge:
            raise OSError("synthetic restore interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(recovery.os, "replace", fail_knowledge_replace)
    with pytest.raises(OSError, match="synthetic restore interruption"):
        restore_knowledge_snapshot(root, snapshot.snapshot_id)
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["operation"] == "restore-knowledge"
    assert checkpoint["status"] == "failed"
    pre_restore_steps = [
        step for step in checkpoint["completed_steps"] if step.startswith("created-pre-restore-snapshot:")
    ]
    assert len(pre_restore_steps) == 1
    pre_restore_id = pre_restore_steps[0].split(":", 1)[1]
    assert checkpoint["exact_next_action"] == f'opdisc restore-knowledge "{root}" {pre_restore_id}'
    assert "synthetic restore interruption" in checkpoint["error"]
    assert knowledge.read_text(encoding="utf-8") == "after\n"

    monkeypatch.setattr(recovery.os, "replace", real_replace)
    result = restore_knowledge_snapshot(root, snapshot.snapshot_id)
    assert result["restored_files"] == ["knowledge/AUTOMATED.md"]
    assert knowledge.read_text(encoding="utf-8") == "before\n"
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "complete"


def test_snapshot_id_cannot_escape_history(tmp_path):
    root = make_workspace(tmp_path)
    with pytest.raises(WorkspaceStateError, match="not portable"):
        compare_knowledge_snapshot(root, "../../outside")
    with pytest.raises(WorkspaceStateError, match="not portable"):
        restore_knowledge_snapshot(root, "../outside")


def test_snapshot_retention_keeps_daily_recent_and_monthly_older(tmp_path):
    root = make_workspace(tmp_path)
    knowledge = root / "knowledge" / "AUTOMATED.md"
    knowledge.write_text("synthetic\n", encoding="utf-8")
    snapshots = [
        ("july-early", "2026-07-05T10:00:00Z"),
        ("july-late", "2026-07-20T10:00:00Z"),
        ("august", "2026-08-01T10:00:00Z"),
        ("recent-morning", "2026-09-10T08:00:00Z"),
        ("recent-evening", "2026-09-10T18:00:00Z"),
        ("today", "2026-09-12T08:00:00Z"),
    ]
    for operation_id, created_at in snapshots:
        create_knowledge_snapshot(
            root,
            operation_id=operation_id,
            paths=[knowledge],
            created_at=created_at,
        )
    prune_knowledge_snapshots(root, now=datetime(2026, 9, 12, 12, tzinfo=UTC))

    kept = {snapshot.snapshot_id for snapshot in list_knowledge_snapshots(root)}
    assert "july-early" not in kept
    assert "july-late" in kept
    assert "august" in kept
    assert "recent-morning" not in kept
    assert "recent-evening" in kept
    assert "today" in kept


def test_full_and_state_backups_have_explicit_scope_and_skip_symlinks(tmp_path):
    root = make_workspace(tmp_path)
    fixture = json.loads(RECOVERY_FIXTURE.read_text(encoding="utf-8"))
    for relative, content in fixture["synthetic_files"].items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (root / "engine" / "not-backed-up.txt").write_text("public engine file\n", encoding="utf-8")
    (root / ".opdisc" / "cache").mkdir()
    (root / ".opdisc" / "cache" / "ignored.bin").write_bytes(b"cache")
    with suppress(OSError):
        (root / "sources" / "external-link").symlink_to(tmp_path / "outside")

    full_path = tmp_path / "full.zip"
    state_path = tmp_path / "state.zip"
    full = backup_workspace(root, full_path, kind="full", created_at="2026-09-12T10:00:00Z")
    state = backup_workspace(root, state_path, kind="state", created_at="2026-09-12T10:01:00Z")

    with zipfile.ZipFile(full_path) as archive:
        full_names = set(archive.namelist())
    with zipfile.ZipFile(state_path) as archive:
        state_names = set(archive.namelist())
    assert set(fixture["synthetic_files"]) <= full_names
    assert not any(
        name.startswith(prefix) for name in full_names for prefix in fixture["always_excluded_prefixes"]
    )
    assert not any(
        name.startswith(prefix) for name in state_names for prefix in fixture["expected_full_only_prefixes"]
    )
    assert "knowledge/AUTOMATED.md" in state_names
    assert "applications/phase5-notes.txt" in state_names
    assert full.warning.startswith("backup is an unencrypted ZIP")
    if (root / "sources" / "external-link").is_symlink():
        assert "sources/external-link" in full.skipped_symlinks
    assert state.file_count < full.file_count


def test_failed_backup_records_error_and_same_command_can_be_rerun(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    archive = tmp_path / "retry.zip"
    real_backup_files = recovery._backup_files

    def fail_backup_files(*_args, **_kwargs):
        raise OSError("synthetic backup interruption")

    monkeypatch.setattr(recovery, "_backup_files", fail_backup_files)
    with pytest.raises(OSError, match="synthetic backup interruption"):
        backup_workspace(root, archive, kind="state", created_at="2026-09-12T10:00:00Z")
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["operation"] == "backup-workspace"
    assert checkpoint["status"] == "failed"
    assert "synthetic backup interruption" in checkpoint["error"]
    assert checkpoint["exact_next_action"] == (
        f'fix the reported error, then run opdisc backup-workspace "{root}" '
        f'"{archive.resolve()}" --kind state'
    )
    assert not archive.exists()

    monkeypatch.setattr(recovery, "_backup_files", real_backup_files)
    result = backup_workspace(root, archive, kind="state", created_at="2026-09-12T10:00:00Z")
    assert result.path == archive.resolve()
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "complete"


def test_restore_verifies_backup_and_creates_full_pre_restore_backup(tmp_path):
    root = make_workspace(tmp_path)
    engine_path = json.loads((root / ".opdisc" / "workspace.json").read_text())["engine_path"]
    knowledge = root / "knowledge" / "PROFILE.md"
    knowledge.write_text("# Original synthetic profile\n", encoding="utf-8")
    archive = tmp_path / "original.zip"
    backup_workspace(root, archive, kind="full", created_at="2026-09-12T10:00:00Z")
    knowledge.write_text("# Changed synthetic profile\n", encoding="utf-8")
    pre_restore = tmp_path / "pre-restore.zip"

    result = restore_workspace_backup(root, archive, pre_restore_path=pre_restore)

    assert knowledge.read_text(encoding="utf-8") == "# Original synthetic profile\n"
    assert result.pre_restore_backup == pre_restore.resolve()
    assert pre_restore.is_file()
    with zipfile.ZipFile(pre_restore) as saved:
        assert saved.read("knowledge/PROFILE.md") == b"# Changed synthetic profile\n"
    metadata = json.loads((root / ".opdisc" / "workspace.json").read_text())
    assert metadata["engine_path"] == engine_path
    checkpoint = json.loads((root / ".opdisc" / "checkpoint.json").read_text())
    assert checkpoint["status"] == "complete"
    assert checkpoint["operation"] == "restore-workspace"


@pytest.mark.parametrize(
    ("bad_path", "error"),
    [("../escape.txt", "unsafe path"), ("engine/overwrite.py", "declared scope")],
)
def test_restore_rejects_unsafe_or_out_of_scope_path_before_mutation(tmp_path, bad_path, error):
    root = make_workspace(tmp_path)
    archive = tmp_path / "malicious.zip"
    payload = b"escape"
    manifest = {
        "schema_version": "1.0",
        "backup_kind": "full",
        "created_at": "2026-09-12T10:00:00Z",
        "files": [{"path": bad_path, "sha256": hashlib.sha256(payload).hexdigest(), "size": 6}],
        "skipped_symlinks": [],
        "custom": {},
    }
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr(".opdisc-backup.json", json.dumps(manifest))
        writer.writestr(bad_path, payload)

    with pytest.raises(WorkspaceStateError, match=error):
        restore_workspace_backup(root, archive)
    assert not (tmp_path / "escape.txt").exists()
    assert not list(tmp_path.glob("pre-restore-*.zip"))


@pytest.mark.parametrize(
    ("members", "error"),
    [
        (["knowledge/PROFILE.md:stream"], "non-portable path"),
        (["knowledge/Profile.md", "knowledge/profile.md"], "case-insensitive path collisions"),
    ],
)
def test_restore_rejects_windows_unsafe_archive_paths_portably(tmp_path, members, error):
    root = make_workspace(tmp_path)
    archive = tmp_path / "windows-unsafe.zip"
    entries = []
    with zipfile.ZipFile(archive, "w") as writer:
        for name in members:
            payload = name.encode("utf-8")
            entries.append(
                {"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
            )
            writer.writestr(name, payload)
        writer.writestr(
            ".opdisc-backup.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backup_kind": "state",
                    "created_at": "2026-09-12T10:00:00Z",
                    "files": entries,
                    "skipped_symlinks": [],
                    "custom": {},
                }
            ),
        )

    with pytest.raises(WorkspaceStateError, match=error):
        restore_workspace_backup(root, archive)
    assert not list(tmp_path.glob("pre-restore-*.zip"))


def test_workspace_audit_reports_missing_sources_external_refs_and_knowledge_refs(tmp_path):
    root = make_workspace(tmp_path)
    source = root / "sources" / "changed.txt"
    source.write_text("changed\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "imports": [
            {
                "sha256": "0" * 64,
                "original_name": "changed.txt",
                "stored_path": "sources/changed.txt",
                "imported_at": "2026-09-12T10:00:00Z",
            },
            {
                "sha256": "0" * 64,
                "original_name": "missing.txt",
                "stored_path": "sources/missing.txt",
                "imported_at": "2026-09-12T10:00:00Z",
            },
        ],
        "external_references": [
            {"path": str(tmp_path / "missing-project"), "label": "Synthetic missing project"}
        ],
        "custom": {},
    }
    (root / ".opdisc" / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    knowledge = {
        "schema_version": "1.0",
        "updated_at": "2026-09-12T10:00:00Z",
        "claims": {
            "missing-source-claim": {
                "statement": "Synthetic claim",
                "source_refs": ["sources/not-there.txt"],
                "material_effect": "none",
                "custom": {},
            }
        },
        "custom": {},
    }
    (root / "knowledge" / "AUTOMATED.json").write_text(json.dumps(knowledge), encoding="utf-8")

    report = audit_workspace(root)
    rules = {finding.rule for finding in report.findings}
    assert {
        "source-hash-mismatch",
        "missing-source",
        "broken-external-reference",
        "knowledge-missing-source",
    } <= rules
    assert len(report.errors) == 3


def test_workspace_audit_rejects_symlinked_source_ancestor_without_reading_outside(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    outside = tmp_path / "outside-sources"
    outside.mkdir()
    outside_file = outside / "private.txt"
    outside_file.write_text("outside sentinel\n", encoding="utf-8")
    try:
        (root / "sources" / "linked").symlink_to(outside, target_is_directory=True)
        (root / "sources" / "direct-link.txt").symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    manifest = {
        "schema_version": "1.0",
        "imports": [
            {
                "sha256": hashlib.sha256(outside_file.read_bytes()).hexdigest(),
                "original_name": "private.txt",
                "stored_path": "sources/linked/private.txt",
                "imported_at": "2026-09-12T10:00:00Z",
            },
            {
                "sha256": hashlib.sha256(outside_file.read_bytes()).hexdigest(),
                "original_name": "private.txt",
                "stored_path": "sources/direct-link.txt",
                "imported_at": "2026-09-12T10:00:00Z",
            },
        ],
        "external_references": [],
        "custom": {},
    }
    (root / ".opdisc" / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    outside_before = outside_file.read_bytes()
    real_sha256 = recovery._sha256

    def reject_outside_read(path):
        if Path(path).resolve(strict=False).is_relative_to(outside.resolve()):
            raise AssertionError("outside source was read")
        return real_sha256(path)

    monkeypatch.setattr(recovery, "_sha256", reject_outside_read)
    report = audit_workspace(root)

    unsafe = [finding for finding in report.errors if finding.rule == "unsafe-source-reference"]
    assert len(unsafe) == 2
    assert all("symlink component" in finding.detail for finding in unsafe)
    assert outside_file.read_bytes() == outside_before


def test_workspace_audit_warns_on_git_and_errors_on_tracked_private_file(tmp_path):
    root = make_workspace(tmp_path, inside_git=True)
    repository = root.parent
    subprocess.run(["git", "add", "Opportunity-Workspace/knowledge/PROFILE.md"], cwd=repository, check=True)

    report = audit_workspace(root)
    rules = {finding.rule for finding in report.findings}
    assert "workspace-inside-git" in rules
    assert "tracked-private-file" in rules


def test_recovery_cli_json(tmp_path, capsys):
    root = make_workspace(tmp_path)
    archive = tmp_path / "state.zip"
    assert main(["--json", "backup-workspace", str(root), str(archive), "--kind", "state"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "state"
    assert main(["--json", "workspace-audit", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
