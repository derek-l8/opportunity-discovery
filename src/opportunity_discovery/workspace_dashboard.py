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
from .workspace_discovery import (
    ENGAGEMENT_TYPES,
    default_manifest_path,
    list_curated_home,
    list_explore,
)
from .workspace_screening import LANES, STATES
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
    default = (
        "Suggested"
        if name == "screening_state"
        else "Default"
        if name in {"uncapped", "personalized"}
        else "All"
    )
    choices = [f'<option value="">{default}</option>']
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
    review = item.get("review") or {}
    review_note = ""
    if view == "home":
        reasons = ", ".join(str(code).replace("-", " ") for code in review.get("reason_codes") or [])
        facts = item.get("verified_facts") or {}
        eligibility = item.get("eligibility") or {}
        unknowns = [
            label
            for label, value in (
                ("availability", item.get("availability")),
                ("eligibility", eligibility.get("conclusion")),
                ("exact deadline", item.get("exact_deadline")),
            )
            if value in (None, "", "unknown")
        ]
        review_note = (
            f'<span class="card-meta">Why selected: {_e(reasons or "reviewer reason not recorded")}</span>'
            f'<span class="card-meta">AI-reported official-page check: {_display(facts.get("checked_at"))}; '
            f"availability {_e(item.get('availability') or 'unknown')}; "
            f"eligibility {_e(eligibility.get('conclusion') or 'unknown')}. "
            f"Unknown: {_e(', '.join(unknowns) if unknowns else 'none of these fields')}.</span>"
            f'<span class="card-action">Next: {_e(item["next_action"])}</span>'
        )
    return (
        f'<a class="opportunity-card{" selected" if selected == identifier else ""}" href="{_e(href)}" '
        f'aria-label="View {_e(title)}">'
        f'<span class="card-top"><span class="eyebrow">{_e(item["lane"])} / {_e(item["board_state"] or "unknown")}</span>'
        f'<span class="card-arrow" aria-hidden="true">↗</span></span>'
        f'<strong>{_e(title)}</strong><span class="card-meta">{_e(meta or "Organization unknown")}</span>'
        f'<span class="card-badges">{_badge(item.get("availability"), "availability")}'
        f"{_badge(item.get('pipeline_state'), 'pipeline')}</span>{review_note}</a>"
    )


def _explore_card(item: dict[str, Any], *, selected: str | None, filters: dict[str, str]) -> str:
    identifier = item["opportunity_id"]
    href = _query(view="explore", item=identifier, **filters)
    title = item.get("title") or "Untitled opportunity"
    finding = item.get("screening") or {}
    focus = finding.get("focus") or {}
    screening = (
        f'<span class="card-meta">Screening: {_e(str(finding.get("state") or "").replace("-", " "))}'
        f" · {_e(str(finding.get('lane') or '').replace('-', ' '))}</span>"
        f'<span class="card-meta">Research: {_e(item.get("research_status"))}</span>'
        f'<span class="card-meta">Opportunity focus: {_e(focus.get("match"))}</span>'
        if finding
        else ""
    )
    return (
        f'<a class="opportunity-card{" selected" if selected == identifier else ""}" href="{_e(href)}" '
        f'aria-label="View {_e(title)}">'
        f'<span class="card-top"><span class="eyebrow">Public lead / '
        f"{_e('review imported' if item['review_status'] == 'reviewed' else 'no review imported')}</span>"
        '<span class="card-arrow" aria-hidden="true">↗</span></span>'
        f'<strong>{_e(title)}</strong><span class="card-meta">{_display(item.get("organization"))}</span>'
        f'<span class="card-meta">First found: {_display(str(item.get("first_seen") or "")[:10])}</span>'
        f'<span class="card-badges">{_badge(item.get("routing_state"))}'
        f"{_badge(item.get('engagement_type'))}</span>{screening}</a>"
    )


def _explore_detail(item: dict[str, Any]) -> str:
    provenance = item.get("provenance") or []
    source_rows = []
    finding = item.get("screening") or {}
    focus = finding.get("focus") or {}
    screening = ""
    if finding:
        reasons = "".join(
            f'<li>{_e(reason.get("message"))} <span class="muted">{_e(reason.get("evidence"))}</span></li>'
            for reason in finding.get("reasons") or []
        )
        questions = "".join(f"<li>{_e(question)}</li>" for question in finding.get("questions") or [])
        screening = (
            '<h3>Personal screening</h3><dl class="fact-grid">'
            f"{_field('Screening result', finding.get('state'))}"
            f"{_field('Screening recorded', finding.get('screened_at') if item.get('screening_saved') else 'Preview — not saved')}"
            f"{_field('Screening method', finding.get('origin') or 'deterministic')}"
            f"{_field('Opportunity focus', focus.get('mode') or 'No stage preference')}"
            f"{_field('Stage match', focus.get('match'))}"
            f"{_field('Official-page research', item.get('research_status'))}</dl>"
            "<p>Screening interprets collected statements. It does not verify the official page or establish eligibility.</p>"
            f"<ul>{reasons or '<li>No positive match recorded.</li>'}</ul>"
            f"<h4>Unresolved questions</h4><ul>{questions or '<li>No screening question recorded. Availability still needs official checking.</li>'}</ul>"
            f"<p>Investigation: {_e(', '.join(item.get('investigation_reasons') or []).replace('-', ' ') or 'Findings carried forward')}</p>"
        )
    if isinstance(provenance, list):
        for source in provenance:
            if isinstance(source, dict):
                source_rows.append(
                    f"<li><span>{_e(source.get('source_id') or 'Unknown source')}</span>"
                    f"{_safe_link(source.get('url') or source.get('source_url'), 'Open lead source')}</li>"
                )
    return (
        '<section class="detail" aria-labelledby="detail-title">'
        '<div class="detail-head"><div><span class="eyebrow">Explore / public lead</span>'
        f'<h2 id="detail-title">{_e(item.get("title") or "Untitled opportunity")}</h2>'
        f"<p>{_display(item.get('organization'))}</p></div>{_badge(item['review_status'])}</div>"
        f'<p class="identifier">{_e(item["opportunity_id"])}</p>'
        '<p class="evidence-note">Collector text and links are unverified. A route, score, or stated deadline does '
        "not establish availability, applicant eligibility, or fit. An unreviewed lead has no imported AI decision.</p>"
        f'<p class="lead-link">{_safe_link(item.get("canonical_url"), "Open collected lead")}</p>'
        '<dl class="fact-grid">'
        f"{_field('Review record', 'Imported' if item['review_status'] == 'reviewed' else 'None imported')}"
        f"{_field('Collector route', item.get('routing_state'))}"
        f"{_field('First found', item.get('first_seen'))}"
        f"{_field('Public score', item.get('generic_score'))}"
        f"{_field('Source-stated deadline', item.get('stated_deadline'))}"
        f'</dl>{screening}<div class="section-title"><h3>What the source says</h3></div>'
        f"<p>{_display(item.get('description_excerpt'))}</p>"
        f"<h4>Captured requirements</h4><p>{_display(item.get('requirements_text'))}</p>"
        f"<dl class='fact-grid'>{_field('Location', item.get('location_text'))}{_field('Graduation rule', item.get('graduation_window_language'))}{_field('Major language', item.get('major_language'))}{_field('Compensation', item.get('compensation_text'))}</dl>"
        "<h4>Collector provenance</h4>"
        f'<ul class="source-list">{"".join(source_rows) or "<li>No provenance recorded.</li>"}</ul>'
        "</section>"
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
        f'<div class="hero-link">{official_link}<p>Destination reported by the reviewer. Check the page again before acting.</p></div>',
        '<div class="section-title"><h3>Review-reported facts</h3><span>Unrecorded facts are shown as Unknown</span></div>',
        '<dl class="fact-grid">',
        _field("Reported availability", item.get("availability")),
        _field("Exact deadline", item.get("exact_deadline")),
        _field("Reported eligibility", eligibility.get("conclusion")),
        _field("Board state", item.get("board_state")),
        _field("Pipeline", item.get("pipeline_state")),
        _field("Last updated", item.get("updated_at")),
        "</dl>",
        '<div class="section-title"><h3>Evidence & provenance</h3></div>',
        '<dl class="fact-grid">',
        _field("Reported official source type", source_kind),
        _field("Official page checked (reported)", facts.get("checked_at")),
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


def render_dashboard(
    root: Path,
    token: str,
    params: dict[str, str],
    *,
    notice: str = "",
    manifest_path: Path | None = None,
) -> str:
    """Render AI-reviewed Home, complete public Explore, or existing board lanes."""
    view = params.get("view", "home")
    if view not in (*BOARD_VIEWS, "home", "explore"):
        view = "home"
    try:
        offset = max(0, int(params.get("offset", "0")))
    except ValueError:
        offset = 0
    counts = {
        lane: list_workspace_board(root, view=lane, limit=1)["total"] for lane in BOARD_VIEWS if lane != "all"
    }
    home_count = list_curated_home(root, limit=1)["total"]
    selected = params.get("item")
    explore_error = ""
    queue_summary: dict[str, Any] | None = None
    filters: dict[str, str]
    if view == "home":
        public_manifest = manifest_path or default_manifest_path(root)
        try:
            queue_summary = list_explore(root, public_manifest, limit=1)
        except WorkspaceStateError as exc:
            explore_error = str(exc)
    if view == "home":
        filters = {}
        page = list_curated_home(root, offset=offset, limit=_PAGE_SIZE)
        title = "Consider first"
        subtitle = "Imported AI review decisions, with the next step and uncertainty visible."
    elif view == "explore":
        filters = {
            key: params.get(key, "").strip()
            for key in (
                "search",
                "route",
                "engagement_type",
                "review_status",
                "screening_state",
                "lane",
                "uncapped",
                "personalized",
            )
        }
        if filters["route"] not in {"", "included", "research_needed", "excluded"}:
            filters["route"] = ""
        if filters["engagement_type"] not in ("", *ENGAGEMENT_TYPES):
            filters["engagement_type"] = ""
        if filters["review_status"] not in {"", "reviewed", "unreviewed"}:
            filters["review_status"] = ""
        if filters["screening_state"] not in ("", "all", *STATES):
            filters["screening_state"] = ""
        if filters["lane"] not in ("", *LANES):
            filters["lane"] = ""
        for key in ("uncapped", "personalized"):
            if filters[key] not in {"", "yes", "no"}:
                filters[key] = ""
        public_manifest = manifest_path or default_manifest_path(root)
        try:
            page = list_explore(
                root,
                public_manifest,
                search=filters["search"],
                route=filters["route"] or None,
                engagement_type=filters["engagement_type"] or None,
                review_status=filters["review_status"] or None,
                screening_state=filters["screening_state"] or None,
                lane=filters["lane"] or None,
                uncapped=filters["uncapped"] == "yes",
                personalized=filters["personalized"] != "no",
                offset=offset,
                limit=_PAGE_SIZE,
            )
            queue_summary = page
        except WorkspaceStateError as exc:
            explore_error = str(exc)
            page = {"total": 0, "next_offset": None, "items": []}
        title = "Explore all leads"
        subtitle = (
            "Personal screening across the collection; official research is shown separately."
            if page.get("personalized")
            else "Search the complete current collector review queue, including leads without AI review."
        )
    else:
        filters = {
            key: params.get(key, "").strip()
            for key in ("search", "availability", "pipeline_state", "board_state")
        }
        page = list_workspace_board(
            root,
            view=view,
            offset=offset,
            limit=_PAGE_SIZE,
            **{key: value or None for key, value in filters.items()},
        )
        title = f"{view.title()} board"
        subtitle = "Track imported reviews and your own application state."

    detail_item = None
    if selected and OPPORTUNITY_ID.fullmatch(selected):
        detail_item = next((item for item in page["items"] if item["opportunity_id"] == selected), None)
        if detail_item is None and view in BOARD_VIEWS:
            matches = list_workspace_board(root, view="all", search=selected, limit=200)["items"]
            detail_item = next((item for item in matches if item["opportunity_id"] == selected), None)
    if detail_item is None and page["items"]:
        detail_item = page["items"][0]
        selected = detail_item["opportunity_id"]
    request_id = params.get("request", "")
    if detail_item and view != "explore" and REQUEST_ID.fullmatch(request_id):
        recent = list_application_requests(root, detail_item["opportunity_id"])
        created = next((row for row in recent if row["request_id"] == request_id), None)
        if created:
            notice = f"Manual request created at {created['path']}. Open HANDOFF.md there with your agent."

    links = [("home", "Home", home_count)]
    links += [(lane, lane.title(), counts[lane]) for lane in ("active", "waiting", "dismissed", "history")]
    links.append(("explore", "Explore", queue_summary["queue_count"] if queue_summary else None))
    nav = "".join(
        f'<a href="{_e(_query(view=lane))}" class="nav-link{" current" if view == lane else ""}"'
        f"{' aria-current=page' if view == lane else ''}><span>{_e(label)}</span>"
        f"{'<b>' + str(count) + '</b>' if count is not None else ''}</a>"
        for lane, label, count in links
    )
    if view == "explore":
        cards = "".join(_explore_card(item, selected=selected, filters=filters) for item in page["items"])
    else:
        cards = "".join(_card(item, view=view, selected=selected, filters=filters) for item in page["items"])
    if not cards:
        if view == "home":
            message = (
                "No AI review has been imported yet. Explore the full queue; no reviewed items does not mean "
                "there is nothing worth doing. If review import failed, correct it and retry."
                if page["reviewed_count"] == 0
                else "No imported review currently calls for action. Explore still shows unreviewed leads."
            )
        elif view == "explore":
            message = (
                "Explore is unavailable until a valid current export is selected."
                if explore_error
                else "No leads match these filters in the current queue."
            )
        else:
            message = "Try another board view or clear your filters."
        cards = f'<div class="empty"><span aria-hidden="true">◇</span><h3>{_e(message)}</h3></div>'

    if view == "home":
        filters_form = (
            '<p class="view-note">Only successfully imported review decisions appear here. '
            "A failed or absent review never means the queue has nothing worth doing. "
            'Collected leads and preliminary screening are in <a href="/?view=explore">Explore</a>.</p>'
        )
    else:
        filter_rows = (
            _filter_options(
                "route", filters["route"], ("included", "research_needed", "excluded"), "Collector route"
            )
            + _filter_options("engagement_type", filters["engagement_type"], ENGAGEMENT_TYPES, "Type")
            + _filter_options(
                "review_status", filters["review_status"], ("reviewed", "unreviewed"), "AI review"
            )
            + _filter_options(
                "screening_state", filters["screening_state"], ("all", *STATES), "Personal screening"
            )
            + _filter_options("lane", filters["lane"], LANES, "Category")
            + _filter_options("uncapped", filters["uncapped"], ("yes",), "Show beyond employer cap")
            + _filter_options("personalized", filters["personalized"], ("no",), "Personalized view")
            if view == "explore"
            else _filter_options(
                "availability",
                filters["availability"],
                ("open", "closed", "upcoming", "unknown"),
                "Availability",
            )
            + _filter_options(
                "pipeline_state", filters["pipeline_state"], tuple(sorted(PIPELINE_STATES)), "Pipeline"
            )
            + _filter_options(
                "board_state",
                filters["board_state"],
                ("active", "research_needed", "dismissed", "duplicate"),
                "Board state",
            )
        )
        filters_form = (
            f'<form class="filters" method="get" action="/"><input type="hidden" name="view" value="{_e(view)}">'
            f'<label class="search-label">Search opportunities<input type="search" name="search" '
            f'value="{_e(filters["search"])}" placeholder="Title, organization, location or keyword"></label>'
            f'<div class="filter-row">{filter_rows}</div><div class="filter-actions">'
            f'<button class="button subtle">Apply filters</button><a href="{_e(_query(view=view))}">Clear</a>'
            "</div></form>"
        )
    paging = ""
    if offset:
        paging += f'<a class="page-link" href="{_e(_query(view=view, offset=max(0, offset - _PAGE_SIZE), **filters))}">← Previous</a>'
    if page["next_offset"] is not None:
        paging += f'<a class="page-link" href="{_e(_query(view=view, offset=page["next_offset"], **filters))}">Next →</a>'
    events = ""
    if view == "history":
        activity = list_workspace_history(root, limit=8)["events"]
        rows = "".join(
            f"<li><time>{_display(event.get('at'))}</time><strong>{_e(event.get('action', 'event'))}</strong>"
            f"<span>{_display(event.get('opportunity_id'))}</span></li>"
            for event in activity
        )
        events = f'<section class="activity"><h2>Recent activity</h2><ol>{rows or "<li>No activity recorded.</li>"}</ol></section>'
    if view == "explore":
        detail = (
            _explore_detail(detail_item)
            if detail_item
            else (
                '<section class="detail empty-detail"><h2>Select a lead</h2><p>Public source text appears here.</p></section>'
            )
        )
    else:
        detail = (
            _detail(root, detail_item, token, view)
            if detail_item
            else (
                '<section class="detail empty-detail"><h2>Select an opportunity</h2>'
                "<p>Imported review facts and actions appear here.</p></section>"
            )
        )
    coverage = ""
    coverage_summary = page if view == "explore" and not explore_error else queue_summary
    if coverage_summary:
        queue_summary = coverage_summary
        coverage = (
            f'<p class="view-note">Current queue: {queue_summary["queue_count"]}; '
            f"reviews imported: {queue_summary['reviewed_count']}; "
            f"no review imported: {queue_summary['unreviewed_count']}. "
            "An imported review may predate newer source changes.</p>"
        )
        if queue_summary.get("coverage"):
            report = queue_summary["coverage"]
            coverage = (
                f'<p class="view-note">Collection: {queue_summary["collection_count"]}; '
                f"screened: {report['screened']}; plausible: {report['plausible']}; "
                f"officially checked (reported): {report['officially_checked']}; "
                f"awaiting investigation: {report['awaiting_investigation']}. "
                f"Unsaved or outdated screening: {report['unsaved_screening']}. "
                f"Opportunity focus: {_e(queue_summary.get('opportunity_focus') or 'No stage preference')}. "
                f"{queue_summary.get('cap_exempt_programs', 0)} preferred early programs retained outside the employer cap. "
                f"{queue_summary['hidden_by_cap']} matching leads hidden by the employer cap; use the filter to show them.</p>"
            )
    elif explore_error and view in {"home", "explore"}:
        coverage = f'<p class="evidence-note" role="status">Explore unavailable: {_e(explore_error)}</p>'
    css = files("opportunity_discovery").joinpath("dashboard.css").read_text(encoding="utf-8")
    stat = (
        "Unavailable"
        if view == "explore" and explore_error
        else page["queue_count"]
        if view == "explore" and not explore_error
        else page["total"]
    )
    stat_label = (
        ("current collection leads" if page.get("personalized") else "current queue leads")
        if view == "explore"
        else "items in this view"
    )
    shown_total = "Unavailable" if view == "explore" and explore_error else str(page["total"])
    pagination = (
        "<span>Current queue unavailable</span>"
        if view == "explore" and explore_error
        else f"<span>Showing {len(page['items'])} of {page['total']}</span>{paging}"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity discovery · {_e(title)}</title><style>{css}</style></head><body>
<a class="skip-link" href="#main">Skip to opportunities</a><div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-mark">◈</span><span>OPPORTUNITY<br><b>DISCOVERY</b></span></div>
<div class="sidebar-label">PRIVATE WORKSPACE</div><nav aria-label="Discovery views">{nav}</nav><div class="sidebar-foot"><span class="live-dot"></span> Local workspace<br><small>{_e(root.name)}</small></div></aside>
<main id="main"><header class="topbar"><div><span class="eyebrow">YOUR OPPORTUNITY WORKSPACE</span><h1>{_e(title)}</h1><p>{_e(subtitle)}</p></div><div class="topbar-stat"><b>{stat}</b><span>{_e(stat_label)}</span></div></header>
{'<div class="notice" role="status">' + _e(notice) + "</div>" if notice else ""}
{coverage}<div class="mobile-nav"><nav aria-label="Discovery views">{nav}</nav></div>
<section class="workspace-grid"><div class="list-panel"><div class="list-head"><div><span class="eyebrow">{_e(view.upper())}</span><h2>Opportunities <span>{shown_total}</span></h2></div></div>
{filters_form}<div class="cards" aria-label="Opportunity results">{cards}</div><div class="pagination">{pagination}</div>{events}</div>
{detail}</section></main></div></body></html>"""


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, root: Path, port: int, manifest_path: Path | None = None) -> None:
        self.workspace_root = root
        self.manifest_path = manifest_path
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
                HTTPStatus.OK,
                render_dashboard(
                    self.server.workspace_root,
                    self.server.form_token,
                    params,
                    manifest_path=self.server.manifest_path,
                ),
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
        view = form.get("view", "home")
        if not OPPORTUNITY_ID.fullmatch(identifier) or view not in (*BOARD_VIEWS, "home"):
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


def serve_workspace_dashboard(
    root: Path,
    *,
    port: int = 8765,
    open_browser: bool = True,
    manifest_path: Path | None = None,
) -> None:
    """Serve an explicitly selected workspace on IPv4 loopback only."""
    root, _metadata = require_workspace(root)
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    with _DashboardServer(root, port, manifest_path) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Private board: {url}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(url)
        with suppress(KeyboardInterrupt):
            server.serve_forever()
