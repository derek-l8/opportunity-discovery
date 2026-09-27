"""Small user-directed board commands and private operation history."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from .workspace_board import PIPELINE_STATES, _item
from .workspace_state import (
    LEGACY_PIPELINE_STATUSES,
    OPPORTUNITY_ID,
    STATE_SCHEMA_VERSION,
    USER_ACTIONS,
    WorkspaceStateError,
    _atomic_json,
    _checkpoint,
    _now,
    _object,
    _parsed_timestamp,
    _read_json,
    _secure_workspace_path,
    _validated_board,
    apply_workspace_feedback_bytes,
    require_workspace,
)


def _board(root: Path) -> tuple[Path, dict[str, Any]]:
    board_path = _secure_workspace_path(
        root, root / ".opdisc", root / ".opdisc" / "board.json", "private board"
    )
    return board_path, _validated_board(board_path)


def _record(board: dict[str, Any], opportunity_id: str) -> dict[str, Any]:
    if not OPPORTUNITY_ID.fullmatch(opportunity_id):
        raise WorkspaceStateError("opportunity_id must be a stable opportunity ID")
    opportunities = _object(board["opportunities"], "board.opportunities")
    if opportunity_id not in opportunities:
        raise WorkspaceStateError(f"{opportunity_id} is not on the private board")
    return _object(opportunities[opportunity_id], "board opportunity")


def _summary(opportunity_id: str, record: dict[str, Any]) -> dict[str, Any]:
    item = _item(opportunity_id, record)
    return {
        "lane": item["lane"],
        "user_status": item["user_status"],
        "pipeline_state": item["pipeline_state"],
        "waiting": item["waiting"],
    }


def _event_path(root: Path, event_id: str) -> Path:
    directory = root / ".opdisc" / "history" / "board"
    return _secure_workspace_path(root, directory, directory / f"{event_id}.json", "board event")


def _event(
    root: Path,
    opportunity_id: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = uuid.uuid4().hex
    document = {
        "schema_version": STATE_SCHEMA_VERSION,
        "event_id": event_id,
        "at": _now(),
        "opportunity_id": opportunity_id,
        "action": action,
        "before": before,
        "after": after,
        "details": details or {},
    }
    _atomic_json(_event_path(root, event_id), document)
    return document


def _advance_updated_at(board: dict[str, Any], at: str) -> None:
    previous = board.get("updated_at")
    if previous is None or _parsed_timestamp(at, "at") > _parsed_timestamp(previous, "board.updated_at"):
        board["updated_at"] = at


def mark_workspace_opportunity(
    root: Path,
    opportunity_id: str,
    action: str,
    *,
    reason_code: str | None = None,
    reason_text: str | None = None,
    prefer: tuple[str, ...] = (),
    avoid: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Use the existing reasoned feedback importer for direct Done/Delete."""
    if action not in USER_ACTIONS:
        raise WorkspaceStateError("action must be done or delete")
    if reason_code is not None and not reason_code.strip():
        raise WorkspaceStateError("reason_code must be non-blank")
    if reason_text is not None and not reason_text.strip():
        raise WorkspaceStateError("reason_text must be non-blank")
    if not reason_code and not reason_text:
        if prefer or avoid:
            raise WorkspaceStateError("preference signals require a reason code or text")
        return change_workspace_opportunity(root, opportunity_id, action)
    root, _metadata = require_workspace(root)
    _board_path, board = _board(root)
    before = _summary(opportunity_id, _record(board, opportunity_id))
    _event_path(root, uuid.uuid4().hex)  # preflight the history path before feedback changes state
    entry: dict[str, Any] = {
        "feedback_id": uuid.uuid4().hex,
        "opportunity_id": opportunity_id,
        "action": action,
        "preference_signals": [
            *({"name": name, "direction": "prefer"} for name in prefer),
            *({"name": name, "direction": "avoid"} for name in avoid),
        ],
    }
    if reason_code is not None:
        entry["reason_code"] = reason_code
    if reason_text is not None:
        entry["reason_text"] = reason_text
    document = {
        "schema_version": STATE_SCHEMA_VERSION,
        "recorded_at": _now(),
        "feedback": [entry],
    }
    raw = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    result = apply_workspace_feedback_bytes(root, raw)
    _board_path, updated = _board(root)
    after = _summary(opportunity_id, _record(updated, opportunity_id))
    event = _event(
        root,
        opportunity_id,
        action,
        before,
        after,
        details={
            "reason_code": reason_code,
            "reason_text": reason_text,
            "report_path": result.report_path.as_posix(),
        },
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "event": event,
        "report_path": result.report_path.as_posix(),
    }


def change_workspace_opportunity(
    root: Path,
    opportunity_id: str,
    action: str,
    *,
    pipeline_state: str | None = None,
    wait_reason: str | None = None,
    wait_until: str | None = None,
) -> dict[str, Any]:
    """Change visibility, pipeline, or waiting without touching verified facts."""
    if action not in {"done", "delete", "restore", "pipeline", "wait", "resume", "purge"}:
        raise WorkspaceStateError("unknown board action")
    if action == "pipeline" and pipeline_state not in PIPELINE_STATES:
        raise WorkspaceStateError(f"pipeline state must be one of {sorted(PIPELINE_STATES)}")
    if action == "wait":
        if not wait_reason or not wait_reason.strip():
            raise WorkspaceStateError("waiting requires a reason")
        if wait_until is not None:
            try:
                date.fromisoformat(wait_until)
            except ValueError as exc:
                raise WorkspaceStateError("wait_until must be an ISO date") from exc
    root, _metadata = require_workspace(root)
    board_path, board = _board(root)
    record = _record(board, opportunity_id)
    before = _summary(opportunity_id, record)
    user_state = _object(record.get("user_state", {}), "user_state")
    now = _now()
    if action in USER_ACTIONS:
        previous = user_state.get("status", "unreviewed")
        prior_action = _object(user_state.get("last_action", {}), "user_state.last_action")
        if "pipeline_state" not in user_state and previous in LEGACY_PIPELINE_STATUSES:
            user_state["pipeline_state"] = previous
        if previous in USER_ACTIONS:
            feedback = _object(user_state.get("feedback", {}), "user_state.feedback")
            previous = prior_action.get("prior_status", feedback.get("prior_status", "unreviewed"))
        user_state["status"] = action
        user_state["last_action"] = {
            **prior_action,
            "action": action,
            "at": now,
            "prior_status": previous,
        }
    elif action == "restore":
        if user_state.get("status") not in USER_ACTIONS:
            raise WorkspaceStateError("restore requires a Done or Delete record")
        feedback = _object(user_state.get("feedback", {}), "user_state.feedback")
        last_action = _object(user_state.get("last_action", {}), "user_state.last_action")
        previous = last_action.get("prior_status", feedback.get("prior_status", "unreviewed"))
        user_state["status"] = (
            previous if isinstance(previous, str) and previous not in USER_ACTIONS else "unreviewed"
        )
        user_state["restored_at"] = now
    elif action == "pipeline":
        user_state["pipeline_state"] = pipeline_state
        user_state["pipeline_updated_at"] = now
    elif action == "wait":
        waiting = _object(user_state.get("waiting", {}), "user_state.waiting")
        user_state["waiting"] = {
            **waiting,
            "active": True,
            "reason": wait_reason,
            "until": wait_until,
            "updated_at": now,
        }
    elif action == "resume":
        waiting = _object(user_state.get("waiting", {}), "user_state.waiting")
        if waiting.get("active") is not True:
            raise WorkspaceStateError("record is not explicitly waiting")
        user_state["waiting"] = {**waiting, "active": False, "updated_at": now}
    else:
        return _purge(root, board_path, board, opportunity_id, before)

    _event_path(root, uuid.uuid4().hex)
    record["user_state"] = user_state
    previous_updated_at = record.get("updated_at")
    if previous_updated_at is None or _parsed_timestamp(now, "now") > _parsed_timestamp(
        previous_updated_at, "record.updated_at"
    ):
        record["updated_at"] = now
    _advance_updated_at(board, now)
    _atomic_json(board_path, board)
    after = _summary(opportunity_id, record)
    event = _event(root, opportunity_id, action, before, after)
    _checkpoint(
        root,
        operation=f"board-{action}",
        operation_id=event["event_id"],
        status="complete",
        completed_steps=["updated-board", "recorded-history"],
        exact_next_action="review the updated private board",
        input_sha256=None,
    )
    return {"schema_version": STATE_SCHEMA_VERSION, "event": event}


def _purge(
    root: Path,
    board_path: Path,
    board: dict[str, Any],
    opportunity_id: str,
    before: dict[str, Any],
) -> dict[str, Any]:
    artifacts: list[Path] = []
    for folder in ("opportunities", "applications"):
        base = root / folder
        artifacts.append(_secure_workspace_path(root, base, base / opportunity_id, "purge artifact"))
    history_dir = root / ".opdisc" / "history" / "board"
    events: list[Path] = []
    if history_dir.exists():
        _secure_workspace_path(root, history_dir, history_dir, "board history")
        for path in history_dir.glob("*.json"):
            secure = _secure_workspace_path(root, history_dir, path, "board event")
            if _read_json(secure, {}).get("opportunity_id") == opportunity_id:
                events.append(secure)
    board["opportunities"].pop(opportunity_id)
    _advance_updated_at(board, _now())
    _atomic_json(board_path, board)
    existing_artifacts = [path for path in artifacts if path.exists()]
    for path in existing_artifacts:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for path in events:
        path.unlink()
    _checkpoint(
        root,
        operation="board-purge",
        operation_id=uuid.uuid4().hex,
        status="complete",
        completed_steps=["removed-board-record", "removed-artifacts", "removed-board-history"],
        exact_next_action="review the private board and retained backup archives",
        input_sha256=None,
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "action": "purge",
        "before": before,
        "removed_artifacts": [path.relative_to(root).as_posix() for path in existing_artifacts],
        "removed_board_events": len(events),
    }


def list_workspace_history(
    root: Path, *, opportunity_id: str | None = None, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Read Phase 6 board events and existing Phase 4/5 operation reports."""
    if opportunity_id is not None and not OPPORTUNITY_ID.fullmatch(opportunity_id):
        raise WorkspaceStateError("opportunity_id must be a stable opportunity ID")
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 200
    ):
        raise WorkspaceStateError("offset must be non-negative and limit must be between 1 and 200")
    root, _metadata = require_workspace(root)
    events: list[dict[str, Any]] = []
    linked_reports: set[str] = set()
    history_dir = root / ".opdisc" / "history" / "board"
    if history_dir.exists():
        _secure_workspace_path(root, history_dir, history_dir, "board history")
        for path in history_dir.glob("*.json"):
            secure = _secure_workspace_path(root, history_dir, path, "board event")
            event = _read_json(secure, {})
            if event.get("schema_version") != STATE_SCHEMA_VERSION:
                raise WorkspaceStateError(f"invalid board event: {secure}")
            if opportunity_id is None or event.get("opportunity_id") == opportunity_id:
                events.append({"kind": "board-action", **event})
                details = _object(event.get("details", {}), "board event details")
                report_path = details.get("report_path")
                if isinstance(report_path, str):
                    linked_reports.add(Path(report_path).name)
    if opportunity_id is None:
        reports_dir = root / ".opdisc" / "reports"
        if reports_dir.exists():
            _secure_workspace_path(root, reports_dir, reports_dir, "operation reports")
            for path in reports_dir.glob("*.json"):
                if path.name in linked_reports:
                    continue
                secure = _secure_workspace_path(root, reports_dir, path, "operation report")
                report = _read_json(secure, {})
                at = report.get("reviewed_at", report.get("recorded_at"))
                if not isinstance(at, str):
                    raise WorkspaceStateError(f"operation report lacks a timestamp: {secure}")
                events.append(
                    {
                        "kind": "operation-report",
                        "event_id": str(report.get("operation_id", path.stem)),
                        "at": at,
                        "action": "review" if "reviewed_at" in report else "feedback",
                        "report": report,
                    }
                )
    events.sort(
        key=lambda item: (_parsed_timestamp(item["at"], "history event time"), str(item["event_id"])),
        reverse=True,
    )
    total = len(events)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "workspace": root.as_posix(),
        "opportunity_id": opportunity_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < total else None,
        "events": events[offset : offset + limit],
    }
