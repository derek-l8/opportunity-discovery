"""Provider-neutral review-response validation.

The importer accepts source-backed, advisory review results at the public/private
file boundary.  It deliberately does not mutate collector state: Phase 4 owns
connecting validated results to a private board or knowledge store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = "1.0"
DISPOSITIONS = {"promote", "defer", "dismiss", "duplicate"}
AVAILABILITY = {"open", "closed", "future-cycle", "unknown"}
IDENTITY_EVIDENCE = {
    "provider-requisition-id",
    "normalized-official-url",
    "organization-requisition-id",
    "exact-composite",
}
OPPORTUNITY_ID_PATTERN = re.compile(r"^opp_[0-9a-f]{32}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class ReviewContractError(ValueError):
    """A review response does not satisfy the provider-neutral contract."""


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewContractError(f"{path} must be an object")
    return value


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ReviewContractError(f"{path} must be a non-empty string")
    return value


def _official_url(value: Any, path: str) -> str:
    url = _string(value, path)
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ReviewContractError(f"{path} is invalid: {exc}") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ReviewContractError(f"{path} must be an http(s) URL")
    return url


def _timestamp(value: Any, path: str) -> str:
    timestamp = _string(value, path)
    if not TIMESTAMP_PATTERN.fullmatch(timestamp):
        raise ReviewContractError(f"{path} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewContractError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReviewContractError(f"{path} must include a UTC offset or Z")
    return timestamp


def _date_or_timestamp(value: Any, path: str) -> str:
    text = _string(value, path)
    if "T" in text:
        return _timestamp(text, path)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ReviewContractError(f"{path} must be an ISO-8601 date or timestamp")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ReviewContractError(f"{path} must be an ISO-8601 date or timestamp") from exc
    return text


def _opportunity_id(value: Any, path: str) -> str:
    identifier = _string(value, path)
    if not OPPORTUNITY_ID_PATTERN.fullmatch(identifier):
        raise ReviewContractError(f"{path} must be a stable opportunity ID")
    return identifier


def _generation_id(value: Any, path: str) -> str:
    identifier = _string(value, path)
    if not SHA256_PATTERN.fullmatch(identifier):
        raise ReviewContractError(f"{path} must be a lowercase SHA-256 value")
    return identifier


def validate_review_response(document: Any) -> dict[str, Any]:
    """Validate and return a normalized, custom-preserving response document."""
    root = _object(document, "response")
    allowed_root = {"schema_version", "packet_generation_id", "reviewed_at", "decisions", "custom"}
    unknown = set(root) - allowed_root
    if unknown:
        raise ReviewContractError(
            "unknown top-level fields must be placed under custom: " + ", ".join(sorted(unknown))
        )
    if root.get("schema_version") != SCHEMA_VERSION:
        raise ReviewContractError(f"schema_version must be {SCHEMA_VERSION!r}")
    _generation_id(root.get("packet_generation_id"), "packet_generation_id")
    _timestamp(root.get("reviewed_at"), "reviewed_at")
    custom = root.get("custom", {})
    _object(custom, "custom")
    decisions = root.get("decisions")
    if not isinstance(decisions, list):
        raise ReviewContractError("decisions must be an array")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(decisions):
        path = f"decisions[{index}]"
        decision = _object(raw, path)
        allowed = {
            "opportunity_id",
            "disposition",
            "reason_codes",
            "official_evidence",
            "duplicate_of",
            "identity_evidence",
            "custom",
        }
        extra = set(decision) - allowed
        if extra:
            raise ReviewContractError(
                f"{path} unknown fields must be placed under custom: " + ", ".join(sorted(extra))
            )
        opportunity_id = _opportunity_id(decision.get("opportunity_id"), f"{path}.opportunity_id")
        if opportunity_id in seen:
            raise ReviewContractError(f"duplicate decision for opportunity_id {opportunity_id!r}")
        seen.add(opportunity_id)
        disposition = decision.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ReviewContractError(f"{path}.disposition must be one of {sorted(DISPOSITIONS)}")
        reasons = decision.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(item, str) and item.strip() for item in reasons)
        ):
            raise ReviewContractError(f"{path}.reason_codes must be a non-empty string array")
        evidence = _object(decision.get("official_evidence"), f"{path}.official_evidence")
        evidence_allowed = {"url", "checked_at", "availability", "exact_deadline", "notes_excerpt"}
        evidence_extra = set(evidence) - evidence_allowed
        if evidence_extra:
            raise ReviewContractError(f"{path}.official_evidence contains unknown fields")
        _official_url(evidence.get("url"), f"{path}.official_evidence.url")
        _timestamp(evidence.get("checked_at"), f"{path}.official_evidence.checked_at")
        if evidence.get("availability") not in AVAILABILITY:
            raise ReviewContractError(
                f"{path}.official_evidence.availability must be one of {sorted(AVAILABILITY)}"
            )
        excerpt = evidence.get("notes_excerpt")
        if excerpt is not None and (not isinstance(excerpt, str) or len(excerpt) > 600):
            raise ReviewContractError(f"{path}.official_evidence.notes_excerpt must be <= 600 characters")
        exact_deadline = evidence.get("exact_deadline")
        if exact_deadline is not None:
            _date_or_timestamp(exact_deadline, f"{path}.official_evidence.exact_deadline")
        duplicate_of = decision.get("duplicate_of")
        identity_evidence = decision.get("identity_evidence")
        if disposition == "duplicate":
            duplicate_of = _opportunity_id(duplicate_of, f"{path}.duplicate_of")
            if duplicate_of == opportunity_id:
                raise ReviewContractError(f"{path}.duplicate_of must identify another opportunity")
            if identity_evidence not in IDENTITY_EVIDENCE:
                raise ReviewContractError(f"{path}.identity_evidence must be strong identity evidence")
        elif duplicate_of is not None or identity_evidence is not None:
            raise ReviewContractError(
                f"{path}.duplicate_of and identity_evidence are only valid for duplicate dispositions"
            )
        _object(decision.get("custom", {}), f"{path}.custom")
        normalized.append(decision)

    return {**root, "custom": custom, "decisions": normalized}


def load_generation_candidates(manifest_path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    """Load and integrity-check the candidate generation named by a manifest."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewContractError(f"could not read export manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ReviewContractError("export manifest must be an object")
    generation_id = manifest.get("generation_id")
    generation_id = _generation_id(generation_id, "export manifest generation_id")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReviewContractError("export manifest files must be an array")
    entries = [
        entry for entry in files if isinstance(entry, dict) and entry.get("filename") == "candidates.jsonl"
    ]
    if len(entries) != 1:
        raise ReviewContractError("export manifest must identify exactly one candidates.jsonl artifact")
    entry = entries[0]
    expected_hash = entry.get("sha256")
    expected_hash = _generation_id(expected_hash, "candidates artifact recorded SHA-256")
    filename = entries[0]["filename"]
    candidate_path = manifest_path.parent / filename
    try:
        payload = candidate_path.read_bytes()
    except OSError as exc:
        raise ReviewContractError(f"could not read candidates artifact: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ReviewContractError("candidates artifact SHA-256 does not match export manifest")
    candidates: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            raise ReviewContractError(f"candidates artifact line {line_number} is empty")
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewContractError(f"candidates artifact line {line_number} is malformed JSON") from exc
        if not isinstance(candidate, dict):
            raise ReviewContractError(f"candidates artifact line {line_number} must be an object")
        identifier = _opportunity_id(
            candidate.get("opportunity_id"), f"candidates line {line_number} opportunity_id"
        )
        if identifier in candidates:
            raise ReviewContractError(f"candidates artifact contains duplicate opportunity_id {identifier!r}")
        candidates[identifier] = candidate
    return generation_id, candidates


def load_review_response_for_generation(
    input_path: Path, manifest_path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate one response against an integrity-checked export generation."""
    try:
        document = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewContractError(f"could not read review response: {exc}") from exc
    generation_id, candidates = load_generation_candidates(manifest_path)
    normalized = validate_review_response(document)
    if normalized["packet_generation_id"] != generation_id:
        raise ReviewContractError("packet_generation_id does not match the current export manifest")
    for index, decision in enumerate(normalized["decisions"]):
        opportunity_id = decision["opportunity_id"]
        if opportunity_id not in candidates:
            raise ReviewContractError(
                f"decisions[{index}].opportunity_id is not in the current candidates artifact"
            )
        if decision["disposition"] == "duplicate" and decision["duplicate_of"] not in candidates:
            raise ReviewContractError(
                f"decisions[{index}].duplicate_of is not in the current candidates artifact"
            )
    return normalized, candidates


def import_review_response(input_path: Path, output_path: Path, *, manifest_path: Path) -> dict[str, Any]:
    """Validate a response and atomically copy its normalized form to the boundary output."""
    normalized, _candidates = load_review_response_for_generation(input_path, manifest_path)
    payload = (json.dumps(normalized, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output_path)
    return {"path": str(output_path), "decision_count": len(normalized["decisions"])}
