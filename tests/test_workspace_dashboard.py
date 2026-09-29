"""Phase 7 browser flow over the existing synthetic private board."""

import json
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest

from opportunity_discovery.workspace_board import list_workspace_board
from opportunity_discovery.workspace_dashboard import _DashboardServer, render_dashboard
from opportunity_discovery.workspace_state import apply_workspace_review
from tests.test_workspace_discovery import add_review_queue
from tests.test_workspace_state import make_generation, make_workspace, materialize_review

SCENARIO = json.loads(
    (Path(__file__).parent / "fixtures" / "demo" / "phase6-board-scenario.json").read_text(encoding="utf-8")
)
PROMOTED_ID = SCENARIO["opportunity_ids"]["promoted"]
RESEARCH_ID = SCENARIO["opportunity_ids"]["research"]


@contextmanager
def dashboard(root, manifest=None):
    with _DashboardServer(root, 0, manifest) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join(timeout=3)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def post(url, form, *, origin=None):
    body = urlencode(form).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        headers["Origin"] = origin
    request = Request(url + "/action", data=body, headers=headers, method="POST")
    try:
        return build_opener(NoRedirect()).open(request)
    except HTTPError as exc:
        if exc.code == 303:
            return exc
        raise


def test_dashboard_renders_real_board_and_escapes_untrusted_content(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    page = render_dashboard(root, "test-token", {"view": "active", "search": "Firmware", "item": PROMOTED_ID})
    assert "Embedded Firmware Intern" in page
    assert "Official page checked" in page
    assert "https://synthetic.example/official/intern-open" in page
    assert "synthetic-demo" in page
    assert "No verified official link recorded" not in page
    assert "Forget Completely" in page
    assert "Type FORGET to confirm" in page
    assert "Unknown" in page
    assert 'aria-label="Discovery views"' in page
    assert 'name="reason_code"' in page

    board_path = root / ".opdisc" / "board.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["opportunities"][PROMOTED_ID]["collector_snapshot"]["title"] = '<script>alert("x")</script>'
    board_path.write_text(json.dumps(board), encoding="utf-8")
    escaped = render_dashboard(root, "test-token", {"view": "active", "item": PROMOTED_ID})
    assert "&lt;script&gt;" in escaped
    assert '<script>alert("x")</script>' not in escaped


def test_dashboard_http_action_flow_and_request_guards(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    with dashboard(root) as (server, url):
        assert server.server_address[0] == "127.0.0.1"
        get = build_opener(NoRedirect())
        active = get.open(url + "/?view=active&search=Firmware").read().decode()
        assert PROMOTED_ID in active
        assert "Official page checked" in active
        assert RESEARCH_ID not in active
        token = server.form_token
        with pytest.raises(HTTPError) as error:
            post(url, {"item": PROMOTED_ID, "action": "done", "view": "active", "token": "bad"})
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            post(
                url,
                {"item": PROMOTED_ID, "action": "done", "view": "active", "token": token},
                origin="https://attacker.example",
            )
        assert error.value.code == 403
        assert (
            post(
                url,
                {
                    "item": PROMOTED_ID,
                    "action": "done",
                    "view": "active",
                    "token": token,
                    "reason_code": SCENARIO["dashboard_example"]["done_reason_code"],
                },
            ).status
            == 303
        )
        assert list_workspace_board(root, view="history", user_status="done")["total"] == 1
        assert (
            post(url, {"item": PROMOTED_ID, "action": "restore", "view": "history", "token": token}).status
            == 303
        )
        assert (
            post(
                url,
                {
                    "item": PROMOTED_ID,
                    "action": "pipeline",
                    "view": "active",
                    "token": token,
                    "pipeline_state": "preparing",
                },
            ).status
            == 303
        )
        assert (
            post(
                url,
                {
                    "item": PROMOTED_ID,
                    "action": "wait",
                    "view": "active",
                    "token": token,
                    "wait_reason": "Synthetic cycle",
                },
            ).status
            == 303
        )
        assert list_workspace_board(root, view="waiting")["total"] == 1
        assert (
            post(url, {"item": PROMOTED_ID, "action": "resume", "view": "waiting", "token": token}).status
            == 303
        )
        assert (
            post(
                url,
                {
                    "item": RESEARCH_ID,
                    "action": "delete",
                    "view": "active",
                    "token": token,
                    "reason_text": SCENARIO["dashboard_example"]["delete_reason_text"],
                },
            ).status
            == 303
        )
        assert list_workspace_board(root, view="dismissed", user_status="delete")["total"] == 1
        with pytest.raises(HTTPError) as error:
            post(
                url,
                {
                    "item": RESEARCH_ID,
                    "action": "purge",
                    "view": "dismissed",
                    "token": token,
                    "confirm": "wrong",
                },
            )
        assert error.value.code == 400
        assert list_workspace_board(root, view="dismissed", user_status="delete")["total"] == 1
        assert (
            post(
                url,
                {
                    "item": RESEARCH_ID,
                    "action": "purge",
                    "view": "dismissed",
                    "token": token,
                    "confirm": SCENARIO["dashboard_example"]["forget_confirmation"],
                },
            ).status
            == 303
        )
        assert list_workspace_board(root, view="all")["total"] == 3
        assert "Recent activity" in get.open(url + "/?view=history").read().decode()


def test_dashboard_http_explore_reads_full_queue_without_creating_board_records(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    add_review_queue(manifest)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    untouched = "opp_3cf744c778c9ceccceb50d064383d337"
    with dashboard(root, manifest) as (_server, url):
        page = (
            build_opener(NoRedirect())
            .open(url + "/?view=explore&review_status=unreviewed&search=Embedded+Firmware+Internship")
            .read()
            .decode()
        )
        assert untouched in page
        assert "reviews imported: 4; no review imported: 1" in page
        assert "Forget Completely" not in page  # Explore is read-only for public leads.
    assert list_workspace_board(root, view="all")["total"] == 4
