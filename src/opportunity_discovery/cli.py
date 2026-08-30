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
from .runner import ensure_ready, run_full_workflow
from .validate_sources import validate_all


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
            f"scanned {report.files_scanned} tracked files;"
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
    add("validate-config", cmd_validate_config, "validate configuration and registry files")
    p = add("validate-sources", cmd_validate_sources, "live-probe enabled sources and record health")
    p.add_argument("--source-id", help="validate a single source")
    p.add_argument("--concurrency", type=int, default=6)
    p = add("collect", cmd_collect, "fetch due sources once (no export)")
    p.add_argument("--force", action="store_true", help="ignore cadence windows")
    p = add("run", cmd_run, "full workflow: collect, reconcile, score, export, summarize")
    p.add_argument("--force", action="store_true", help="ignore cadence windows")
    add("export", cmd_export, "write export artifacts atomically")
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
