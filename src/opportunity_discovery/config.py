"""Configuration loading and validation (config/default.toml, overridable)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAME = "default.toml"


@dataclass
class PathsConfig:
    base_dir: Path
    data_dir: Path
    output_dir: Path
    logs_dir: Path

    @staticmethod
    def resolve(base_dir: Path, overrides: dict[str, str]) -> PathsConfig:
        def _p(key: str, default: str) -> Path:
            raw = overrides.get(key, default)
            path = Path(raw)
            return path if path.is_absolute() else base_dir / path

        return PathsConfig(
            base_dir=base_dir,
            data_dir=_p("data_dir", "data"),
            output_dir=_p("output_dir", "output"),
            logs_dir=_p("logs_dir", "logs"),
        )


@dataclass
class FetchConfig:
    max_concurrency: int = 6
    per_domain_min_interval_seconds: float = 1.5
    timeout_seconds: float = 20.0
    max_retries: int = 3
    backoff_base_seconds: float = 1.5
    backoff_max_seconds: float = 30.0
    respect_robots: bool = True
    cache_days: int = 30


@dataclass
class SeasonConfig:
    target_season: str = "summer-2027"
    season_aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class ScoringConfig:
    review_queue_threshold: float = 0.5
    families: dict[str, dict[str, Any]] = field(default_factory=dict)
    bonus_paid: float = 2.0
    bonus_funded: float = 2.0
    bonus_deadline_known: float = 0.25
    bonus_remote: float = 0.25
    penalty_unfunded_distant_event: float = 1.5
    coop_suppress: bool = True
    online_hackathon_suppress: bool = True
    unpaid_retention_score_floor: float = 1.5


@dataclass
class ChangeDetectionConfig:
    closed_after_consecutive_successes: int = 3
    material_fields: list[str] = field(
        default_factory=lambda: [
            "title",
            "canonical_url",
            "location_text",
            "remote_signal",
            "deadline",
            "compensation_text",
            "employment_type",
            "season",
            "description_hash",
        ]
    )


@dataclass
class ExportConfig:
    schema_version: str = "1.0"
    packet_char_limit: int = 120_000
    excerpt_chars: int = 600


@dataclass
class EngineConfig:
    paths: PathsConfig
    fetch: FetchConfig
    season: SeasonConfig
    scoring: ScoringConfig
    changes: ChangeDetectionConfig
    export: ExportConfig
    sources_file: Path
    config_path: Path
    log_level: str = "INFO"
    log_retention_days: int = 14
    source_check_retention_days: int = 180


def _apply(dataclass_obj: Any, section: dict[str, Any], known: set[str]) -> list[str]:
    errors: list[str] = []
    for key, value in section.items():
        if key not in known:
            errors.append(f"unknown config key: {key}")
            continue
        setattr(dataclass_obj, key, value)
    return errors


def load_config(
    config_path: Path | None = None,
    base_dir: Path | None = None,
    path_overrides: dict[str, str] | None = None,
) -> tuple[EngineConfig, list[str]]:
    """Load engine configuration. Returns (config, validation_errors)."""
    errors: list[str] = []
    if config_path is None:
        base = base_dir or _find_repo_root(Path.cwd())
        config_path = base / "config" / DEFAULT_CONFIG_NAME
    else:
        config_path = Path(config_path)
        base = base_dir or config_path.parent.parent

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)

    fetch = FetchConfig()
    season = SeasonConfig()
    scoring = ScoringConfig()
    changes = ChangeDetectionConfig()
    export_cfg = ExportConfig()

    errors += _apply(fetch, raw.get("fetch", {}), set(vars(FetchConfig())))
    errors += _apply(season, raw.get("season", {}), {"target_season", "season_aliases"})
    errors += _apply(scoring, raw.get("scoring", {}), set(vars(ScoringConfig())) - {"families"})
    fam_section = raw.get("scoring", {}).get("families", {})
    if isinstance(fam_section, dict):
        scoring.families.update(fam_section)
    else:
        errors.append("scoring.families must be a table")
    errors += _apply(changes, raw.get("change_detection", {}), set(vars(ChangeDetectionConfig())))
    errors += _apply(export_cfg, raw.get("export", {}), set(vars(ExportConfig())))

    paths = PathsConfig.resolve(base, raw.get("paths", {}))

    # basic sanity checks
    if fetch.max_concurrency < 1 or fetch.max_concurrency > 32:
        errors.append("fetch.max_concurrency must be between 1 and 32")
    if fetch.max_retries < 0 or fetch.max_retries > 10:
        errors.append("fetch.max_retries must be between 0 and 10")
    if export_cfg.packet_char_limit < 1000:
        errors.append("export.packet_char_limit must be >= 1000")
    if not season.target_season:
        errors.append("season.target_season must be non-empty")

    sources_file = base / raw.get("sources_file", "config/sources.toml")
    if not sources_file.name.endswith(".toml"):
        errors.append(f"sources_file must be a .toml file: {sources_file}")

    cfg = EngineConfig(
        paths=paths,
        fetch=fetch,
        season=season,
        scoring=scoring,
        changes=changes,
        export=export_cfg,
        sources_file=sources_file,
        config_path=config_path,
        log_level=str(raw.get("log_level", "INFO")),
        log_retention_days=int(raw.get("log_retention_days", 14)),
        source_check_retention_days=int(raw.get("source_check_retention_days", 180)),
    )
    return cfg, errors


def _find_repo_root(start: Path) -> Path:
    """Find repo root by looking for pyproject.toml; fall back to cwd."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return start.resolve()
