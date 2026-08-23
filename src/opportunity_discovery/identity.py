"""Stable candidate identity.

Priority of identity evidence (strongest first):
1. Official ATS/provider requisition ID  ->  prov:{provider}:{req_id}
2. Stable official application URL       ->  url:{normalized_url}
3. Org + explicit requisition ID         ->  orgreq:{org}:{req_id}
4. Conservative normalized composite     ->  comp:{org}|{normalized_title}|{location}

Identity is never computed from fuzzy title similarity; two records with
different identity keys are never merged on that basis alone.
"""
from __future__ import annotations

import hashlib

from .urlnorm import normalize_url


def _hash(key: str) -> str:
    return "opp_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def identity_key(
    *,
    provider: str | None = None,
    provider_req_id: str | None = None,
    organization: str | None = None,
    title: str | None = None,
    canonical_url: str | None = None,
    location_text: str | None = None,
) -> tuple[str, str]:
    """Return (opportunity_id, identity_basis_description)."""
    if provider and provider_req_id:
        key = f"prov:{provider.lower()}:{str(provider_req_id).lower()}"
        return _hash(key), f"provider-req {key}"
    if canonical_url:
        norm = normalize_url(canonical_url)
        if norm:
            return _hash(f"url:{norm}"), f"url {norm}"
    if organization and provider_req_id:
        org = organization.strip().lower()
        key = f"orgreq:{org}:{str(provider_req_id).lower()}"
        return _hash(key), f"org+req {key}"
    # Conservative composite: exact normalized fields only, no similarity.
    org = (organization or "").strip().lower()
    ttl = " ".join((title or "").strip().lower().split())
    loc = (location_text or "").strip().lower()
    key = f"comp:{org}|{ttl}|{loc}"
    return _hash(key), f"composite {key}"


def description_hash(text: str | None) -> str | None:
    if not text:
        return None
    normalized = " ".join(text.split()).lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]
