"""Manual application request and synthetic agent handoff contract."""

import json
from pathlib import Path
from urllib.request import urlopen

import jsonschema
import pytest

from opportunity_discovery.cli import main
from opportunity_discovery.workspace_application import create_application_request, list_application_requests
from opportunity_discovery.workspace_board import list_workspace_board
from opportunity_discovery.workspace_state import WorkspaceStateError, apply_workspace_review
from tests.test_workspace_dashboard import dashboard, post
from tests.test_workspace_state import make_generation, make_workspace, materialize_review

ROOT = Path(__file__).parent.parent
DEMO = ROOT / "tests" / "fixtures" / "demo"
SCENARIO = json.loads((DEMO / "phase8-application.json").read_text(encoding="utf-8"))
PROMOTED_ID = SCENARIO["opportunity_id"]


def seeded_workspace(tmp_path):
    root = make_workspace(tmp_path)
    manifest = make_generation(tmp_path)
    apply_workspace_review(root, materialize_review(tmp_path), manifest_path=manifest)
    source = root / "sources" / "synthetic-project.md"
    source.write_text("# Synthetic project\nA fictional classroom sensor logger.\n", encoding="utf-8")
    return root


def test_manual_request_files_schema_fake_response_and_nonoverwrite(tmp_path, capsys):
    root = seeded_workspace(tmp_path)
    request = SCENARIO["request"]
    result = create_application_request(
        root,
        PROMOTED_ID,
        request["artifact_type"],
        request["request_text"],
        references=tuple(request["references"]),
    )
    folder = root / result["request_path"]
    assert folder.is_dir()
    assert (folder / "drafts").is_dir()
    assert (folder / "revisions").is_dir()
    assert not (folder / "response.json").exists()
    assert list((folder / "drafts").iterdir()) == []
    request_document = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    refs = json.loads((folder / "references.json").read_text(encoding="utf-8"))
    opportunity = json.loads((folder / "opportunity.json").read_text(encoding="utf-8"))
    jsonschema.validate(
        request_document,
        json.loads((ROOT / "schemas" / "workspace-application-request.schema.json").read_text()),
    )
    jsonschema.validate(
        refs, json.loads((ROOT / "schemas" / "workspace-application-references.schema.json").read_text())
    )
    board_schema = json.loads((ROOT / "schemas" / "workspace-board-page.schema.json").read_text())
    jsonschema.validate(opportunity, board_schema["properties"]["items"]["items"])
    assert opportunity["official_url"] == "https://synthetic.example/official/intern-open"
    assert opportunity["eligibility"]["conclusion"] == "no-known-hard-failure"
    assert [ref["path"] for ref in refs["references"]] == [
        "sources/synthetic-project.md",
        "knowledge/PROFILE.md",
        "knowledge/CATALOG.md",
    ]
    assert all(len(ref["sha256"]) == 64 for ref in refs["references"])
    assert "WORKSPACE.md" in (folder / "HANDOFF.md").read_text()
    assert list_application_requests(root, PROMOTED_ID)[0]["has_response"] is False

    fake = dict(SCENARIO["fake_response"])
    fake["request_id"] = result["request_id"]
    artifact = folder / fake["artifacts"][0]["path"]
    artifact.write_bytes((DEMO / "phase8-fake-draft.md").read_bytes())
    (folder / "response.json").write_text(json.dumps(fake), encoding="utf-8")
    jsonschema.validate(
        fake, json.loads((ROOT / "schemas" / "workspace-application-response.schema.json").read_text())
    )
    assert list_application_requests(root, PROMOTED_ID)[0]["has_response"] is True

    artifact.write_text("User-edited synthetic resume", encoding="utf-8")
    second = create_application_request(root, PROMOTED_ID, "cover-letter", "Make a second synthetic draft.")
    assert second["request_path"] != result["request_path"]
    assert artifact.read_text(encoding="utf-8") == "User-edited synthetic resume"
    assert not (root / second["request_path"] / "response.json").exists()
    assert list_workspace_board(root, view="active")["total"] == 2

    assert (
        main(["--json", "workspace-request", str(root), PROMOTED_ID, "essay", "Prepare a fake essay."]) == 0
    )
    cli_result = json.loads(capsys.readouterr().out)
    assert (root / cli_result["request_path"] / "request.json").is_file()


def test_request_rejects_traversal_and_symlink_before_creating_files(tmp_path):
    root = seeded_workspace(tmp_path)
    base = root / "applications" / PROMOTED_ID
    request = SCENARIO["request"]
    for reference in (
        "../knowledge/PROFILE.md",
        "sources/../knowledge/PROFILE.md",
        "sources\\bad.md",
        "knowledge/missing.md",
    ):
        with pytest.raises(WorkspaceStateError):
            create_application_request(
                root, PROMOTED_ID, request["artifact_type"], request["request_text"], references=(reference,)
            )
    assert not base.exists()
    outside = tmp_path / "outside.md"
    outside.write_text("Private synthetic file", encoding="utf-8")
    try:
        (root / "sources" / "link.md").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(WorkspaceStateError, match="symlink"):
        create_application_request(
            root, PROMOTED_ID, "resume", "Synthetic request", references=("sources/link.md",)
        )
    assert not base.exists()


def test_dashboard_creates_manual_request_from_opportunity(tmp_path):
    root = seeded_workspace(tmp_path)
    with dashboard(root) as (server, url):
        form = {
            "token": server.form_token,
            "item": PROMOTED_ID,
            "view": "active",
            "action": "application-request",
            "artifact_type": "short-answer",
            "request_text": "Write a synthetic short answer using cited private facts.",
            "references": "sources/synthetic-project.md",
        }
        response = post(url, form)
        assert response.status == 303
        assert "request=" in response.headers["Location"]
        requests = list_application_requests(root, PROMOTED_ID)
        assert len(requests) == 1
        page = urlopen(url + response.headers["Location"]).read().decode()
        assert "Manual request created at" in page
        assert requests[0]["path"] in page
        assert "Awaiting agent response" in page
