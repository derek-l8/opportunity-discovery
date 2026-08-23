"""Bounded, polite HTTP fetching with retries, conditional requests, and caching."""
from __future__ import annotations

import logging
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from . import USER_AGENT
from .config import EngineConfig
from .constants import HEALTH_RATE_LIMITED
from .db import connect  # noqa: F401  (re-export convenience)

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class FetchOutcome:
    url: str
    status: int | None = None
    body: bytes | None = None
    text: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    from_cache: bool = False
    error: str | None = None
    state: str = "ok"
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and self.status < 400


class _DomainThrottle:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        if self.min_interval <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                prev = self._last.get(domain, 0.0)
                delta = now - prev
                if delta >= self.min_interval:
                    self._last[domain] = now
                    return
                sleep_for = self.min_interval - delta
            time.sleep(sleep_for)


class Fetcher:
    """Synchronous polite fetcher; supports file:// for tests/synthetic runs."""

    def __init__(self, cfg: EngineConfig, conn: sqlite3.Connection | None = None) -> None:
        import sqlite3 as _sq

        self.cfg = cfg
        self.conn: _sq.Connection = conn or _sq.connect(":memory:", check_same_thread=False)
        if conn is None:
            from .db import migrate

            migrate(self.conn)  # ensure raw_cache exists for standalone fetchers
        self.conn.row_factory = _sq.Row
        self.client = httpx.Client(
            timeout=cfg.fetch.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        )
        self.throttle = _DomainThrottle(cfg.fetch.per_domain_min_interval_seconds)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def close(self) -> None:
        self.client.close()

    def fetch(self, url: str, *, extra_headers: dict[str, str] | None = None,
              use_cache_fallback: bool = True) -> FetchOutcome:
        start_ms = time.monotonic_ns() // 1_000_000
        if url.startswith("file://"):
            return self._fetch_file(url, start_ms)
        parts = urlsplit(url)
        domain = parts.hostname or ""

        robots_applies = self.cfg.fetch.respect_robots and parts.scheme in ("http", "https")
        if robots_applies and not self._robots_allows(url):
                return FetchOutcome(url=url, state="robots-blocked", error="disallowed by robots.txt",
                                    duration_ms=time.monotonic_ns() // 1_000_000 - start_ms)

        cond_headers = self._conditional_headers(url)
        headers = dict(extra_headers or {})
        headers.update(cond_headers)

        attempt = 0
        backoff = self.cfg.fetch.backoff_base_seconds
        while True:
            attempt += 1
            self.throttle.wait(domain)
            resp = None
            try:
                resp = self.client.get(url, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                status = None
            else:
                status = resp.status_code
                if status == 304:
                    return self._serve_304(url, resp, start_ms)
                if status < 400:
                    self._store_cache(url, resp)
                    return FetchOutcome(
                        url=url,
                        status=status,
                        body=resp.content,
                        text=resp.text,
                        content_type=resp.headers.get("content-type"),
                        etag=resp.headers.get("etag"),
                        last_modified=resp.headers.get("last-modified"),
                        state="ok",
                        duration_ms=time.monotonic_ns() // 1_000_000 - start_ms,
                    )
                error = f"HTTP {status}"

            retryable = status is None or status in RETRYABLE_STATUS
            if retryable and attempt <= self.cfg.fetch.max_retries:
                delay = self._retry_delay(status, backoff, resp)
                log.debug("retry %d for %s in %.1fs (%s)", attempt, url, delay, error)
                time.sleep(delay)
                backoff = min(backoff * 2, self.cfg.fetch.backoff_max_seconds)
                continue

            # final failure -> try cache fallback (preserve prior success)
            if use_cache_fallback:
                cached = self._load_cache(url)
                if cached is not None:
                    out = FetchOutcome(
                        url=url, status=cached["status"], body=cached["body"],
                        text=(cached["body"] or b"").decode("utf-8", "replace"),
                        content_type=cached["content_type"], etag=cached["etag"],
                        last_modified=cached["last_modified"], from_cache=True,
                        state="degraded", error=f"{error}; served from cache",
                        duration_ms=time.monotonic_ns() // 1_000_000 - start_ms,
                    )
                    return out
            out_state = HEALTH_RATE_LIMITED if status == 429 else "failed"
            return FetchOutcome(url=url, status=status, error=error, state=out_state,
                                duration_ms=time.monotonic_ns() // 1_000_000 - start_ms)

    def fetch_many(self, urls: list[str], worker: int | None = None) -> list[FetchOutcome]:
        max_workers = min(worker or self.cfg.fetch.max_concurrency, len(urls) or 1)
        results: dict[str, FetchOutcome] = {}
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = {pool.submit(self.fetch, u): u for u in urls}
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    results[url] = fut.result()
                except Exception as exc:  # isolation: one failure must not abort the batch
                    log.warning("unexpected fetch failure for %s: %s", url, exc)
                    results[url] = FetchOutcome(url=url, error=str(exc), state="failed")
        return [results[u] for u in urls]

    # ----------------------------------------------------------------- helpers
    def _fetch_file(self, url: str, start_ms: int) -> FetchOutcome:
        path = Path(url.removeprefix("file://"))
        try:
            data = path.read_bytes()
        except OSError as exc:
            return FetchOutcome(url=url, error=str(exc), state="failed",
                                duration_ms=time.monotonic_ns() // 1_000_000 - start_ms)
        suffix = path.suffix.lower().lstrip(".")
        ctype = {
            "json": "application/json", "csv": "text/csv", "xml": "application/xml",
            "html": "text/html", "md": "text/markdown", "txt": "text/plain",
        }.get(suffix, "application/octet-stream")
        return FetchOutcome(url=url, status=200, body=data,
                            text=data.decode("utf-8", "replace"), content_type=ctype,
                            state="ok", duration_ms=time.monotonic_ns() // 1_000_000 - start_ms)

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            rp = self._robots.get(origin)
        if rp is None:
            rp = RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            try:
                resp = self.client.get(robots_url, headers={"User-Agent": USER_AGENT})
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.allow_all = True  # type: ignore[attr-defined]
            except httpx.HTTPError:
                rp.allow_all = True  # type: ignore[attr-defined]
            with self._robots_lock:
                self._robots[origin] = rp
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def _conditional_headers(self, url: str) -> dict[str, str]:
        row = self.conn.execute(
            "SELECT etag, last_modified FROM raw_cache WHERE url = ?", (url,)
        ).fetchone()
        headers: dict[str, str] = {}
        if row:
            if row["etag"]:
                headers["If-None-Match"] = row["etag"]
            if row["last_modified"]:
                headers["If-Modified-Since"] = row["last_modified"]
        return headers

    def _serve_304(self, url: str, resp: httpx.Response, start_ms: int) -> FetchOutcome:
        row = self.conn.execute(
            "SELECT status, content_type, content, etag, last_modified FROM raw_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row and row["content"] is not None:
            body = bytes(row["content"])
        else:
            body = b""
        return FetchOutcome(
            url=url, status=304, body=body,
            text=body.decode("utf-8", "replace") if body else None,
            content_type=row["content_type"] if row else None,
            etag=resp.headers.get("etag") or (row["etag"] if row else None),
            last_modified=resp.headers.get("last-modified") or (row["last_modified"] if row else None),
            not_modified=True, state="not-modified",
            duration_ms=time.monotonic_ns() // 1_000_000 - start_ms,
        )

    def _store_cache(self, url: str, resp: httpx.Response) -> None:
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        expires = now + timedelta(days=self.cfg.fetch.cache_days)
        self.conn.execute(
            """
            INSERT INTO raw_cache (url, fetched_at, status, content_type, content,
                                   content_hash, etag, last_modified, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                fetched_at=excluded.fetched_at, status=excluded.status,
                content_type=excluded.content_type, content=excluded.content,
                content_hash=excluded.content_hash, etag=excluded.etag,
                last_modified=excluded.last_modified, expires_at=excluded.expires_at
            """,
            (
                url, now.isoformat(), resp.status_code,
                resp.headers.get("content-type"), resp.content,
                None, resp.headers.get("etag"), resp.headers.get("last-modified"),
                expires.isoformat(),
            ),
        )
        self.conn.commit()

    def _load_cache(self, url: str) -> dict | None:
        row = self.conn.execute(
            "SELECT status, content_type, content, etag, last_modified FROM raw_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row and row["content"] is not None:
            return {
                "status": row["status"], "body": bytes(row["content"]),
                "content_type": row["content_type"], "etag": row["etag"],
                "last_modified": row["last_modified"],
            }
        return None

    @staticmethod
    def _retry_delay(status: int | None, base_backoff: float,
                     resp: httpx.Response | None = None) -> float:
        jitter = random.uniform(0, 0.5 * base_backoff)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), 0.0)
                except ValueError:
                    pass
        return base_backoff + jitter
