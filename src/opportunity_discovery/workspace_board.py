"""Stable read model for an explicitly selected private workspace board."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace_state import (
    OPPORTUNITY_ID,
    STATE_SCHEMA_VERSION,
    WorkspaceStateError,
    _object,
    _secure_workspace_path,
    _validated_board,
    require_workspace,
)

BOARD_VIEWS = ("active", "waiting", "dismissed", "history", "all")
WAITING_PIPELINE_STATES = {"submitted", "interviewing"}
OUTCOME_PIPELINE_STATES = {"offer", "rejected", "withdrawn"}
PIPELINE_STATES = {"not-started", "preparing", *WAITING_PIPELINE_STATES, *OUTCOME_PIPELINE_STATES}


def _pipeline_state(user_state: dict[str, Any]) -> str:
    value = user_state.get("pipeline_state")
    if isinstance(value, str):
        return value
    legacy = user_state.get("status")
    return legacy if isinstance(legacy, str) and legacy in PIPELINE_STATES else "unknown"


def _lane(record: dict[str, Any], user_state: dict[str, Any], pipeline_state: str) -> str:
    status = user_state.get("status", "unreviewed")
    waiting = _object(user_state.get("waiting", {}), "user_state.waiting")
    if status == "delete" or record.get("board_state") in {"dismissed", "duplicate"}:
        return "dismissed"
    if status == "done":
        return "history"
    if waiting.get("active") is True or pipeline_state in WAITING_PIPELINE_STATES:
        return "waiting"
    if pipeline_state in OUTCOME_PIPELINE_STATES:
        return "history"
    return "active"


def _item(opportunity_id: str, record: dict[str, Any]) -> dict[str, Any]:
    if not OPPORTUNITY_ID.fullmatch(opportunity_id) or record.get("opportunity_id") != opportunity_id:
        raise WorkspaceStateError(f"board record identity mismatch for {opportunity_id}")
    collector = _object(record.get("collector_snapshot", {}), "collector_snapshot")
    facts = _object(record.get("verified_facts", {}), "verified_facts")
    review = _object(record.get("review", {}), "review")
    user_state = _object(record.get("user_state", {}), "user_state")
    pipeline = _pipeline_state(user_state)
    return {
        "opportunity_id": opportunity_id,
        "lane": _lane(record, user_state, pipeline),
        "title": collector.get("title"),
        "organization": collector.get("organization"),
        "canonical_url": collector.get("canonical_url"),
        "official_url": facts.get("official_url"),
        "board_state": record.get("board_state"),
        "updated_at": record.get("updated_at"),
        "routing_state": collector.get("routing_state"),
        "availability": facts.get("availability", "unknown"),
        "exact_deadline": facts.get("exact_deadline"),
        "pipeline_state": pipeline,
        "user_status": user_state.get("status", "unreviewed"),
        "waiting": user_state.get("waiting", {"active": False}),
        "duplicate_of": record.get("duplicate_of"),
        "verified_facts": facts,
        "eligibility": _object(record.get("eligibility", {}), "eligibility"),
        "review": review,
        "user_state": user_state,
        "provenance": collector.get("provenance", []),
        "collector_custom": _object(collector.get("custom", {}), "collector_snapshot.custom"),
        "custom": _object(record.get("custom", {}), "record.custom"),
    }


def list_workspace_board(
    root: Path,
    *,
    view: str = "active",
    board_state: str | None = None,
    user_status: str | None = None,
    pipeline_state: str | None = None,
    availability: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read a deterministic page without changing private files."""
    if view not in BOARD_VIEWS:
        raise WorkspaceStateError(f"view must be one of {BOARD_VIEWS}")
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
    board_path = _secure_workspace_path(
        root, root / ".opdisc", root / ".opdisc" / "board.json", "private board"
    )
    board = _validated_board(board_path)
    opportunities = _object(board["opportunities"], "board.opportunities")
    needle = search.casefold().strip() if search else None
    items: list[dict[str, Any]] = []
    for opportunity_id in sorted(opportunities):
        item = _item(opportunity_id, _object(opportunities[opportunity_id], "board opportunity"))
        if view != "all" and item["lane"] != view:
            continue
        if board_state is not None and item["board_state"] != board_state:
            continue
        if user_status is not None and item["user_status"] != user_status:
            continue
        if pipeline_state is not None and item["pipeline_state"] != pipeline_state:
            continue
        if availability is not None and item["availability"] != availability:
            continue
        if needle and not any(
            needle in str(item[key] or "").casefold() for key in ("opportunity_id", "title", "organization")
        ):
            continue
        items.append(item)
    total = len(items)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "workspace": str(root),
        "view": view,
        "filters": {
            "board_state": board_state,
            "user_status": user_status,
            "pipeline_state": pipeline_state,
            "availability": availability,
            "search": search,
        },
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < total else None,
        "items": items[offset : offset + limit],
    }
