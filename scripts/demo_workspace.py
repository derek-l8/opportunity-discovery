"""Create the reusable synthetic board and handoff in a new external workspace."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from opportunity_discovery.workspace import initialize_workspace
from opportunity_discovery.workspace_actions import change_workspace_opportunity, mark_workspace_opportunity
from opportunity_discovery.workspace_application import create_application_request
from opportunity_discovery.workspace_board import list_workspace_board
from opportunity_discovery.workspace_state import apply_workspace_review

ENGINE = Path(__file__).resolve().parents[1]
DEMO = ENGINE / "tests" / "fixtures" / "demo"
GENERATION_ID = "a" * 64


def create_demo(root: Path) -> dict[str, object]:
    """Create synthetic private state; refuse an existing target to protect user files."""
    root = root.expanduser().absolute()
    if root.exists():
        raise ValueError(f"demo destination already exists: {root}")
    root.mkdir(parents=True)
    initialize_workspace(root, engine_path=ENGINE)
    profile = root / "knowledge" / "PROFILE.md"
    profile.write_text(
        "# Fictional demo profile\n\n"
        "Example Student studies computer engineering and built a classroom sensor logger. "
        "No real applicant is represented.\n",
        encoding="utf-8",
    )
    source = root / "sources" / "synthetic-project.md"
    source.write_text("# Synthetic project\n\nA fictional classroom sensor logger.\n", encoding="utf-8")
    (root / "knowledge" / "CATALOG.md").write_text(
        "# Synthetic knowledge catalog\n\n- Fictional project: `sources/synthetic-project.md`\n",
        encoding="utf-8",
    )

    scenario = json.loads((DEMO / "phase7-dashboard-candidates.json").read_text(encoding="utf-8"))
    candidates = []
    for seed in scenario["candidates"]:
        identifier = seed["opportunity_id"]
        url = f"https://synthetic.example/leads/{identifier}"
        candidates.append(
            {
                **seed,
                "lead_state": "unverified-lead",
                "canonical_url": url,
                "provenance": [{"source_id": "synthetic-demo", "source_url": url}],
                "reason_codes": [],
                "custom": {"synthetic": True},
            }
        )
    generation = root / ".opdisc" / "demo-generation"
    generation.mkdir()
    payload = "".join(json.dumps(item, sort_keys=True) + "\n" for item in candidates).encode("utf-8")
    (generation / "candidates.jsonl").write_bytes(payload)
    manifest = {
        "schema_version": "1.0",
        "generation_id": GENERATION_ID,
        "files": [{"filename": "candidates.jsonl", "sha256": hashlib.sha256(payload).hexdigest()}],
    }
    manifest_path = generation / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    review = json.loads((DEMO / "phase4-workspace-review.json").read_text(encoding="utf-8"))
    review["packet_generation_id"] = GENERATION_ID
    review["decisions"].append(scenario["extra_decision"])
    review_path = generation / "workspace-review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    apply_workspace_review(root, review_path, manifest_path=manifest_path)
    change_workspace_opportunity(
        root,
        "opp_62275629da8a983b921695cc4ce53996",
        "wait",
        wait_reason="Synthetic next-cycle verification",
        wait_until="2027-01-10",
    )
    mark_workspace_opportunity(root, "opp_3cf744c778c9ceccceb50d064383d337", "done", reason_code="timing")

    application = json.loads((DEMO / "phase8-application.json").read_text(encoding="utf-8"))
    request = application["request"]
    result = create_application_request(
        root,
        application["opportunity_id"],
        request["artifact_type"],
        request["request_text"],
        references=tuple(request["references"]),
    )
    request_root = root / result["request_path"]
    fake_response = application["fake_response"]
    fake_response["request_id"] = result["request_id"]
    artifact = request_root / fake_response["artifacts"][0]["path"]
    artifact.write_bytes((DEMO / "phase8-fake-draft.md").read_bytes())
    (request_root / "response.json").write_text(json.dumps(fake_response, indent=2) + "\n", encoding="utf-8")
    return {
        "workspace": root.as_posix(),
        "counts": {
            view: list_workspace_board(root, view=view)["total"]
            for view in ("active", "waiting", "dismissed", "history")
        },
        "request_path": result["request_path"],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/demo_workspace.py NEW-WORKSPACE-PATH", file=sys.stderr)
        return 2
    try:
        result = create_demo(Path(sys.argv[1]))
    except (OSError, ValueError) as exc:
        print(f"ERROR demo not created: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    print("Launch with: opdisc workspace-dashboard NEW-WORKSPACE-PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
