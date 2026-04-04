#!/usr/bin/env python3
"""Multi-agent scheduled audit workflow entrypoint."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from .common import ensure_parent, main_cli_error, read_json, short_exc, write_json, write_summary
from .github_api import ensure_label, upsert_audit_issue
from .llm import model_for, request_markdown
from .prompts import REVIEWER_SYSTEM, build_coordinate_prompt, build_reviewer_prompt
from .review_data import collect_repo_snapshot


DEFAULT_MODEL = "MiniMax-M2.5"
AUDIT_TITLE = "AI Repo Audit"


def prepare(output_path: str) -> None:
    snapshot = collect_repo_snapshot()
    payload = {
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "head_sha": snapshot["head_sha"],
        "base_sha": snapshot["head_sha"],
        "included_files": [item["path"] for item in snapshot["files"]],
        "skipped_files": 0,
        "review_material": (
            "Recent commits:\n"
            + snapshot["recent_commits"]
            + "\n\nWorking tree status:\n"
            + snapshot["status_short"]
            + "\n\n"
            + "\n\n".join(f"### {item['path']}\n```text\n{item['content']}\n```" for item in snapshot["files"])
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    ensure_parent(output_path)
    write_json(output_path, payload)


def reviewer(role: str, input_path: str, output_path: str, strict: bool) -> int:
    payload = read_json(input_path)
    try:
        model = model_for("AI_AUDIT_MODEL", DEFAULT_MODEL)
        content = request_markdown(REVIEWER_SYSTEM, build_reviewer_prompt(role, payload), model)
        result = {"role": role, "ok": True, "content": content}
    except Exception as exc:
        result = {"role": role, "ok": False, "error": short_exc(exc)}
    ensure_parent(output_path)
    write_json(output_path, result)
    return 1 if strict and not result.get("ok") else 0


def coordinate(input_path: str, outputs: list[str], strict: bool) -> int:
    payload = read_json(input_path)
    reviewer_results = [read_json(path) for path in outputs if os.path.exists(path)]
    failed = [item for item in reviewer_results if not item.get("ok")]

    if reviewer_results and any(item.get("ok") for item in reviewer_results):
        model = model_for("AI_AUDIT_MODEL", DEFAULT_MODEL)
        try:
            final_report = request_markdown(
                REVIEWER_SYSTEM,
                build_coordinate_prompt("audit", payload, reviewer_results),
                model,
            )
        except Exception as exc:
            final_report = (
                "## Verdict\nThe audit coordinator failed and produced a degraded report.\n\n"
                "## Findings\n"
                f"- [high] workflow - audit coordinator failed with `{short_exc(exc)}`.\n\n"
                "## Test Gaps\n- Re-run the audit after fixing the coordinator failure.\n\n"
                "## Agent Breakdown\n"
                + "\n".join(
                    f"- {item.get('role', 'unknown')}: {'ok' if item.get('ok') else 'failed: ' + item.get('error', 'unknown error')}"
                    for item in reviewer_results
                )
            )
            failed.append({"role": "coordinator", "ok": False, "error": short_exc(exc)})
    else:
        final_report = (
            "## Verdict\nThe scheduled audit did not complete successfully.\n\n"
            "## Findings\n- [high] workflow - all audit agents failed.\n\n"
            "## Test Gaps\n- Re-run the audit after fixing API secret or workflow issues.\n\n"
            "## Agent Breakdown\n"
            + "\n".join(
                f"- {item.get('role', 'unknown')}: failed: {item.get('error', 'unknown error')}"
                for item in reviewer_results
            )
        )

    if os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_TOKEN"):
        ensure_label("ai-audit", "0052cc", "Automated AI repository audit")
        ensure_label("automation", "5319e7", "Automation-generated issue")
        ensure_label("triage", "d4c5f9", "Needs triage")
        upsert_audit_issue(AUDIT_TITLE, final_report, ["ai-audit", "automation", "triage"])
    write_summary(f"## AI repo audit\n\nReviewed model: `{model_for('AI_AUDIT_MODEL', DEFAULT_MODEL)}`\n\n{final_report}")
    print(final_report)
    return 1 if strict and failed else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--output", required=True)

    p_review = sub.add_parser("review")
    p_review.add_argument("--role", required=True)
    p_review.add_argument("--input", required=True)
    p_review.add_argument("--output", required=True)
    p_review.add_argument("--strict", action="store_true")

    p_coord = sub.add_parser("coordinate")
    p_coord.add_argument("--input", required=True)
    p_coord.add_argument("--review", dest="reviews", action="append", default=[])
    p_coord.add_argument("--strict", action="store_true")

    args = parser.parse_args()
    if args.cmd == "prepare":
        prepare(args.output)
    elif args.cmd == "review":
        raise SystemExit(reviewer(args.role, args.input, args.output, args.strict))
    elif args.cmd == "coordinate":
        raise SystemExit(coordinate(args.input, args.reviews, args.strict))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
