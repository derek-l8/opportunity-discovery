"""End-to-end synthetic walkthrough from fresh workspace to browser request files."""

import json
import runpy
from pathlib import Path
from urllib.request import urlopen

from opportunity_discovery.workspace_board import list_workspace_board
from tests.test_workspace_dashboard import dashboard, post

SCRIPT = Path(__file__).parent.parent / "scripts" / "demo_workspace.py"
SCENARIO = json.loads(
    (Path(__file__).parent / "fixtures" / "demo" / "phase8-application.json").read_text(encoding="utf-8")
)


def test_synthetic_demo_browser_and_manual_request(tmp_path):
    create_demo = runpy.run_path(str(SCRIPT))["create_demo"]
    root = tmp_path / "Opportunity-Demo"
    result = create_demo(root)
    assert result["counts"] == {"active": 1, "waiting": 1, "dismissed": 2, "history": 1}
    original_request = root / result["request_path"]
    assert (original_request / "response.json").is_file()
    assert (original_request / "drafts" / "synthetic-resume.md").is_file()
    assert (root / ".opdisc" / "demo-generation" / "workspace-review.json").is_file()

    promoted = SCENARIO["opportunity_id"]
    with dashboard(root, Path(result["manifest_path"])) as (server, url):
        home = urlopen(url).read().decode()
        assert "Consider first" in home
        assert "Why selected" in home
        explore = urlopen(url + "/?view=explore&review_status=unreviewed").read().decode()
        assert "Unreviewed Materials Internship" in explore
        assert "no review imported: 1" in explore
        for view in ("active", "waiting", "dismissed", "history"):
            page = urlopen(url + "/?view=" + view).read().decode()
            assert view.title() + " board" in page
            assert "Opportunities" in page
        token = server.form_token
        assert (
            post(
                url,
                {
                    "token": token,
                    "item": promoted,
                    "view": "active",
                    "action": "pipeline",
                    "pipeline_state": "preparing",
                },
            ).status
            == 303
        )
        assert list_workspace_board(root, view="active", pipeline_state="preparing")["total"] == 1
        response = post(
            url,
            {
                "token": token,
                "item": promoted,
                "view": "active",
                "action": "application-request",
                "artifact_type": "essay",
                "request_text": "Prepare a fictional essay using the synthetic source.",
                "references": "sources/synthetic-project.md",
            },
        )
        assert response.status == 303
        updated = urlopen(url + response.headers["Location"]).read().decode()
        assert "Manual request created at" in updated
    requests = sorted((root / "applications" / promoted / "requests").iterdir())
    assert len(requests) == 2
    latest = next(path for path in requests if path != original_request)
    request = json.loads((latest / "request.json").read_text(encoding="utf-8"))
    assert request["artifact_type"] == "essay"
    assert "synthetic source" in request["request_text"]
    assert not (latest / "response.json").exists()
    assert list((latest / "drafts").iterdir()) == []
