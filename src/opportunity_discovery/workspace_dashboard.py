"""Local browser interface over the existing private board read and action model."""

# HTML fragments are kept inline with their controls to make action review easier.
# ruff: noqa: E501

from __future__ import annotations

import html
import secrets
import webbrowser
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from .workspace_actions import (
    change_workspace_opportunity,
    list_workspace_history,
    mark_workspace_opportunity,
)
from .workspace_application import (
    ARTIFACT_TYPES,
    REQUEST_ID,
    create_application_request,
    list_application_requests,
)
from .workspace_board import BOARD_VIEWS, PIPELINE_STATES, list_workspace_board
from .workspace_state import OPPORTUNITY_ID, WorkspaceStateError, require_workspace

_PAGE_SIZE = 25
_MAX_FORM_BYTES = 16_384
_REASON_CODES = ("already-applied", "not-relevant", "timing", "location", "other")


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _display(value: Any) -> str:
    return _e(value) if value not in (None, "", [], {}) else '<span class="unknown">Unknown</span>'


def _safe_link(value: Any, label: str, css: str = "") -> str:
    if not isinstance(value, str):
        return ""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or any(ord(c) < 32 for c in value):
        return ""
    return f'<a class="{_e(css)}" href="{_e(value)}" target="_blank" rel="noopener noreferrer">{_e(label)} <span aria-hidden="true">↗</span></a>'


def _query(**kwargs: str | int | None) -> str:
    return "/?" + urlencode({key: value for key, value in kwargs.items() if value not in (None, "")})


def _field(label: str, value: Any) -> str:
    return f'<div class="fact"><dt>{_e(label)}</dt><dd>{_display(value)}</dd></div>'


def _badge(value: Any, kind: str = "") -> str:
    shown = str(value or "unknown").replace("-", " ")
    return f'<span class="badge {kind}">{_e(shown)}</span>'


def _filter_options(name: str, current: str, options: tuple[str, ...], label: str) -> str:
    choices = ['<option value="">All</option>']
    choices.extend(
        f'<option value="{_e(value)}"{" selected" if value == current else ""}>{_e(value.replace("-", " ").title())}</option>'
        for value in options
    )
    return f'<label class="filter">{_e(label)}<select name="{_e(name)}">{"".join(choices)}</select></label>'


def _card(item: dict[str, Any], *, view: str, selected: str | None, filters: dict[str, str]) -> str:
    identifier = item["opportunity_id"]
    href = _query(view=view, item=identifier, **filters)
    title = item.get("title") or "Untitled opportunity"
    meta = " · ".join(str(value) for value in (item.get("organization"), item.get("exact_deadline")) if value)
    return (
        f'<a class="opportunity-card{" selected" if selected == identifier else ""}" href="{_e(href)}" '
        f'aria-label="View {_e(title)}">'
        f'<span class="card-top"><span class="eyebrow">{_e(item["lane"])} / {_e(item["board_state"] or "unknown")}</span>'
        f'<span class="card-arrow" aria-hidden="true">↗</span></span>'
        f'<strong>{_e(title)}</strong><span class="card-meta">{_e(meta or "Organization unknown")}</span>'
        f'<span class="card-badges">{_badge(item.get("availability"), "availability")}'
        f"{_badge(item.get('pipeline_state'), 'pipeline')}</span></a>"
    )


def _source_rows(provenance: Any) -> str:
    if not isinstance(provenance, list) or not provenance:
        return '<p class="muted">No collector provenance recorded.</p>'
    rows = []
    for source in provenance:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id", "Unidentified source")
        link = _safe_link(source.get("source_url"), "Open source")
        rows.append(f"<li><span>{_e(source_id)}</span>{link}</li>")
    return '<ul class="source-list">' + "".join(rows) + "</ul>"


def _action_form(token: str, identifier: str, action: str, label: str, *, view: str, style: str = "") -> str:
    return (
        f'<form method="post" action="/action" class="inline-action"><input type="hidden" name="token" value="{_e(token)}">'
        f'<input type="hidden" name="item" value="{_e(identifier)}">'
        f'<input type="hidden" name="view" value="{_e(view)}">'
        f'<input type="hidden" name="action" value="{_e(action)}">'
        f'<button class="button {style}" type="submit">{_e(label)}</button></form>'
    )


def _detail(root: Path, item: dict[str, Any], token: str, view: str) -> str:
    identifier = item["opportunity_id"]
    facts = item.get("verified_facts") or {}
    eligibility = item.get("eligibility") or {}
    review = item.get("review") or {}
    waiting = item.get("waiting") or {}
    title = item.get("title") or "Untitled opportunity"
    official_link = _safe_link(
        item.get("official_url"), "Open official application / program page", "official-link"
    )
    if not official_link:
        official_link = '<span class="unknown">No verified official link recorded</span>'
    collected_link = _safe_link(item.get("canonical_url"), "Open collected lead")
    source_kind = (review.get("verification") or {}).get("source_kind")
    evidence = review.get("official_evidence") or {}
    reason_codes = review.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        reason_codes = []
    status = item.get("user_status")
    parts = [
        '<section class="detail" aria-labelledby="detail-title">',
        '<div class="detail-head"><div><span class="eyebrow">Opportunity detail</span>',
        f'<h2 id="detail-title">{_e(title)}</h2><p>{_display(item.get("organization"))}</p></div>',
        f"{_badge(item.get('lane'), 'lane')}</div>",
        f'<p class="identifier">{_e(identifier)}</p>',
        f'<div class="hero-link">{official_link}<p>Verified destination when supplied by review. Check the page again before acting.</p></div>',
        '<div class="section-title"><h3>What is known</h3><span>Unrecorded facts are shown as Unknown</span></div>',
        '<dl class="fact-grid">',
        _field("Availability", item.get("availability")),
        _field("Exact deadline", item.get("exact_deadline")),
        _field("Eligibility conclusion", eligibility.get("conclusion")),
        _field("Board state", item.get("board_state")),
        _field("Pipeline", item.get("pipeline_state")),
        _field("Last updated", item.get("updated_at")),
        "</dl>",
        '<div class="section-title"><h3>Evidence & provenance</h3></div>',
        '<dl class="fact-grid">',
        _field("Official source type", source_kind),
        _field("Official page checked", facts.get("checked_at")),
        _field("Reviewer disposition", review.get("disposition")),
        _field("Collector route", item.get("routing_state")),
        _field("Review completed", review.get("reviewed_at")),
        _field("Eligibility basis", ", ".join(eligibility.get("basis_codes") or [])),
        "</dl>",
        f'<p class="evidence-note"><b>Official evidence note:</b> {_display(evidence.get("notes_excerpt"))}</p>',
        f'<p class="reason-line"><b>Review reasons:</b> {_display(", ".join(map(str, reason_codes)))}</p>',
        f'<p class="lead-link">{collected_link}</p>',
        "<h4>Collected from</h4>",
        _source_rows(item.get("provenance")),
        '<div class="section-title"><h3>Your board</h3></div>',
        '<dl class="fact-grid">',
        _field("Your status", status),
        _field("Waiting reason", waiting.get("reason") if waiting.get("active") else None),
        _field("Waiting until", waiting.get("until") if waiting.get("active") else None),
        _field("Duplicate of", item.get("duplicate_of")),
        "</dl>",
    ]
    if status in {"done", "delete"}:
        parts.append(_action_form(token, identifier, "restore", "Restore to board", view=view))
    else:
        parts.extend(
            [
                '<div class="action-grid">',
                '<form method="post" action="/action" class="decision-form">',
                f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="item" value="{_e(identifier)}">',
                f'<input type="hidden" name="view" value="{_e(view)}">',
                '<label>Reason <span class="optional">optional</span><select name="reason_code">',
                '<option value="">Choose a reason</option>',
                *(
                    f'<option value="{_e(code)}">{_e(code.replace("-", " ").title())}</option>'
                    for code in _REASON_CODES
                ),
                "</select></label>",
                '<label>Additional context <span class="optional">optional</span><input name="reason_text" maxlength="1000" placeholder="What informed your decision?"></label>',
                '<div class="button-row"><button class="button" name="action" value="done">Done</button>',
                '<button class="button secondary" name="action" value="delete">Delete</button></div>',
                '<p class="form-hint">Done removes this from active work. Delete dismisses it while retaining a rediscovery record.</p>',
                "</form>",
                "</div>",
            ]
        )
    parts.extend(
        [
            '<div class="control-row"><form method="post" action="/action">',
            f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="item" value="{_e(identifier)}">',
            f'<input type="hidden" name="view" value="{_e(view)}"><input type="hidden" name="action" value="pipeline">',
            '<label>Pipeline state<select name="pipeline_state">',
            *(
                f'<option value="{_e(state)}"{" selected" if item.get("pipeline_state") == state else ""}>{_e(state.replace("-", " ").title())}</option>'
                for state in sorted(PIPELINE_STATES)
            ),
            '</select></label><button class="button subtle">Update pipeline</button></form>',
        ]
    )
    if waiting.get("active"):
        parts.append(_action_form(token, identifier, "resume", "Resume", view=view, style="subtle"))
    else:
        parts.extend(
            [
                '<form method="post" action="/action">',
                f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="item" value="{_e(identifier)}">',
                f'<input type="hidden" name="view" value="{_e(view)}"><input type="hidden" name="action" value="wait">',
                '<label>Wait reason<input name="wait_reason" required maxlength="500" placeholder="e.g. Next application cycle"></label>',
                '<label>Until <span class="optional">optional</span><input type="date" name="wait_until"></label>',
                '<button class="button subtle">Set waiting</button></form>',
            ]
        )
    parts.extend(
        [
            "</div>",
            '<div class="section-title"><h3>Application preparation</h3></div>',
            '<p class="form-hint">Create a manual request for your chosen agent. This creates a private handoff folder; it does not write a draft or submit anything.</p>',
            '<form method="post" action="/action" class="application-form">',
            f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="item" value="{_e(identifier)}">',
            f'<input type="hidden" name="view" value="{_e(view)}"><input type="hidden" name="action" value="application-request">',
            '<label>Artifact<select name="artifact_type">',
            *(
                f'<option value="{_e(kind)}">{_e(kind.replace("-", " ").title())}</option>'
                for kind in ARTIFACT_TYPES
            ),
            "</select></label>",
            '<label>What should the agent prepare?<textarea name="request_text" rows="4" maxlength="5000" required placeholder="Describe the artifact, target audience, and any constraints."></textarea></label>',
            '<label>Private source or knowledge paths <span class="optional">optional; one per line</span><textarea name="references" rows="3" placeholder="sources/example.md"></textarea></label>',
            '<button class="button">Create manual request</button></form>',
            "<h4>Recent requests</h4>",
            '<ul class="request-list">',
            *(
                f"<li><b>{_e(row['artifact_type'])}</b> · {_e(row['created_at'])}"
                f"<span>{_e(row['path'])}</span>"
                f"<small>{'Response recorded' if row['has_response'] else 'Awaiting agent response'}</small></li>"
                for row in list_application_requests(root, identifier)
            ),
            "</ul>",
            '<details class="danger-zone"><summary>Forget Completely</summary>',
            "<p>Removes this board record, its board history, and its opportunity and application folders. It may be rediscovered later. Backups and older reports remain.</p>",
            '<form method="post" action="/action">',
            f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="item" value="{_e(identifier)}">',
            f'<input type="hidden" name="view" value="{_e(view)}"><input type="hidden" name="action" value="purge">',
            '<label>Type FORGET to confirm<input name="confirm" autocomplete="off" required pattern="FORGET" aria-label="Type FORGET to confirm"></label>',
            '<button class="button danger">Forget Completely</button></form></details>',
            "</section>",
        ]
    )
    return "".join(parts)


def render_dashboard(root: Path, token: str, params: dict[str, str], *, notice: str = "") -> str:
    """Render the current board from the Phase 6 read model."""
    view = params.get("view", "active")
    if view not in BOARD_VIEWS:
        view = "active"
    filters = {
        key: params.get(key, "").strip()
        for key in ("search", "availability", "pipeline_state", "board_state")
    }
    try:
        offset = max(0, int(params.get("offset", "0")))
    except ValueError:
        offset = 0
    page = list_workspace_board(
        root,
        view=view,
        offset=offset,
        limit=_PAGE_SIZE,
        **{key: value or None for key, value in filters.items()},
    )
    counts = {
        lane: list_workspace_board(root, view=lane, limit=1)["total"] for lane in BOARD_VIEWS if lane != "all"
    }
    selected = params.get("item")
    detail_item = None
    if selected and OPPORTUNITY_ID.fullmatch(selected):
        matches = list_workspace_board(root, view="all", search=selected, limit=200)["items"]
        detail_item = next((item for item in matches if item["opportunity_id"] == selected), None)
    if detail_item is None and page["items"]:
        detail_item = page["items"][0]
        selected = detail_item["opportunity_id"]
    request_id = params.get("request", "")
    if detail_item and REQUEST_ID.fullmatch(request_id):
        recent = list_application_requests(root, detail_item["opportunity_id"])
        created = next((row for row in recent if row["request_id"] == request_id), None)
        if created:
            notice = f"Manual request created at {created['path']}. Open HANDOFF.md there with your agent."
    activity = list_workspace_history(root, limit=8)["events"] if view == "history" else []
    nav = "".join(
        f'<a href="{_e(_query(view=lane))}" class="nav-link{" current" if view == lane else ""}"'
        f"{' aria-current=page' if view == lane else ''}><span>{_e(lane.title())}</span><b>{counts[lane]}</b></a>"
        for lane in ("active", "waiting", "dismissed", "history")
    )
    cards = "".join(_card(item, view=view, selected=selected, filters=filters) for item in page["items"])
    if not cards:
        cards = '<div class="empty"><span aria-hidden="true">◇</span><h3>No opportunities here</h3><p>Try another view or clear your filters.</p></div>'
    paging = ""
    if offset:
        paging += f'<a class="page-link" href="{_e(_query(view=view, offset=max(0, offset - _PAGE_SIZE), **filters))}">← Previous</a>'
    if page["next_offset"] is not None:
        paging += f'<a class="page-link" href="{_e(_query(view=view, offset=page["next_offset"], **filters))}">Next →</a>'
    events = ""
    if view == "history":
        rows = "".join(
            f"<li><time>{_display(event.get('at'))}</time><strong>{_e(event.get('action', 'event'))}</strong>"
            f"<span>{_display(event.get('opportunity_id'))}</span></li>"
            for event in activity
        )
        events = f'<section class="activity"><h2>Recent activity</h2><ol>{rows or "<li>No activity recorded.</li>"}</ol></section>'
    css = files("opportunity_discovery").joinpath("dashboard.css").read_text(encoding="utf-8")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity board · {_e(view.title())}</title><style>{css}</style></head><body>
<a class="skip-link" href="#main">Skip to board</a><div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-mark">◈</span><span>OPPORTUNITY<br><b>DISCOVERY</b></span></div>
<div class="sidebar-label">PRIVATE WORKSPACE</div><nav aria-label="Board views">{nav}</nav><div class="sidebar-foot"><span class="live-dot"></span> Local board<br><small>{_e(root.name)}</small></div></aside>
<main id="main"><header class="topbar"><div><span class="eyebrow">YOUR OPPORTUNITY WORKSPACE</span><h1>{_e(view.title())} board</h1><p>Review verified leads, track your progress, and keep uncertainty visible.</p></div><div class="topbar-stat"><b>{counts["active"]}</b><span>active leads</span></div></header>
{'<div class="notice" role="status">' + _e(notice) + "</div>" if notice else ""}
<div class="mobile-nav"><nav aria-label="Board views">{nav}</nav></div>
<section class="workspace-grid"><div class="list-panel"><div class="list-head"><div><span class="eyebrow">BOARD / {_e(view.upper())}</span><h2>Opportunities <span>{page["total"]}</span></h2></div></div>
<form class="filters" method="get" action="/"><input type="hidden" name="view" value="{_e(view)}"><label class="search-label">Search opportunities<input type="search" name="search" value="{_e(filters["search"])}" placeholder="Title, organization or ID"></label>
<div class="filter-row">{_filter_options("availability", filters["availability"], ("open", "closed", "upcoming", "unknown"), "Availability")}{_filter_options("pipeline_state", filters["pipeline_state"], tuple(sorted(PIPELINE_STATES)), "Pipeline")}{_filter_options("board_state", filters["board_state"], ("active", "research_needed", "dismissed", "duplicate"), "Board state")}</div>
<div class="filter-actions"><button class="button subtle">Apply filters</button><a href="{_e(_query(view=view))}">Clear</a></div></form>
<div class="cards" aria-label="Opportunity results">{cards}</div><div class="pagination"><span>Showing {len(page["items"])} of {page["total"]}</span>{paging}</div>{events}</div>
{_detail(root, detail_item, token, view) if detail_item else '<section class="detail empty-detail"><span aria-hidden="true">◇</span><h2>Select an opportunity</h2><p>Its facts, sources and actions appear here.</p></section>'}</section></main></div></body></html>'''


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, root: Path, port: int) -> None:
        self.workspace_root = root
        self.form_token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), _DashboardHandler)


class _DashboardHandler(BaseHTTPRequestHandler):
    server: _DashboardServer

    def log_message(self, _format: str, *args: Any) -> None:
        pass  # URLs may contain private search terms.

    def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _send_html(self, status: HTTPStatus, content: str) -> None:
        data = content.encode("utf-8")
        self._headers(status, "text/html; charset=utf-8", len(data))
        self.wfile.write(data)

    def _fail(self, status: HTTPStatus, message: str) -> None:
        self._send_html(
            status,
            f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Error</title><p>{_e(message)}</p><a href="/">Back to board</a></html>',
        )

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self) -> None:
        if not self._valid_host():
            self._fail(HTTPStatus.FORBIDDEN, "Invalid local host")
            return
        parsed = urlsplit(self.path)
        if parsed.path != "/":
            self._fail(HTTPStatus.NOT_FOUND, "Page not found")
            return
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        try:
            self._send_html(
                HTTPStatus.OK, render_dashboard(self.server.workspace_root, self.server.form_token, params)
            )
        except (OSError, WorkspaceStateError) as exc:
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        if not self._valid_host() or urlsplit(self.path).path != "/action":
            self._fail(HTTPStatus.FORBIDDEN, "Invalid local request")
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers['Host']}":
            self._fail(HTTPStatus.FORBIDDEN, "Invalid request origin")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            self._fail(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Form encoding required")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= _MAX_FORM_BYTES:
            self._fail(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Invalid form size")
            return
        try:
            form = {
                key: values[-1]
                for key, values in parse_qs(
                    self.rfile.read(length).decode("utf-8"), keep_blank_values=True
                ).items()
            }
        except UnicodeDecodeError:
            self._fail(HTTPStatus.BAD_REQUEST, "Invalid form text")
            return
        if not secrets.compare_digest(form.get("token", ""), self.server.form_token):
            self._fail(HTTPStatus.FORBIDDEN, "Invalid form token")
            return
        identifier = form.get("item", "")
        action = form.get("action", "")
        view = form.get("view", "active")
        if not OPPORTUNITY_ID.fullmatch(identifier) or view not in BOARD_VIEWS:
            self._fail(HTTPStatus.BAD_REQUEST, "Invalid opportunity or view")
            return
        root = self.server.workspace_root
        request_id = None
        try:
            if action in {"done", "delete"}:
                reason_code = form.get("reason_code", "").strip() or None
                reason_text = form.get("reason_text", "").strip() or None
                if reason_code and reason_code not in _REASON_CODES:
                    raise WorkspaceStateError("Invalid reason code")
                mark_workspace_opportunity(
                    root, identifier, action, reason_code=reason_code, reason_text=reason_text
                )
            elif action == "purge":
                if form.get("confirm") != "FORGET":
                    raise WorkspaceStateError("Type FORGET to confirm complete removal")
                change_workspace_opportunity(root, identifier, "purge")
            elif action == "pipeline":
                change_workspace_opportunity(
                    root, identifier, "pipeline", pipeline_state=form.get("pipeline_state")
                )
            elif action == "wait":
                change_workspace_opportunity(
                    root,
                    identifier,
                    "wait",
                    wait_reason=form.get("wait_reason"),
                    wait_until=form.get("wait_until") or None,
                )
            elif action in {"restore", "resume"}:
                change_workspace_opportunity(root, identifier, action)
            elif action == "application-request":
                references = tuple(
                    line.strip() for line in form.get("references", "").splitlines() if line.strip()
                )
                result = create_application_request(
                    root,
                    identifier,
                    form.get("artifact_type", ""),
                    form.get("request_text", ""),
                    references=references,
                )
                request_id = result["request_id"]
            else:
                raise WorkspaceStateError("Unknown board action")
        except (OSError, WorkspaceStateError) as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        destination = _query(view=view, item=None if action == "purge" else identifier, request=request_id)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", destination)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve_workspace_dashboard(root: Path, *, port: int = 8765, open_browser: bool = True) -> None:
    """Serve an explicitly selected workspace on IPv4 loopback only."""
    root, _metadata = require_workspace(root)
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    with _DashboardServer(root, port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Private board: {url}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(url)
        with suppress(KeyboardInterrupt):
            server.serve_forever()
