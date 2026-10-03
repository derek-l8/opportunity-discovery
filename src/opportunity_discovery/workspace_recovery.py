"""Small, direct recovery, backup, and audit tools for private workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .workspace_state import (
    STATE_SCHEMA_VERSION,
    WorkspaceStateError,
    _atomic_json,
    _checkpoint,
    _object,
    _read_json,
    _secure_workspace_path,
    require_workspace,
)

SNAPSHOT_RETENTION_DAYS = 30
GENERATED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
ENGINE_SETTINGS = (
    "engine/opportunity-discovery/config/default.toml",
    "engine/opportunity-discovery/config/sources.toml",
)
BACKUP_KINDS = {"full", "state"}


@dataclass(frozen=True)
class KnowledgeSnapshot:
    snapshot_id: str
    created_at: str
    operation_id: str
    path: Path
    files: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "operation_id": self.operation_id,
            "path": str(self.path),
            "files": list(self.files),
        }


@dataclass(frozen=True)
class BackupResult:
    workspace: Path
    path: Path
    kind: str
    file_count: int
    sha256: str
    skipped_symlinks: tuple[str, ...]
    warning: str = "backup is an unencrypted ZIP containing private information"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "workspace": str(self.workspace),
            "path": str(self.path),
            "kind": self.kind,
            "file_count": self.file_count,
            "sha256": self.sha256,
            "skipped_symlinks": list(self.skipped_symlinks),
            "warning": self.warning,
        }


@dataclass(frozen=True)
class RestoreResult:
    workspace: Path
    archive: Path
    pre_restore_backup: Path
    restored_files: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "workspace": str(self.workspace),
            "archive": str(self.archive),
            "pre_restore_backup": str(self.pre_restore_backup),
            "restored_files": self.restored_files,
        }


@dataclass(frozen=True)
class WorkspaceAuditFinding:
    severity: str
    rule: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass
class WorkspaceAuditReport:
    workspace: Path
    findings: list[WorkspaceAuditFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[WorkspaceAuditFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "workspace": str(self.workspace),
            "ok": not self.errors,
            "error_count": len(self.errors),
            "warning_count": len(self.findings) - len(self.errors),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceStateError(f"invalid snapshot timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise WorkspaceStateError(f"snapshot timestamp {value!r} has no UTC offset")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(root: Path, path: Path) -> str:
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(root.absolute())
    except ValueError as exc:
        raise WorkspaceStateError(f"path is outside the workspace: {path}") from exc
    if ".." in relative.parts:
        raise WorkspaceStateError(f"path escapes the workspace: {path}")
    return relative.as_posix()


def _snapshot_from_manifest(path: Path, document: dict[str, Any]) -> KnowledgeSnapshot:
    files = document.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise WorkspaceStateError(f"invalid snapshot manifest: {path}")
    return KnowledgeSnapshot(
        str(document.get("snapshot_id")),
        str(document.get("created_at")),
        str(document.get("operation_id")),
        path.parent,
        tuple(files),
    )


def create_knowledge_snapshot(
    root: Path,
    *,
    operation_id: str,
    paths: list[Path],
    created_at: str | None = None,
    preserve_snapshot_ids: set[str] | None = None,
) -> KnowledgeSnapshot:
    """Capture the exact pre-change state of selected knowledge files."""
    root, _metadata = require_workspace(root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", operation_id):
        raise WorkspaceStateError("operation_id is not portable")
    timestamp = created_at or _now()
    _parse_time(timestamp)
    snapshot_id = operation_id
    history = root / ".opdisc" / "history" / "knowledge"
    destination = _secure_workspace_path(
        root, history, history / snapshot_id, "knowledge snapshot destination"
    )
    manifest_path = _secure_workspace_path(
        root, destination, destination / "manifest.json", "knowledge snapshot manifest"
    )
    if manifest_path.exists():
        return _snapshot_from_manifest(manifest_path, _read_json(manifest_path, {}))

    entries: list[dict[str, Any]] = []
    normalized: list[tuple[Path, str]] = []
    for path in paths:
        path = _secure_workspace_path(root, root / "knowledge", path, "knowledge snapshot path")
        relative = _safe_relative(root, path)
        if not relative.startswith("knowledge/"):
            raise WorkspaceStateError("knowledge snapshots may include only files below knowledge/")
        if path.exists() and not path.is_file():
            raise WorkspaceStateError(f"knowledge snapshot accepts files only: {relative}")
        normalized.append((path, relative))
        entries.append(
            {
                "path": relative,
                "existed": path.is_file(),
                "sha256": _sha256(path) if path.is_file() else None,
            }
        )

    history.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}-", dir=history))
    try:
        for path, relative in normalized:
            if not path.is_file():
                continue
            target = temporary / "files" / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        manifest = {
            "schema_version": STATE_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": timestamp,
            "operation_id": operation_id,
            "files": entries,
            "custom": {},
        }
        _atomic_json(temporary / "manifest.json", manifest)
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            shutil.rmtree(temporary)
    prune_knowledge_snapshots(
        root,
        now=_parse_time(timestamp),
        preserve={snapshot_id, *(preserve_snapshot_ids or set())},
    )
    return _snapshot_from_manifest(destination / "manifest.json", manifest)


def list_knowledge_snapshots(root: Path) -> list[KnowledgeSnapshot]:
    root, _metadata = require_workspace(root)
    history = _secure_workspace_path(
        root,
        root / ".opdisc" / "history",
        root / ".opdisc" / "history" / "knowledge",
        "knowledge snapshot history",
    )
    snapshots: list[KnowledgeSnapshot] = []
    if not history.exists():
        return snapshots
    for manifest_path in history.glob("*/manifest.json"):
        manifest_path = _secure_workspace_path(root, history, manifest_path, "knowledge snapshot manifest")
        manifest = _read_json(manifest_path, {})
        snapshots.append(_snapshot_from_manifest(manifest_path, manifest))
    return sorted(snapshots, key=lambda item: (item.created_at, item.snapshot_id), reverse=True)


def _snapshot_manifest_path(root: Path, snapshot_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", snapshot_id):
        raise WorkspaceStateError("snapshot_id is not portable")
    history = root / ".opdisc" / "history" / "knowledge"
    return _secure_workspace_path(
        root,
        history,
        history / snapshot_id / "manifest.json",
        "knowledge snapshot manifest",
    )


def _snapshot_entry_path(root: Path, value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or "\\" in value:
        raise WorkspaceStateError("snapshot contains a non-portable path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not value.startswith("knowledge/"):
        raise WorkspaceStateError(f"snapshot contains an unsafe knowledge path: {value}")
    target = _secure_workspace_path(
        root,
        root / "knowledge",
        root / Path(*relative.parts),
        f"knowledge snapshot entry {value}",
    )
    return value, target


def prune_knowledge_snapshots(
    root: Path, *, now: datetime | None = None, preserve: set[str] | None = None
) -> list[str]:
    """Keep one daily snapshot for 30 days and one monthly snapshot before that."""
    root, _metadata = require_workspace(root)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    preserved = preserve or set()
    snapshots = list_knowledge_snapshots(root)
    keep: set[str] = set(preserved)
    daily: set[str] = set()
    monthly: set[str] = set()
    for snapshot in snapshots:
        created = _parse_time(snapshot.created_at)
        age = current - created
        if age <= timedelta(days=SNAPSHOT_RETENTION_DAYS):
            key = created.date().isoformat()
            if key not in daily:
                daily.add(key)
                keep.add(snapshot.snapshot_id)
        else:
            key = created.strftime("%Y-%m")
            if key not in monthly:
                monthly.add(key)
                keep.add(snapshot.snapshot_id)
    removed: list[str] = []
    history = root / ".opdisc" / "history" / "knowledge"
    for snapshot in snapshots:
        if snapshot.snapshot_id in keep:
            continue
        target = _secure_workspace_path(
            root, history, history / snapshot.snapshot_id, "knowledge snapshot prune target"
        )
        if target.parent == history and target.is_dir():
            shutil.rmtree(target)
            removed.append(snapshot.snapshot_id)
    return sorted(removed)


def compare_knowledge_snapshot(root: Path, snapshot_id: str) -> dict[str, Any]:
    root, _metadata = require_workspace(root)
    manifest_path = _snapshot_manifest_path(root, snapshot_id)
    snapshot = _snapshot_from_manifest(manifest_path, _read_json(manifest_path, {}))
    changes: list[dict[str, str]] = []
    for entry in snapshot.files:
        relative, current = _snapshot_entry_path(root, entry.get("path"))
        existed = bool(entry["existed"])
        if existed and not current.is_file():
            changes.append({"path": relative, "change": "removed"})
        elif not existed and current.is_file():
            changes.append({"path": relative, "change": "added"})
        elif existed and current.is_file() and _sha256(current) != entry["sha256"]:
            changes.append({"path": relative, "change": "changed"})
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "changes": changes,
        "identical": not changes,
    }


def restore_knowledge_snapshot(root: Path, snapshot_id: str) -> dict[str, Any]:
    """Restore one snapshot after first snapshotting the current file state."""
    root, _metadata = require_workspace(root)
    manifest_path = _snapshot_manifest_path(root, snapshot_id)
    snapshot = _snapshot_from_manifest(manifest_path, _read_json(manifest_path, {}))
    restore_id = "pre-restore-" + re.sub(r"[^A-Za-z0-9._-]", "-", _now())
    checked: list[tuple[dict[str, Any], str, Path, Path | None]] = []
    paths: list[Path] = []
    for entry in snapshot.files:
        relative, target = _snapshot_entry_path(root, entry.get("path"))
        source: Path | None = None
        if entry.get("existed"):
            source_root = snapshot.path / "files"
            source = _secure_workspace_path(
                root,
                source_root,
                source_root / Path(*PurePosixPath(relative).parts),
                f"snapshot content {relative}",
            )
            if not source.is_file() or _sha256(source) != entry.get("sha256"):
                raise WorkspaceStateError(f"snapshot content is missing or corrupt: {relative}")
        checked.append((entry, relative, target, source))
        paths.append(target)
    pre_restore = create_knowledge_snapshot(
        root,
        operation_id=restore_id,
        paths=paths,
        preserve_snapshot_ids={snapshot_id},
    )
    manifest_sha256 = _sha256(manifest_path)
    operation_id = f"restore-knowledge-{manifest_sha256[:12]}"
    completed = ["validated-snapshot", f"created-pre-restore-snapshot:{pre_restore.snapshot_id}"]
    checkpoint_path = _checkpoint(
        root,
        operation="restore-knowledge",
        operation_id=operation_id,
        status="in_progress",
        completed_steps=completed,
        exact_next_action=f"restore knowledge files from snapshot {snapshot_id}",
        input_sha256=manifest_sha256,
    )
    restored: list[str] = []
    try:
        for entry, relative, target, source in checked:
            # Recheck immediately before each mutation in case a component changed
            # after preflight.
            target = _secure_workspace_path(
                root, root / "knowledge", target, f"knowledge restore target {relative}"
            )
            if entry["existed"]:
                assert source is not None
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".restore.tmp")
                try:
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, target)
                finally:
                    with suppress(FileNotFoundError):
                        temporary.unlink()
            else:
                with suppress(FileNotFoundError):
                    target.unlink()
            restored.append(relative)
        completed.append("restored-knowledge")
        checkpoint_path = _checkpoint(
            root,
            operation="restore-knowledge",
            operation_id=operation_id,
            status="complete",
            completed_steps=completed,
            exact_next_action=(
                "compare the restored knowledge and keep the pre-restore snapshot until satisfied"
            ),
            input_sha256=manifest_sha256,
        )
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "pre_restore_snapshot_id": pre_restore.snapshot_id,
            "restored_files": restored,
            "checkpoint_path": str(checkpoint_path),
            "exact_next_action": (
                "compare the restored knowledge and keep the pre-restore snapshot until satisfied"
            ),
        }
    except Exception as exc:
        _checkpoint(
            root,
            operation="restore-knowledge",
            operation_id=operation_id,
            status="failed",
            completed_steps=completed,
            exact_next_action=(f'opdisc restore-knowledge "{root}" {pre_restore.snapshot_id}'),
            input_sha256=manifest_sha256,
            error=str(exc),
        )
        raise


def _backup_roots(kind: str) -> tuple[str, ...]:
    common = (
        "WORKSPACE.md",
        "AGENTS.md",
        "CLAUDE.md",
        "Open Dashboard.cmd",
        ".agents",
        "knowledge",
        "opportunities",
        "applications",
        ".opdisc",
        *ENGINE_SETTINGS,
    )
    if kind == "full":
        return (*common, "inbox", "sources")
    return common


def _backup_files(root: Path, kind: str, output_path: Path) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    skipped_symlinks: list[str] = []
    output_absolute = output_path.absolute()
    pending = (
        [*root.iterdir(), *(root / name for name in ENGINE_SETTINGS)]
        if kind == "full"
        else [root / name for name in _backup_roots(kind)]
    )
    while pending:
        candidate = pending.pop()
        relative = _safe_relative(root, candidate)
        if _has_symlink_component(root, relative):
            skipped_symlinks.append(relative)
            continue
        if not _archive_path_allowed(relative, kind):
            continue
        if candidate.is_dir():
            pending.extend(candidate.iterdir())
        elif (
            candidate.is_file()
            and candidate.absolute() != output_absolute
            and candidate.absolute() != output_absolute.with_suffix(output_absolute.suffix + ".tmp")
            and not _is_workspace_backup(candidate)
        ):
            files.append(candidate)
    files = list(set(files))
    names = [_safe_archive_name(_safe_relative(root, path)) for path in files]
    if len({name.casefold() for name in names}) != len(names):
        raise WorkspaceStateError("workspace contains case-insensitive path collisions")
    return sorted(set(files), key=lambda item: _safe_relative(root, item)), sorted(skipped_symlinks)


def _is_workspace_backup(path: Path) -> bool:
    if path.suffix.casefold() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return ".opdisc-backup.json" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def backup_workspace(
    root: Path,
    output_path: Path,
    *,
    kind: str,
    created_at: str | None = None,
    record_checkpoint: bool = True,
) -> BackupResult:
    """Create an ordinary, explicit unencrypted ZIP backup."""
    root, _metadata = require_workspace(root)
    if kind not in BACKUP_KINDS:
        raise WorkspaceStateError(f"backup kind must be one of {sorted(BACKUP_KINDS)}")
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists() and output_path.is_dir():
        raise WorkspaceStateError(f"backup destination is a directory: {output_path}")
    timestamp = created_at or _now()
    _parse_time(timestamp)
    operation_hash = hashlib.sha256(f"{kind}:{output_path}:{timestamp}".encode()).hexdigest()
    operation_id = f"backup-{kind}-{operation_hash[:12]}"
    if record_checkpoint:
        _checkpoint(
            root,
            operation="backup-workspace",
            operation_id=operation_id,
            status="in_progress",
            completed_steps=["validated-workspace"],
            exact_next_action="collect files and write the backup archive",
            input_sha256=None,
        )
    try:
        files, skipped = _backup_files(root, kind, output_path)
        manifest_files = [
            {
                "path": _safe_relative(root, path),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
            for path in files
        ]
        manifest = {
            "schema_version": STATE_SCHEMA_VERSION,
            "backup_kind": kind,
            "created_at": timestamp,
            "files": manifest_files,
            "skipped_symlinks": skipped,
            "custom": {},
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(".opdisc-backup.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                for path in files:
                    archive.write(path, _safe_relative(root, path))
            os.replace(temporary, output_path)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        result = BackupResult(root, output_path, kind, len(files), _sha256(output_path), tuple(skipped))
        if record_checkpoint:
            _checkpoint(
                root,
                operation="backup-workspace",
                operation_id=operation_id,
                status="complete",
                completed_steps=["validated-workspace", "created-backup"],
                exact_next_action="store the unencrypted archive in a private, backed-up location",
                input_sha256=None,
            )
        return result
    except Exception as exc:
        if record_checkpoint:
            _checkpoint(
                root,
                operation="backup-workspace",
                operation_id=operation_id,
                status="failed",
                completed_steps=["validated-workspace"],
                exact_next_action=(
                    f'fix the reported error, then run opdisc backup-workspace "{root}" '
                    f'"{output_path}" --kind {kind}'
                ),
                input_sha256=None,
                error=str(exc),
            )
        raise


def _safe_archive_name(name: str) -> str:
    if "\\" in name or ":" in name:
        raise WorkspaceStateError(f"backup contains non-portable path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.as_posix() != name:
        raise WorkspaceStateError(f"backup contains unsafe path: {name}")
    return path.as_posix()


def _archive_path_allowed(name: str, kind: str) -> bool:
    parts = PurePosixPath(name).parts
    folded = tuple(part.casefold() for part in parts)
    if set(folded) & GENERATED_DIRECTORIES or name.endswith(".restore.tmp"):
        return False
    if folded[0] == ".opdisc-backup.json":
        return False
    if (
        folded[0] == ".opdisc"
        and len(folded) > 1
        and (folded[1] in {"backups", "cache", "caches", "tmp", "temp"} or name.endswith(".tmp"))
    ):
        return False
    if folded[0] == "engine":
        return name in ENGINE_SETTINGS
    return kind == "full" or parts[0] in _backup_roots(kind)


def _archive_member_sha256(archive: zipfile.ZipFile, name: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(name) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _validated_backup(archive_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [_safe_archive_name(info.filename) for info in archive.infolist()]
            if len(names) != len(set(names)):
                raise WorkspaceStateError("backup contains duplicate paths")
            folded_names = [name.casefold() for name in names]
            if len(folded_names) != len(set(folded_names)):
                raise WorkspaceStateError("backup contains case-insensitive path collisions")
            if ".opdisc-backup.json" not in names:
                raise WorkspaceStateError("backup manifest is missing")
            manifest = _object(json.loads(archive.read(".opdisc-backup.json")), "backup manifest")
            if manifest.get("schema_version") != STATE_SCHEMA_VERSION:
                raise WorkspaceStateError("backup schema version is unsupported")
            if manifest.get("backup_kind") not in BACKUP_KINDS:
                raise WorkspaceStateError("backup kind is invalid")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise WorkspaceStateError("backup files must be an array")
            checked_entries: list[dict[str, Any]] = []
            seen_entries: set[str] = set()
            seen_folded_entries: set[str] = set()
            for raw in entries:
                entry = _object(raw, "backup file")
                name = _safe_archive_name(_string_value(entry.get("path"), "backup file path"))
                if name in seen_entries:
                    raise WorkspaceStateError(f"backup manifest repeats path: {name}")
                seen_entries.add(name)
                folded_name = name.casefold()
                if folded_name in seen_folded_entries:
                    raise WorkspaceStateError(
                        f"backup manifest has a case-insensitive path collision: {name}"
                    )
                seen_folded_entries.add(folded_name)
                if not _archive_path_allowed(name, str(manifest["backup_kind"])):
                    raise WorkspaceStateError(f"backup path is outside its declared scope: {name}")
                if name not in names:
                    raise WorkspaceStateError(f"backup content is missing: {name}")
                digest, size = _archive_member_sha256(archive, name)
                if digest != entry.get("sha256"):
                    raise WorkspaceStateError(f"backup content hash mismatch: {name}")
                if size != entry.get("size"):
                    raise WorkspaceStateError(f"backup content size mismatch: {name}")
                checked_entries.append({**entry, "path": name})
            expected_names = {str(entry["path"]) for entry in checked_entries} | {".opdisc-backup.json"}
            if set(names) != expected_names:
                raise WorkspaceStateError("backup contains files not named by its manifest")
            return manifest, checked_entries
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise WorkspaceStateError(f"could not read backup: {exc}") from exc


def _string_value(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceStateError(f"{path} must be a non-empty string")
    return value


def _unique_pre_restore_path(archive_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = archive_path.parent / f"pre-restore-{stamp}.zip"
    counter = 1
    while candidate.exists():
        candidate = archive_path.parent / f"pre-restore-{stamp}-{counter}.zip"
        counter += 1
    return candidate


def _has_symlink_component(root: Path, relative: str) -> bool:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_reparse_tag", 0) == getattr(
            stat, "IO_REPARSE_TAG_MOUNT_POINT", -1
        ):
            return True
    return False


def restore_workspace_backup(
    root: Path, archive_path: Path, *, pre_restore_path: Path | None = None
) -> RestoreResult:
    """Verify fully, back up current state, then restore named files atomically."""
    root, current_metadata = require_workspace(root)
    archive_path = Path(archive_path).expanduser().resolve()
    _manifest, entries = _validated_backup(archive_path)
    for entry in entries:
        if _has_symlink_component(root, str(entry["path"])):
            raise WorkspaceStateError(f"restore refuses symlink path: {entry['path']}")
    pre_restore = (
        Path(pre_restore_path).expanduser().resolve()
        if pre_restore_path
        else _unique_pre_restore_path(archive_path)
    )
    if pre_restore == archive_path:
        raise WorkspaceStateError("pre-restore backup path must differ from the archive being restored")
    backup_workspace(root, pre_restore, kind="full", record_checkpoint=False)
    archive_sha = _sha256(archive_path)
    operation_id = f"restore-{archive_sha[:12]}"
    completed = ["validated-backup", "created-pre-restore-backup"]
    _checkpoint(
        root,
        operation="restore-workspace",
        operation_id=operation_id,
        status="in_progress",
        completed_steps=completed,
        exact_next_action="restore verified files",
        input_sha256=archive_sha,
    )
    try:
        restored = 0
        with zipfile.ZipFile(archive_path) as archive:
            for entry in sorted(entries, key=lambda item: str(item["path"])):
                name = str(entry["path"])
                target = root / Path(*PurePosixPath(name).parts)
                if _has_symlink_component(root, name):
                    raise WorkspaceStateError(f"restore refuses symlink path: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".restore.tmp")
                digest = hashlib.sha256()
                size = 0
                try:
                    with archive.open(name) as source, open(temporary, "wb") as handle:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if digest.hexdigest() != entry["sha256"] or size != entry["size"]:
                        raise WorkspaceStateError(f"backup changed while restoring: {name}")
                    if name == ".opdisc/workspace.json":
                        archived_metadata = _object(
                            json.loads(temporary.read_text(encoding="utf-8")),
                            "archived workspace metadata",
                        )
                        archived_custom = _object(
                            archived_metadata.get("custom", {}), "archived workspace custom"
                        )
                        _atomic_json(
                            temporary,
                            {**current_metadata, "custom": archived_custom},
                        )
                    os.replace(temporary, target)
                finally:
                    with suppress(FileNotFoundError):
                        temporary.unlink()
                restored += 1
        completed.append("restored-files")
        _checkpoint(
            root,
            operation="restore-workspace",
            operation_id=operation_id,
            status="complete",
            completed_steps=completed,
            exact_next_action="run workspace-audit and inspect restored private state",
            input_sha256=archive_sha,
        )
        return RestoreResult(root, archive_path, pre_restore, restored)
    except Exception as exc:
        _checkpoint(
            root,
            operation="restore-workspace",
            operation_id=operation_id,
            status="failed",
            completed_steps=completed,
            exact_next_action=f"restore the pre-restore backup at {pre_restore}",
            input_sha256=archive_sha,
            error=str(exc),
        )
        raise


def _git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(result.stdout.strip()).resolve()


def _audit_git(root: Path, report: WorkspaceAuditReport) -> None:
    git_root = _git_root(root)
    if git_root is None:
        return
    report.findings.append(
        WorkspaceAuditFinding("warning", "workspace-inside-git", ".", f"workspace is inside {git_root}")
    )
    try:
        relative = root.relative_to(git_root).as_posix()
        pathspec = relative if relative != "." else "."
        result = subprocess.run(
            ["git", "ls-files", "--", pathspec],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (ValueError, OSError, subprocess.CalledProcessError):
        return
    for tracked in result.stdout.splitlines():
        if tracked.strip():
            report.findings.append(
                WorkspaceAuditFinding(
                    "error", "tracked-private-file", tracked, "private workspace file is tracked by Git"
                )
            )


def _portable_workspace_path(root: Path, value: Any, label: str) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value or "\\" in value:
        return None, f"{label} is not a portable relative path"
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None, f"{label} escapes the workspace"
    return root / Path(*path.parts), None


def audit_workspace(root: Path) -> WorkspaceAuditReport:
    """Audit private workspace exposure and reference integrity without mutation."""
    root, metadata = require_workspace(root)
    report = WorkspaceAuditReport(root)
    _audit_git(root, report)
    recorded_root = metadata.get("private_state_root")
    if recorded_root != str(root):
        report.findings.append(
            WorkspaceAuditFinding(
                "warning",
                "moved-workspace",
                ".opdisc/workspace.json",
                "recorded private_state_root differs from the current workspace path",
            )
        )

    manifest_path = root / ".opdisc" / "source-manifest.json"
    manifest = _read_json(manifest_path, {})
    imports = manifest.get("imports", [])
    if not isinstance(imports, list):
        report.findings.append(
            WorkspaceAuditFinding(
                "error",
                "invalid-source-manifest",
                ".opdisc/source-manifest.json",
                "imports is not an array",
            )
        )
        imports = []
    for index, raw in enumerate(imports):
        if not isinstance(raw, dict):
            report.findings.append(
                WorkspaceAuditFinding(
                    "error", "invalid-source-import", f"imports[{index}]", "entry is not an object"
                )
            )
            continue
        path, error = _portable_workspace_path(root, raw.get("stored_path"), f"imports[{index}].stored_path")
        display = str(raw.get("stored_path"))
        portable = PurePosixPath(display) if not error else None
        if not error and (portable is None or not portable.parts or portable.parts[0] != "sources"):
            error = f"imports[{index}].stored_path must be below sources/"
        if not error and path is not None:
            try:
                path = _secure_workspace_path(root, root / "sources", path, f"imports[{index}].stored_path")
            except WorkspaceStateError as exc:
                error = str(exc)
        if error:
            report.findings.append(WorkspaceAuditFinding("error", "unsafe-source-reference", display, error))
        elif path is not None and not path.is_file():
            report.findings.append(
                WorkspaceAuditFinding(
                    "error", "missing-source", display, "manifest source file does not exist"
                )
            )
        elif path is not None and isinstance(raw.get("sha256"), str) and _sha256(path) != raw["sha256"]:
            report.findings.append(
                WorkspaceAuditFinding(
                    "error", "source-hash-mismatch", display, "preserved source content changed"
                )
            )
    external = manifest.get("external_references", [])
    if not isinstance(external, list):
        report.findings.append(
            WorkspaceAuditFinding(
                "error",
                "invalid-external-references",
                ".opdisc/source-manifest.json",
                "external_references is not an array",
            )
        )
        external = []
    for index, raw in enumerate(external):
        path_text = raw.get("path") if isinstance(raw, dict) else None
        external_path = Path(path_text).expanduser() if isinstance(path_text, str) else None
        if external_path is not None and not external_path.is_absolute():
            external_path = root / external_path
        if external_path is None or not external_path.exists():
            report.findings.append(
                WorkspaceAuditFinding(
                    "warning",
                    "broken-external-reference",
                    f"external_references[{index}]",
                    "referenced external path is unavailable",
                )
            )

    knowledge_path = root / "knowledge" / "AUTOMATED.json"
    if knowledge_path.exists():
        knowledge = _read_json(knowledge_path, {})
        claims = knowledge.get("claims", {})
        if isinstance(claims, dict):
            for knowledge_id, raw in claims.items():
                references = raw.get("source_refs", []) if isinstance(raw, dict) else []
                for reference in references if isinstance(references, list) else []:
                    if not isinstance(reference, str) or url_like(reference):
                        continue
                    path, error = _portable_workspace_path(root, reference, f"knowledge {knowledge_id}")
                    if error or path is None or not path.exists():
                        report.findings.append(
                            WorkspaceAuditFinding(
                                "error",
                                "knowledge-missing-source",
                                f"knowledge/AUTOMATED.json#{knowledge_id}",
                                f"knowledge references missing source {reference}",
                            )
                        )
    engine_path = metadata.get("engine_path")
    if isinstance(engine_path, str) and Path(engine_path).is_dir():
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=engine_path,
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip():
                report.findings.append(
                    WorkspaceAuditFinding(
                        "warning",
                        "dirty-engine-checkout",
                        ".opdisc/workspace.json",
                        "engine checkout has local changes; updater must stop before pulling",
                    )
                )
        except (OSError, subprocess.CalledProcessError):
            pass
    return report


def url_like(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")
