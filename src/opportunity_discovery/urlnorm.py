"""URL normalization, tracking-parameter stripping, and ATS pattern detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Common tracking parameters that never determine a requisition.
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "srsltid",
    "yclid",
    "igshid",
    "si",
    "spm",
    "scid",
    "gh_src",
    "gh_jid",
}

# Parameters known to carry the actual requisition and must be preserved even if
# they collide with generic names above (checked case-insensitively).
PRESERVE_PARAMS = {"jobid", "job_id", "req", "reqid", "requisition_id", "id", "gh_jid", "ashby_jid"}

_SCHEME_FIXES = {"http": "https"}


@dataclass(frozen=True)
class ATSPattern:
    provider: str  # greenhouse | lever | ashby | smartrecruiters | workday
    org: str
    board_or_site: str | None = None
    req_id: str | None = None


def normalize_url(url: str) -> str:
    """Normalize an application URL without destroying requisition semantics.

    - upgrades http -> https for well-known hosts
    - lowercases host, removes default port
    - drops fragment
    - strips common tracking parameters (preserving requisition params)
    - sorts query params for stability
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = _SCHEME_FIXES.get(parts.scheme.lower(), parts.scheme.lower() or "https")
    host = (parts.hostname or "").lower()
    if not host:
        return url.strip()
    port = parts.port
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    if parts.username:
        netloc = f"{parts.username}@{netloc}"

    query_pairs = []
    seen_keys: dict[str, int] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lk = key.lower()
        seen_keys[lk] = seen_keys.get(lk, 0) + 1
        if lk in TRACKING_PARAMS and lk not in PRESERVE_PARAMS:
            continue
        query_pairs.append((key, value))
    query_pairs.sort()
    query = urlencode(query_pairs)
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


_GREENHOUSE_RE = re.compile(
    r"https?://(?:job-)?boards\.greenhouse\.io/(?P<org>[^/?#]+)"
    r"(?:/jobs/(?P<req>\w+))?",
    re.IGNORECASE,
)
_LEVER_RE = re.compile(r"https?://jobs\.(?:eu\.)?lever\.co/(?P<org>[\w-]+)(?:/(?P<req>\w+))?", re.IGNORECASE)
_ASHBY_RE = re.compile(r"https?://jobs\.ashbyhq\.com/(?P<org>[\w.-]+)(?:/(?P<req>[\w-]+))?", re.IGNORECASE)
_SMART_RE = re.compile(
    r"https?://(?:careers|jobs|www)\.smartrecruiters\.com/(?P<org>[\w-]+)"
    r"(?:/(?P<req>[\w-]+))?",
    re.IGNORECASE,
)
_WORKDAY_RE = re.compile(
    r"https?://(?P<tenant>[^.]+)\.(?P<host>wd\d+\.myworkdayjobs\.com)"
    r"/(?P<site>[^/?#]+)",
    re.IGNORECASE,
)


def detect_ats(url: str) -> ATSPattern | None:
    """Detect ATS provider/org from an official application URL."""
    if not url:
        return None
    m = _GREENHOUSE_RE.search(url)
    if m:
        org = m.group("org")
        org = "embed" if org.lower() == "embed" else org
        return ATSPattern("greenhouse", org, req_id=m.group("req"))
    m = _LEVER_RE.search(url)
    if m:
        return ATSPattern("lever", m.group("org"), req_id=m.group("req"))
    m = _ASHBY_RE.search(url)
    if m:
        return ATSPattern("ashby", m.group("org"), req_id=m.group("req"))
    m = _SMART_RE.search(url)
    if m:
        return ATSPattern("smartrecruiters", m.group("org"), req_id=m.group("req"))
    m = _WORKDAY_RE.search(url)
    if m:
        return ATSPattern("workday", m.group("tenant"), board_or_site=m.group("site"))
    return None


def humanize_slug(slug: str) -> str:
    """Humanize a URL slug for display; always flagged inferred upstream."""
    text = re.sub(r"[-_]+", " ", slug).strip()
    return re.sub(r"\s+", " ", text).title()
