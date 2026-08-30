"""Adapter package: import side registers all built-in adapters."""

from __future__ import annotations

# Importing these modules performs @register_adapter registration.
from . import (
    ashby,  # noqa: F401,E402
    csvfeed,  # noqa: F401,E402
    githublist,  # noqa: F401,E402
    greenhouse,  # noqa: F401,E402
    htmllist,  # noqa: F401,E402
    jsonfeed,  # noqa: F401,E402
    lever,  # noqa: F401,E402
    rss,  # noqa: F401,E402
    sitemap,  # noqa: F401,E402
    smartrecruiters,  # noqa: F401,E402
    workday,  # noqa: F401,E402
)
from .base import (  # noqa: F401
    REGISTRY,
    AdapterResult,
    FetchContext,
    bounded_excerpt,
    get_adapter,
    outcome_to_result,
    register_adapter,
    run_source,
)

ADAPTER_NAMES = sorted(REGISTRY.keys())
