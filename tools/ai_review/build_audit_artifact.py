#!/usr/bin/env python3
"""Build structured audit artifacts for review and repo audit workflows."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from .common import ensure_parent, main_cli_error, read_json, write_json


SECTION_PATTERN = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _read_text_if_exists(path: str | None, default: str = "") -> str:
    if not path or not os.path.exists(path):
        return default
    return Path(path).read_text(encoding="utf-8")


def _read_json_if_exists(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {}
    return read_json(path)


def _extract_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(SECTION_PATTERN.finditer(markdown))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group("title").strip()] = markdown[start:end].strip()
    return sections


def _extract_bullets(section_text: str) -> list[str]:
    return [line.strip()[2:].strip() for line in section_text.splitlines() if line.strip().startswith("- ")]


def _section_value(sections: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in sections.items()}
    for name in names:
        if name in sections:
            return sections[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _report_digest(report: str) -> dict:
    sections = _extract_sections(report)
    summary = _section_value(sections, "总结", "summary")
    findings = _extract_bullets(_section_value(sections, "发现", "findings"))
    test_gaps = _extract_bullets(_section_value(sections, "测试缺口", "test gaps"))
    agents = _extract_bullets(_section_value(sections, "Agent 明细", "agent breakdown"))
    verdict = "attention"
    if not findings or findings == ["未发现需要优先处理的重大问题。"]:
        verdict = "pass"
    if any("failed" in item.lower() for item in agents):
        verdict = "degraded"
    return {
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "test_gaps": test_gaps,
        "agent_breakdown": agents,
        "report_excerpt": "\n".join(report.splitlines()[:30]),
    }


def _context_fields(context: dict) -> dict:
    return {
        "mcp_enabled": context.get("mcp_enabled", False),
        "mcp_sources": context.get("mcp_sources", []),
        "mcp_tool_calls": context.get("mcp_tool_calls", []),
        "context_bundle_size": context.get("context_bundle_size", 0),
        "related_files": context.get("related_files", []),
        "related_issues": context.get("related_issues", []),
        "related_prs": context.get("related_prs", []),
        "recent_failed_runs": context.get("recent_failed_runs", []),
        "external_search_used": context.get("external_search_used", False),
        "degraded": context.get("degraded", False),
        "degraded_reasons": context.get("degraded_reasons", []),
    }


def build_review_audit(
    payload_path: str,
    reviews: list[str],
    report_path: str,
    output_path: str,
    fix_path: str | None = None,
    validation_path: str | None = None,
    pr_path: str | None = None,
    context_path: str | None = None,
) -> None:
    payload = read_json(payload_path)
    report = _read_text_if_exists(report_path, "## 总结\nreview-coordinator 未产出报告。\n")
    reviewer_results = [read_json(path) for path in reviews if os.path.exists(path)]
    fix = _read_json_if_exists(fix_path)
    validation = _read_json_if_exists(validation_path)
    pr = _read_json_if_exists(pr_path)
    context = _read_json_if_exists(context_path)
    digest = _report_digest(report)

    audit = {
        "type": "push_review",
        "repository": os.getenv("GITHUB_REPOSITORY", payload.get("repository", "unknown")),
        "branch": os.getenv("GITHUB_REF_NAME", ""),
        "sha": payload.get("head_sha") or os.getenv("GITHUB_SHA", ""),
        "base_sha": payload.get("base_sha", ""),
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
        "model": os.getenv("AI_REVIEW_MODEL", ""),
        "included_files": payload.get("included_files", []),
        "skipped_files": payload.get("skipped_files", []),
        "skipped_count": payload.get("skipped_count", 0),
        "reviewer_results": [{"role": item.get("role"), "ok": item.get("ok"), "error": item.get("error", "")} for item in reviewer_results],
        "coordinator": digest,
        "auto_fix": {
            "changed": fix.get("changed", False),
            "changed_files": fix.get("changed_files", [item.get("path") for item in fix.get("changes", []) if item.get("path")]),
            "risk_level": validation.get("risk_level", fix.get("risk_level", "")),
            "auto_fix_allowed": validation.get("auto_fix_allowed", fix.get("auto_fix_allowed")),
            "auto_merge_allowed": validation.get("auto_merge_allowed", fix.get("auto_merge_allowed")),
            "merge_status": pr.get("merge_status", "not_requested"),
            "reason": validation.get("reason", fix.get("reason", "")),
            "blocked_reason": fix.get("blocked_reason", ""),
            "root_cause_guess": fix.get("root_cause_guess", ""),
            "evidence_sources": fix.get("evidence_sources", []),
            "blocked_auto_fix_paths": validation.get("blocked_auto_fix_paths", fix.get("blocked_auto_fix_paths", [])),
            "blocked_auto_merge_paths": validation.get("blocked_auto_merge_paths", fix.get("blocked_auto_merge_paths", [])),
            "gates": validation.get("gates", []),
        },
        "validation_gates": validation.get("gates", []),
        "pr_result": pr,
    }
    audit.update(_context_fields(context))
    ensure_parent(output_path)
    write_json(output_path, audit)


def build_repo_audit(payload_path: str, reviews: list[str], report_path: str, output_path: str, context_path: str | None = None) -> None:
    payload = read_json(payload_path)
    report = _read_text_if_exists(report_path, "## 总结\naudit-coordinator 未产出报告。\n")
    reviewer_results = [read_json(path) for path in reviews if os.path.exists(path)]
    context = _read_json_if_exists(context_path)
    digest = _report_digest(report)

    audit = {
        "type": "repo_audit",
        "repository": os.getenv("GITHUB_REPOSITORY", payload.get("repository", "unknown")),
        "branch": os.getenv("GITHUB_REF_NAME", "main") or "main",
        "sha": payload.get("head_sha", ""),
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
        "model": os.getenv("AI_AUDIT_MODEL", ""),
        "generated_at": payload.get("generated_at", ""),
        "included_files": payload.get("included_files", []),
        "reviewer_results": [{"role": item.get("role"), "ok": item.get("ok"), "error": item.get("error", "")} for item in reviewer_results],
        "coordinator": digest,
    }
    audit.update(_context_fields(context))
    ensure_parent(output_path)
    write_json(output_path, audit)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    review = sub.add_parser("review")
    review.add_argument("--payload", required=True)
    review.add_argument("--review", dest="reviews", action="append", default=[])
    review.add_argument("--report", required=True)
    review.add_argument("--output", required=True)
    review.add_argument("--fix")
    review.add_argument("--validation")
    review.add_argument("--pr")
    review.add_argument("--context")

    audit = sub.add_parser("audit")
    audit.add_argument("--payload", required=True)
    audit.add_argument("--review", dest="reviews", action="append", default=[])
    audit.add_argument("--report", required=True)
    audit.add_argument("--output", required=True)
    audit.add_argument("--context")

    args = parser.parse_args()
    if args.cmd == "review":
        build_review_audit(args.payload, args.reviews, args.report, args.output, args.fix, args.validation, args.pr, args.context)
    else:
        build_repo_audit(args.payload, args.reviews, args.report, args.output, args.context)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
