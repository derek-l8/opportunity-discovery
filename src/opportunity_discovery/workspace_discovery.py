"""Read-only curated and full-queue views for an external private workspace."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .workspace_board import _item
from .workspace_state import (
    OPPORTUNITY_ID,
    WorkspaceStateError,
    _object,
    _secure_workspace_path,
    _validated_board,
    require_workspace,
)

_IMPORTED_DISPOSITIONS = {"promote", "defer", "dismiss", "duplicate"}
ENGAGEMENT_TYPES = (
    "internship",
    "co-op",
    "contract",
    "research",
    "fellowship",
    "program",
    "event",
    "full-time",
    "unknown",
)


def _has_imported_decision(record: dict[str, Any]) -> bool:
    review = record.get("review")
    return (
        isinstance(review, dict)
        and bool(review.get("reviewed_at"))
        and review.get("disposition") in _IMPORTED_DISPOSITIONS
    )


def _board_records(root: Path) -> dict[str, Any]:
    root, _ = require_workspace(root)
    path = _secure_workspace_path(root, root / ".opdisc", root / ".opdisc" / "board.json", "private board")
    return _object(_validated_board(path)["opportunities"], "board.opportunities")


def _page(items: list[dict[str, Any]], offset: int, limit: int) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= 200:
        raise WorkspaceStateError("offset must be non-negative and limit must be between 1 and 200")
    return {
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < len(items) else None,
        "items": items[offset : offset + limit],
    }


def _next_action(item: dict[str, Any]) -> str:
    if item["board_state"] == "active":
        if item["availability"] == "future-cycle":
            return "Recheck the official page and prepare for the next cycle."
        return "Recheck the official page, then decide whether to prepare an application."
    return "Investigate the official page and unresolved availability or eligibility facts."


def list_curated_home(root: Path, *, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    """Show only imported review decisions that still call for user attention."""
    records = _board_records(root)
    reviewed_count = 0
    items: list[dict[str, Any]] = []
    for identifier, record in records.items():
        record_obj = _object(record, f"board.{identifier}")
        item = _item(identifier, record_obj)
        if not _has_imported_decision(record_obj):
            continue
        reviewed_count += 1
        if item["lane"] != "active" or item["board_state"] not in {"active", "research_needed"}:
            continue
        items.append({**item, "next_action": _next_action(item)})
    # The imported disposition drives the order. A recorded exact deadline only
    # orders promoted items within that group; public generic scores do not.
    items.sort(
        key=lambda item: (
            item["board_state"] != "active",
            item["exact_deadline"] or "9999-12-31",
            item["opportunity_id"],
        )
    )
    return {**_page(items, offset, limit), "reviewed_count": reviewed_count}


def default_manifest_path(root: Path) -> Path:
    """Use the installed engine's default output; callers may select another manifest."""
    _, metadata = require_workspace(root)
    engine_path = metadata.get("engine_path")
    if not isinstance(engine_path, str) or not engine_path:
        raise WorkspaceStateError("workspace metadata does not identify an engine checkout")
    return Path(engine_path) / "output" / "export_manifest.json"


def load_current_queue(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the complete queue only when its exact artifact matches the manifest."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceStateError(f"current public export unavailable: {exc}") from exc
    manifest = _object(manifest, "export manifest")
    generation = manifest.get("generation_id")
    if (
        not isinstance(generation, str)
        or len(generation) != 64
        or any(char not in "0123456789abcdef" for char in generation)
    ):
        raise WorkspaceStateError("export manifest has an invalid generation ID")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise WorkspaceStateError("export manifest files must be an array")
    entries = [
        entry for entry in files if isinstance(entry, dict) and entry.get("filename") == "review_queue.jsonl"
    ]
    if len(entries) != 1:
        raise WorkspaceStateError("export manifest must identify exactly one review_queue.jsonl")
    expected = entries[0].get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise WorkspaceStateError("review queue manifest hash is invalid")
    try:
        payload = (manifest_path.parent / "review_queue.jsonl").read_bytes()
    except OSError as exc:
        raise WorkspaceStateError(f"current review queue unavailable: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != expected:
        raise WorkspaceStateError("review queue hash does not match export manifest")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(payload.splitlines(), 1):
        try:
            candidate = _object(json.loads(line), f"review queue line {number}")
        except (ValueError, json.JSONDecodeError) as exc:
            raise WorkspaceStateError(f"review queue line {number} is invalid: {exc}") from exc
        identifier = candidate.get("opportunity_id")
        if not isinstance(identifier, str) or not OPPORTUNITY_ID.fullmatch(identifier) or identifier in seen:
            raise WorkspaceStateError(f"review queue line {number} has an invalid or repeated opportunity ID")
        seen.add(identifier)
        candidates.append(candidate)
    return manifest, candidates


def list_explore(
    root: Path,
    manifest_path: Path,
    *,
    search: str | None = None,
    route: str | None = None,
    engagement_type: str | None = None,
    review_status: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    """Search every current queue lead, including ones absent from private review."""
    if route not in (None, "included", "research_needed"):
        raise WorkspaceStateError("route must be included or research_needed")
    if engagement_type is not None and engagement_type not in ENGAGEMENT_TYPES:
        raise WorkspaceStateError("invalid opportunity type")
    if review_status not in (None, "reviewed", "unreviewed"):
        raise WorkspaceStateError("review status must be reviewed or unreviewed")
    manifest, queue = load_current_queue(manifest_path)
    records = _board_records(root)
    reviewed_ids = {
        identifier
        for identifier, record in records.items()
        if isinstance(record, dict) and _has_imported_decision(record)
    }
    needle = search.strip().casefold() if search else ""
    items: list[dict[str, Any]] = []
    reviewed_count = 0
    for candidate in queue:
        identifier = candidate["opportunity_id"]
        status = "reviewed" if identifier in reviewed_ids else "unreviewed"
        reviewed_count += status == "reviewed"
        if route and candidate.get("routing_state") != route:
            continue
        if engagement_type and candidate.get("engagement_type") != engagement_type:
            continue
        if review_status and status != review_status:
            continue
        if needle and not any(
            needle in str(candidate.get(field) or "").casefold()
            for field in ("opportunity_id", "title", "organization", "location_text", "description_excerpt")
        ):
            continue
        items.append({**candidate, "review_status": status})
    items.sort(key=lambda item: item["opportunity_id"])
    items.sort(key=lambda item: str(item.get("first_seen") or ""), reverse=True)
    return {
        **_page(items, offset, limit),
        "queue_count": len(queue),
        "reviewed_count": reviewed_count,
        "unreviewed_count": len(queue) - reviewed_count,
        "generation_id": manifest["generation_id"],
        "generated_at": manifest.get("generated_at"),
    }
