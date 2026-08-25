import json

import httpx

from opportunity_discovery.http_client import Fetcher
from tests.helpers import make_db


def make_fetcher(engine_config, handler):
    conn = make_db(engine_config.paths.base_dir)
    fetcher = Fetcher(engine_config, conn=conn)
    fetcher.client = httpx.Client(
        transport=httpx.MockTransport(handler),
        timeout=engine_config.fetch.timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "opportunity-discovery/test"},
    )
    return fetcher, conn


def test_conditional_request_uses_etag(engine_config):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"payload", headers={"ETag": '"v1"'})

    fetcher, conn = make_fetcher(engine_config, handler)
    try:
        out1 = fetcher.fetch("https://api.example.com/feed.json")
        assert out1.status == 200 and out1.body == b"payload"
        out2 = fetcher.fetch("https://api.example.com/feed.json")
        assert out2.not_modified
        assert out2.body == b"payload"  # served from stored cache
        assert calls["n"] == 2
    finally:
        fetcher.close()
        conn.close()


def test_retries_transient_then_succeeds(engine_config):
    engine_config.fetch.max_retries = 3
    engine_config.fetch.backoff_base_seconds = 0.0
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, content=b'{"ok": true}')

    fetcher, conn = make_fetcher(engine_config, handler)
    try:
        out = fetcher.fetch("https://flaky.example.com/x")
        assert out.ok and calls["n"] == 2
    finally:
        fetcher.close()
        conn.close()


def test_rate_limited_state_not_empty_success(engine_config):
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "60"}, content=b"slow down")

    engine_config.fetch.max_retries = 0
    fetcher, conn = make_fetcher(engine_config, handler)
    try:
        out = fetcher.fetch("https://busy.example.com/x")
        assert not out.ok
        assert out.state == "rate-limited"
    finally:
        fetcher.close()
        conn.close()


def test_cache_fallback_on_failure(engine_config):
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            raise httpx.ConnectError("network down")
        return httpx.Response(200, content=b"cached-body", headers={"ETag": '"e1"'})

    fetcher, conn = make_fetcher(engine_config, handler)
    try:
        first = fetcher.fetch("https://cacheable.example.com/data")
        assert first.status == 200
        state["fail"] = True
        second = fetcher.fetch("https://cacheable.example.com/data")
        assert second.from_cache
        assert second.text == "cached-body"
        assert second.state == "degraded"
    finally:
        fetcher.close()
        conn.close()


def test_fetch_many_isolates_failures(engine_config):
    def handler(request):
        if "bad" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=b"x")

    fetcher, conn = make_fetcher(engine_config, handler)
    try:
        results = fetcher.fetch_many([
            "https://good.example.com/a", "https://bad.example.com/b",
            "https://good.example.com/c",
        ])
        assert len(results) == 3
        by_url = {r.url: r for r in results}
        assert by_url["https://good.example.com/a"].ok
        assert not by_url["https://bad.example.com/b"].ok
        assert by_url["https://bad.example.com/b"].error
    finally:
        fetcher.close()
        conn.close()


def test_file_scheme_fetch(engine_config, tmp_path):
    p = tmp_path / "local.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    fetcher, conn = make_fetcher(engine_config, lambda req: httpx.Response(500))
    try:
        out = fetcher.fetch(p.as_uri())
        assert out.status == 200
        assert json.loads(out.text)["a"] == 1
    finally:
        fetcher.close()
        conn.close()


def test_file_scheme_fetch_percent_encoded_name(engine_config, tmp_path):
    p = tmp_path / "with space.json"
    p.write_text('{"b": 2}', encoding="utf-8")
    assert "%20" in p.as_uri()
    fetcher, conn = make_fetcher(engine_config, lambda req: httpx.Response(500))
    try:
        out = fetcher.fetch(p.as_uri())
        assert out.status == 200
        assert json.loads(out.text)["b"] == 2
    finally:
        fetcher.close()
        conn.close()


def test_file_scheme_fetch_localhost_authority(engine_config, tmp_path):
    p = tmp_path / "localhost.json"
    p.write_text('{"c": 3}', encoding="utf-8")
    uri = "file://localhost" + p.as_uri()[len("file://"):]
    fetcher, conn = make_fetcher(engine_config, lambda req: httpx.Response(500))
    try:
        out = fetcher.fetch(uri)
        assert out.status == 200
        assert json.loads(out.text)["c"] == 3
    finally:
        fetcher.close()
        conn.close()


def test_file_scheme_fetch_rejects_remote_authority(engine_config):
    fetcher, conn = make_fetcher(engine_config, lambda req: httpx.Response(500))
    try:
        out = fetcher.fetch("file://remote.example.com/data/feed.json")
        assert not out.ok
        assert out.status is None
        assert out.state == "failed"
        assert "authority" in (out.error or "")
    finally:
        fetcher.close()
        conn.close()


def test_file_scheme_fetch_missing_file_is_failed_outcome(engine_config, tmp_path):
    uri = (tmp_path / "missing.json").as_uri()
    fetcher, conn = make_fetcher(engine_config, lambda req: httpx.Response(500))
    try:
        out = fetcher.fetch(uri)
        assert not out.ok
        assert out.status is None
        assert out.error
    finally:
        fetcher.close()
        conn.close()
