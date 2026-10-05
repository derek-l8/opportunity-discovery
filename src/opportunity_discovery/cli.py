"""opdisc command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from . import audit as audit_mod
from . import db as dbm
from .config import load_config
from .export import build_source_health, export_all
from .lock import RunLock
from .models import SourceSpec
from .prune import apply_prune, plan_prune
from .registry import load_sources, sync_sources_to_db
from .review_contract import ReviewContractError, import_review_response
from .runner import ensure_ready, run_full_workflow
from .validate_sources import validate_all
from .workspace import WorkspaceInitError, initialize_workspace
from .workspace_actions import (
    change_workspace_opportunity,
    list_workspace_history,
    mark_workspace_opportunity,
)
from .workspace_application import ARTIFACT_TYPES, create_application_request
from .workspace_board import BOARD_VIEWS, PIPELINE_STATES, list_workspace_board
from .workspace_constraints import compact_review_batch
from .workspace_dashboard import serve_workspace_dashboard
from .workspace_discovery import default_manifest_path
from .workspace_recovery import (
    audit_workspace,
    backup_workspace,
    compare_knowledge_snapshot,
    list_knowledge_snapshots,
    restore_knowledge_snapshot,
    restore_workspace_backup,
)
from .workspace_screening import (
    LANES,
    REVIEW_ACTIONS,
    STATES,
    apply_screening_response,
    list_personal_feed,
    screen_collection,
    set_screening_profile,
)
from .workspace_state import (
    WorkspaceStateError,
    apply_workspace_feedback,
    apply_workspace_review,
)


def cmd_workspace_screening(args: argparse.Namespace) -> int:
    try:
        root = Path(args.workspace)
        if args.command == "workspace-profile":
            result = set_screening_profile(root, json.loads(Path(args.profile).read_text(encoding="utf-8")))
        else:
            manifest = Path(args.manifest) if args.manifest else default_manifest_path(root)
            if args.command == "workspace-screen":
                result = screen_collection(root, manifest)
            elif args.command == "workspace-apply-screening":
                result = apply_screening_response(
                    root, json.loads(Path(args.response).read_text(encoding="utf-8")), manifest
                )
            else:
                result = list_personal_feed(
                    root,
                    manifest,
                    state_filter="all" if args.audit_sample else args.state,
                    lane=args.lane,
                    search=args.search,
                    uncapped=args.uncapped or args.audit_sample,
                    offset=args.offset,
                    limit=args.limit,
                    review_only=not args.include_deferred
                    and not args.audit_sample
                    and not args.review_action
                    and args.state not in ("all", "low-relevance"),
                    review_action=args.review_action,
                    audit_sample=args.audit_sample,
                )
                if args.compact:
                    result = compact_review_batch(result)
        print(json.dumps(result, indent=2))
        return 0
    except (WorkspaceStateError, OSError, ValueError) as exc:
        print(f"ERROR private screening: {exc}", file=sys.stderr)
        return 2


def _setup_logging(quiet: bool) -> None:
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _load(cfg_path: str | None):  # type: ignore[no-untyped-def]
    cfg, errors = load_config(Path(cfg_path) if cfg_path else None)
    return cfg, errors


# --------------------------------------------------------------------------- commands
def cmd_init(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        print("config errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2
    conn = dbm.connect(cfg.paths.data_dir / "opdisc.sqlite3")
    applied = dbm.migrate(conn)
    sources, src_errors = load_sources(cfg.sources_file)
    sync_sources_to_db(conn, sources)
    for d in (cfg.paths.data_dir, cfg.paths.output_dir, cfg.paths.logs_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    if not args.quiet:
        print(f"storage ready at {cfg.paths.data_dir}")
        print(f"migrations applied: {applied or 'none pending'}")
        print(f"registry synced: {len(sources)} sources")
        if src_errors:
            print("registry warnings:", file=sys.stderr)
            for e in src_errors:
                print(f"  - {e}", file=sys.stderr)
    conn.close()
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    sources: list[SourceSpec] = []
    src_errors: list[str] = []
    if cfg:
        sources, src_errors = load_sources(cfg.sources_file)
    all_errors = errors + [f"sources.toml:{e}" for e in src_errors]
    payload = {
        "ok": not all_errors,
        "config": str(cfg.config_path) if cfg else None,
        "sources_file": str(cfg.sources_file) if cfg else None,
        "source_count": len(sources),
        "enabled_sources": sum(1 for s in sources if s.enabled),
        "errors": all_errors,
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if all_errors:
            for e in all_errors:
                print(f"ERROR {e}")
        else:
            print(f"OK config={payload['config']} sources={payload['source_count']}")
    return 0 if not all_errors else 2


def cmd_init_workspace(args: argparse.Namespace) -> int:
    try:
        result = initialize_workspace(
            Path(args.workspace),
            engine_path=Path(args.engine_path) if args.engine_path else None,
        )
    except (OSError, WorkspaceInitError) as exc:
        print(f"ERROR workspace not initialized: {exc}", file=sys.stderr)
        return 2
    payload = result.to_dict()
    if args.json_output:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(f"workspace ready at {result.root}")
        print(
            f"created {len(result.created_files)} starter files; "
            f"updated {len(result.updated_files)} machine files; "
            f"preserved {len(result.preserved_files)}"
        )
        for warning in result.warnings:
            print(f"WARNING {warning}", file=sys.stderr)
    return 0


def cmd_workspace_apply_review(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest) if args.manifest else None
    if manifest is None:
        cfg, errors = _load(args.config)
        if errors:
            for error in errors:
                print(f"ERROR {error}", file=sys.stderr)
            return 2
        manifest = cfg.paths.output_dir / "export_manifest.json"
    try:
        result = apply_workspace_review(
            Path(args.workspace),
            Path(args.response),
            manifest_path=manifest,
        )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace review not applied: {exc}", file=sys.stderr)
        return 2
    payload = result.to_dict()
    if args.json_output:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(
            f"applied {result.decision_count} decisions: {result.promoted} active, "
            f"{result.research_needed} research needed, {result.dismissed} dismissed, "
            f"{result.duplicates} duplicates"
        )
        print(f"material changes: {len(result.material_changes)} -> {result.report_path}")
    return 0


def cmd_workspace_apply_feedback(args: argparse.Namespace) -> int:
    try:
        result = apply_workspace_feedback(Path(args.workspace), Path(args.feedback))
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace feedback not applied: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(
            f"applied {result.feedback_count} reasoned feedback entries; "
            f"updated {result.preference_signals_updated} soft preference signals"
        )
    return 0


def cmd_workspace_board(args: argparse.Namespace) -> int:
    try:
        page = list_workspace_board(
            Path(args.workspace),
            view=args.view,
            board_state=args.board_state,
            user_status=args.user_status,
            pipeline_state=args.pipeline_state,
            availability=args.availability,
            search=args.search,
            offset=args.offset,
            limit=args.limit,
        )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace board not read: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(page, indent=2))
    elif not args.quiet:
        print(
            f"{page['total']} records in {page['view']}; showing {len(page['items'])} from {page['offset']}"
        )
        for item in page["items"]:
            print(f"{item['opportunity_id']}  {item['title'] or '(untitled)'}  [{item['lane']}]")
    return 0


def cmd_workspace_action(args: argparse.Namespace) -> int:
    try:
        if args.board_action in {"done", "delete"}:
            result = mark_workspace_opportunity(
                Path(args.workspace),
                args.opportunity_id,
                args.board_action,
                reason_code=args.reason_code,
                reason_text=args.reason_text,
                prefer=tuple(args.prefer),
                avoid=tuple(args.avoid),
            )
        else:
            result = change_workspace_opportunity(
                Path(args.workspace),
                args.opportunity_id,
                args.board_action,
                pipeline_state=getattr(args, "pipeline_state", None),
                wait_reason=getattr(args, "reason", None),
                wait_until=getattr(args, "until", None),
            )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace action not applied: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(f"{args.board_action}: {args.opportunity_id}")
    return 0


def cmd_workspace_history(args: argparse.Namespace) -> int:
    try:
        page = list_workspace_history(
            Path(args.workspace),
            opportunity_id=args.opportunity_id,
            offset=args.offset,
            limit=args.limit,
        )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace history not read: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(page, indent=2))
    elif not args.quiet:
        print(f"{page['total']} history events; showing {len(page['events'])} from {page['offset']}")
        for event in page["events"]:
            print(f"{event['at']}  {event['action']}  {event.get('opportunity_id', '')}")
    return 0


def cmd_workspace_dashboard(args: argparse.Namespace) -> int:
    try:
        serve_workspace_dashboard(
            Path(args.workspace),
            port=args.port,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
    except (OSError, WorkspaceStateError, ValueError) as exc:
        print(f"ERROR workspace dashboard not started: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_workspace_request(args: argparse.Namespace) -> int:
    try:
        result = create_application_request(
            Path(args.workspace),
            args.opportunity_id,
            args.artifact_type,
            args.request_text,
            references=tuple(args.reference),
        )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR application request not created: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(f"request created: {result['request_path']}")
        print("Open HANDOFF.md in that folder with your chosen agent to prepare the artifact.")
    return 0


def cmd_knowledge_snapshots(args: argparse.Namespace) -> int:
    try:
        snapshots = list_knowledge_snapshots(Path(args.workspace))
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR knowledge snapshots unavailable: {exc}", file=sys.stderr)
        return 2
    payload = {"schema_version": "1.0", "snapshots": [item.to_dict() for item in snapshots]}
    if args.json_output:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        for snapshot in snapshots:
            print(f"{snapshot.snapshot_id}  {snapshot.created_at}  {len(snapshot.files)} files")
    return 0


def cmd_compare_knowledge(args: argparse.Namespace) -> int:
    try:
        result = compare_knowledge_snapshot(Path(args.workspace), args.snapshot_id)
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR knowledge snapshot not compared: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(f"snapshot {args.snapshot_id}: {len(result['changes'])} changed paths")
        for change in result["changes"]:
            print(f"  {change['change']}: {change['path']}")
    return 0


def cmd_restore_knowledge(args: argparse.Namespace) -> int:
    try:
        result = restore_knowledge_snapshot(Path(args.workspace), args.snapshot_id)
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR knowledge snapshot not restored: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(f"restored {len(result['restored_files'])} files from {args.snapshot_id}")
        print(f"pre-restore snapshot: {result['pre_restore_snapshot_id']}")
    return 0


def cmd_backup_workspace(args: argparse.Namespace) -> int:
    try:
        result = backup_workspace(Path(args.workspace), Path(args.output), kind=args.kind)
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace not backed up: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(f"created {result.kind} backup with {result.file_count} files -> {result.path}")
        print(f"WARNING {result.warning}", file=sys.stderr)
    return 0


def cmd_restore_workspace(args: argparse.Namespace) -> int:
    try:
        result = restore_workspace_backup(
            Path(args.workspace),
            Path(args.archive),
            pre_restore_path=Path(args.pre_restore_output) if args.pre_restore_output else None,
        )
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace backup not restored: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(f"restored {result.restored_files} files from {result.archive}")
        print(f"pre-restore backup: {result.pre_restore_backup}")
    return 0


def cmd_audit_workspace(args: argparse.Namespace) -> int:
    try:
        report = audit_workspace(Path(args.workspace))
    except (OSError, WorkspaceStateError) as exc:
        print(f"ERROR workspace not audited: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    elif not args.quiet:
        print(
            f"workspace audit: {len(report.errors)} errors, "
            f"{len(report.findings) - len(report.errors)} warnings"
        )
        for finding in report.findings:
            print(f"  [{finding.severity}] {finding.rule}: {finding.path} {finding.detail}")
    return 1 if report.errors else 0


def cmd_validate_sources(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    conn = dbm.connect(cfg.paths.data_dir / "opdisc.sqlite3")
    dbm.migrate(conn)
    sources, _src_errors = load_sources(cfg.sources_file)
    sync_sources_to_db(conn, sources)
    if args.source_id:
        sources = [s for s in sources if s.source_id == args.source_id]
        if not sources:
            print(f"unknown source: {args.source_id}", file=sys.stderr)
            return 2
    results = validate_all(sources, conn, cfg, concurrency=args.concurrency)
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    if args.json_output:
        print(json.dumps({"counts": counts, "results": results}, indent=2))
    elif not args.quiet:
        for sid, r in sorted(results.items()):
            print(f"{r['status']:>18}  {sid}: {r['detail']}")
        print(f"\ncounts: {counts}")
    conn.close()
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    from .models import RunSummary
    from .runner import new_run_id, run_collect, workflow_exit_code

    conn = ensure_ready(cfg)
    run_id = new_run_id()
    summary = RunSummary(run_id=run_id, started_at=datetime.now(UTC).isoformat())
    try:
        with RunLock(cfg.paths.data_dir / "run.lock"):
            run_collect(conn, cfg, run_id, summary, force=args.force)
    except BlockingIOError as exc:
        print(f"another run is active: {exc}", file=sys.stderr)
        return 3
    finally:
        conn.close()
    if args.json_output:
        print(json.dumps(summary.to_dict(), indent=2))
    elif not args.quiet:
        print(_summary_line(summary))
    return workflow_exit_code(summary)


def cmd_run(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    conn = ensure_ready(cfg)
    try:
        with RunLock(cfg.paths.data_dir / "run.lock"):
            code, summary = run_full_workflow(conn, cfg, force=args.force)
    except BlockingIOError as exc:
        print(f"another run is active: {exc}", file=sys.stderr)
        return 3
    finally:
        conn.close()
    if args.json_output:
        print(json.dumps(summary.to_dict(), indent=2))
    elif not args.quiet:
        print(_summary_line(summary))
    return code


def cmd_export(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    conn = ensure_ready(cfg)
    artifacts = export_all(conn, cfg, None)
    conn.close()
    if args.json_output:
        print(json.dumps(artifacts, indent=2))
    elif not args.quiet:
        for k, v in artifacts.items():
            if isinstance(v, dict):
                print(f"{k}: {v.get('path')} count={v.get('count')}")
            else:
                print(f"{k}: {v}")
    return 0


def cmd_source_health(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors and not args.quiet:
        for e in errors:
            print(f"WARN config: {e}", file=sys.stderr)
    conn = ensure_ready(cfg)
    doc = build_source_health(conn, datetime.now(UTC).isoformat())
    conn.close()
    if args.json_output:
        print(json.dumps(doc, indent=2))
    elif not args.quiet:
        print(f"summary: {doc['summary']}")
        for s in doc["sources"]:
            print(f"  {s['health_state']:>14}  {s['source_id']} ({s['validation_status']})")
    return 0


def cmd_import_review(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 2
    manifest_path = cfg.paths.output_dir / "export_manifest.json"
    try:
        result = import_review_response(
            Path(args.response),
            cfg.paths.output_dir / "review_response.json",
            manifest_path=manifest_path,
        )
    except ReviewContractError as exc:
        print(f"ERROR review response not imported: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(f"validated {result['decision_count']} decisions -> {result['path']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg, _errors = _load(args.config)
    conn = ensure_ready(cfg)
    last_run = conn.execute("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    opp_counts = {
        "total": conn.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"],
        "active": conn.execute("SELECT COUNT(*) n FROM opportunities WHERE active=1").fetchone()["n"],
        "new_last_run": conn.execute(
            "SELECT COUNT(*) n FROM changes WHERE change_type='new' AND detected_at > COALESCE("
            "(SELECT MAX(exported_at) FROM export_checkpoints), '1970-01-01')"
        ).fetchone()["n"],
        "review_queue_est": conn.execute(
            "SELECT COUNT(*) n FROM opportunities o WHERE o.active=1 AND"
            " NOT EXISTS (SELECT 1 FROM json_each(o.reason_codes_json) je WHERE je.value LIKE 'exclude:%')"
            " AND json_array_length(o.role_family_tags_json) > 0 AND o.generic_score > 0"
        ).fetchone()["n"],
    }
    health = build_source_health(conn, datetime.now(UTC).isoformat())
    conn.close()
    payload = {
        "schema_version": "1.0",
        "database": str(cfg.paths.data_dir / "opdisc.sqlite3"),
        "last_run": dict(last_run) if last_run else None,
        "opportunities": opp_counts,
        "source_health_summary": health["summary"],
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(
            f"opportunities: {opp_counts['total']} total, {opp_counts['active']} active,"
            f" ~{opp_counts['review_queue_est']} review-queue candidates"
        )
        print(f"last run: {payload['last_run']['run_id'] if payload['last_run'] else 'none'}")
        print(f"sources: {health['summary']}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.repo_root) if args.repo_root else Path.cwd().resolve()
    report = audit_mod.audit_repository(root)
    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    elif not args.quiet:
        print(
            f"scanned {report.files_scanned} publication-candidate files;"
            f" {len(report.errors)} errors, "
            f"{len(report.findings) - len(report.errors)} warnings"
        )
        for f in report.findings:
            loc = f.path + (f":{f.line}" if f.line else "")
            print(f"  [{f.severity}] {f.rule}: {loc} {f.detail or ''}")
    return 1 if report.errors else 0


def cmd_add_source(args: argparse.Namespace) -> int:
    """Append a source to the registry file (documented equivalent to hand-editing)."""
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    spec = SourceSpec(
        source_id=args.source_id,
        display_name=args.display_name or args.source_id,
        organization=args.organization,
        adapter=args.adapter,
        landing_url=args.landing_url,
        endpoint_config=json.loads(args.endpoint_json) if args.endpoint_json else {},
        categories=args.category.split(",") if args.category else [],
        official_source=bool(args.official),
    )
    spec_errors = spec.validate()
    if spec_errors:
        for e in spec_errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    block = [
        "[[sources]]",
        f'source_id = "{spec.source_id}"',
        f'display_name = "{spec.display_name}"',
        f'organization = "{spec.organization}"',
        f'adapter = "{spec.adapter}"',
    ]
    if spec.landing_url:
        block.append(f'landing_url = "{spec.landing_url}"')
    block.append("endpoint_config = " + json.dumps(spec.endpoint_config))
    if spec.categories:
        cats = ", ".join(f'"{c.strip()}"' for c in spec.categories)
        block.append(f"categories = [{cats}]")
    if spec.official_source:
        block.append("official_source = true")
    text = "\n".join(block) + "\n\n"
    existing = cfg.sources_file.read_text(encoding="utf-8") if cfg.sources_file.exists() else ""
    if f'source_id = "{spec.source_id}"' in existing:
        print(f"source already present: {spec.source_id}", file=sys.stderr)
        return 1
    cfg.sources_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.sources_file, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(text)
    if not args.quiet:
        print(f"appended {spec.source_id} to {cfg.sources_file}; run `opdisc validate-sources`")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    cfg, errors = _load(args.config)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    conn = ensure_ready(cfg)
    plans = plan_prune(
        conn,
        cache_days=cfg.fetch.cache_days,
        log_days=cfg.log_retention_days,
        check_days=cfg.source_check_retention_days,
    )
    deleted = 0 if args.dry_run else apply_prune(conn, plans)
    conn.close()
    if args.json_output:
        print(json.dumps({"dry_run": args.dry_run, "plans": plans, "deleted": deleted}, indent=2))
    elif not args.quiet:
        for p in plans:
            print(f"would delete {p['rows']} rows from {p['table']}")
        print(f"deleted: {deleted}" + (" (dry-run; pass --apply)" if args.dry_run else ""))
    return 0


def _summary_line(summary) -> str:  # type: ignore[no-untyped-def]
    return (
        f"{summary.run_id}: source checks: {summary.sources_succeeded} succeeded,"
        f" {summary.sources_failed} failed, {summary.sources_attempted} attempted;"
        f" source records: {summary.records_seen}; unverified leads:"
        f" {summary.opportunities_new} new, {summary.opportunities_changed} changed,"
        f" {summary.opportunities_closed} closed, {summary.review_queue_count} in review queue"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opdisc",
        description="Deterministic public opportunity-discovery engine.",
    )
    parser.add_argument("--version", action="version", version=f"opdisc {__version__}")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress normal output")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="machine-readable JSON output"
    )
    parser.add_argument("--config", help="path to engine TOML config")

    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, fn, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=fn)
        return p

    add("init", cmd_init, "initialize/migrate local storage and sync the registry")
    p = add("init-workspace", cmd_init_workspace, "initialize an external private workspace")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("--engine-path", help="path to the public engine checkout")
    p = add("workspace-profile", cmd_workspace_screening, "import an AI-normalized private screening profile")
    p.add_argument("workspace")
    p.add_argument("profile", help="private JSON matching workspace-screening-profile.schema.json")
    for name, help_text in (
        ("workspace-screen", "screen the entire collection without AI calls"),
        ("workspace-screening", "read a bounded personal screening/research batch"),
        ("workspace-apply-screening", "import a semantic screening pass, separate from research"),
    ):
        p = add(name, cmd_workspace_screening, help_text)
        p.add_argument("workspace")
        p.add_argument("--manifest")
        if name == "workspace-apply-screening":
            p.add_argument("response")
        if name == "workspace-screening":
            p.add_argument(
                "--compact", action="store_true", help="share the profile once in a focused AI evidence batch"
            )
            p.add_argument(
                "--audit-sample",
                action="store_true",
                help="read a reproducible stratified sample of selected, deferred and excluded leads",
            )
            p.add_argument(
                "--review-action",
                choices=REVIEW_ACTIONS,
                help="read a specific next-action lane, including deferred follow-up",
            )
            p.add_argument(
                "--include-deferred",
                action="store_true",
                help="read the broader feed, including unchanged checks and deferred questions",
            )
            p.add_argument("--state", choices=("all", *STATES))
            p.add_argument("--lane", choices=LANES)
            p.add_argument("--search")
            p.add_argument("--uncapped", action="store_true")
            p.add_argument("--offset", type=int, default=0)
            p.add_argument("--limit", type=int, default=25)
    p = add(
        "workspace-apply-review",
        cmd_workspace_apply_review,
        "apply validated agent review to an external private workspace",
    )
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("response", help="workspace-review JSON")
    p.add_argument("--manifest", help="export_manifest.json (defaults to configured output)")
    p = add(
        "workspace-apply-feedback",
        cmd_workspace_apply_feedback,
        "apply explicit reasoned Done/Delete feedback to private workspace state",
    )
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("feedback", help="workspace-feedback JSON")
    p = add("workspace-board", cmd_workspace_board, "read a filtered private board page")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("--view", choices=BOARD_VIEWS, default="active")
    p.add_argument("--board-state")
    p.add_argument("--user-status")
    p.add_argument("--pipeline-state")
    p.add_argument("--availability")
    p.add_argument("--search")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=50)
    for action in ("done", "delete", "restore", "purge", "resume"):
        p = add(f"workspace-{action}", cmd_workspace_action, f"{action} a private board record")
        p.set_defaults(board_action=action)
        p.add_argument("workspace", help="private workspace root")
        p.add_argument("opportunity_id", help="stable opportunity ID")
        if action in {"done", "delete"}:
            p.add_argument("--reason-code")
            p.add_argument("--reason-text")
            p.add_argument("--prefer", action="append", default=[], metavar="SIGNAL")
            p.add_argument("--avoid", action="append", default=[], metavar="SIGNAL")
    p = add("workspace-pipeline", cmd_workspace_action, "set a private application pipeline state")
    p.set_defaults(board_action="pipeline")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("opportunity_id", help="stable opportunity ID")
    p.add_argument("pipeline_state", choices=sorted(PIPELINE_STATES))
    p = add("workspace-wait", cmd_workspace_action, "mark a private board record as waiting")
    p.set_defaults(board_action="wait")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("opportunity_id", help="stable opportunity ID")
    p.add_argument("--reason", required=True)
    p.add_argument("--until", help="optional ISO date")
    p = add("workspace-history", cmd_workspace_history, "read private board and operation history")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("--opportunity-id")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=50)
    p = add("workspace-dashboard", cmd_workspace_dashboard, "open curated Home and full-queue Explore")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("--port", type=int, default=8765, help="localhost port (default: 8765)")
    p.add_argument(
        "--manifest", help="current public export manifest (default: engine/output/export_manifest.json)"
    )
    p = add("workspace-request", cmd_workspace_request, "create a manual application handoff")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("opportunity_id", help="stable opportunity ID")
    p.add_argument("artifact_type", choices=ARTIFACT_TYPES)
    p.add_argument("request_text", help="what the chosen agent should prepare")
    p.add_argument(
        "--reference", action="append", default=[], metavar="PATH", help="sources/ or knowledge/ path"
    )
    p = add("knowledge-snapshots", cmd_knowledge_snapshots, "list private knowledge snapshots")
    p.add_argument("workspace", help="private workspace root")
    p = add("compare-knowledge", cmd_compare_knowledge, "compare current knowledge with a snapshot")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("snapshot_id")
    p = add("restore-knowledge", cmd_restore_knowledge, "restore a private knowledge snapshot")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("snapshot_id")
    p = add("backup-workspace", cmd_backup_workspace, "create an unencrypted private workspace ZIP")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("output", help="backup ZIP destination")
    p.add_argument("--kind", choices=("full", "state"), default="full")
    p = add("restore-workspace", cmd_restore_workspace, "restore a verified private workspace ZIP")
    p.add_argument("workspace", help="private workspace root")
    p.add_argument("archive", help="backup ZIP to restore")
    p.add_argument("--pre-restore-output", help="path for the automatic full pre-restore backup")
    p = add("workspace-audit", cmd_audit_workspace, "audit private workspace exposure and references")
    p.add_argument("workspace", help="private workspace root")
    add("validate-config", cmd_validate_config, "validate configuration and registry files")
    p = add("validate-sources", cmd_validate_sources, "live-probe enabled sources and record health")
    p.add_argument("--source-id", help="validate a single source")
    p.add_argument("--concurrency", type=int, default=6)
    p = add("collect", cmd_collect, "fetch due sources once (no export)")
    p.add_argument("--force", action="store_true", help="ignore cadence windows")
    p = add("run", cmd_run, "full workflow: collect, reconcile, score, export, summarize")
    p.add_argument("--force", action="store_true", help="ignore cadence windows")
    add("export", cmd_export, "write export artifacts atomically")
    p = add("import-review", cmd_import_review, "validate a source-backed review response")
    p.add_argument("response", help="path to provider-neutral review-response JSON")
    add("source-health", cmd_source_health, "show per-source health states")
    add("status", cmd_status, "concise engine status")
    p = add("audit", cmd_audit, "repository publication safety audit")
    p.add_argument("repo_root", nargs="?", default=None)
    p = add("add-source", cmd_add_source, "append a source entry to the registry")
    p.add_argument("source_id")
    p.add_argument("--display-name")
    p.add_argument("--organization", required=True)
    p.add_argument("--adapter", required=True)
    p.add_argument("--endpoint-json", help='endpoint_config JSON, e.g. {"board":"acme"}')
    p.add_argument("--landing-url")
    p.add_argument("--category", help="comma-separated categories")
    p.add_argument("--official", action="store_true")
    p = add("prune", cmd_prune, "prune caches/logs (dry-run by default)")
    p.add_argument("--apply", dest="dry_run", action="store_false", default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "quiet", False))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
