#!/usr/bin/env python3
"""Multi-agent scheduled audit workflow entrypoint."""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone

from .common import ensure_parent, main_cli_error, read_json, render_timestamp_lines, short_exc, write_json, write_summary
from .github_api import ensure_label, upsert_audit_issue
from .llm import model_for, request_markdown
from .prompts import REVIEWER_SYSTEM, build_coordinate_prompt, build_reviewer_prompt
from .review_data import collect_repo_snapshot


DEFAULT_MODEL = "MiniMax-M2.5"
AUDIT_TITLE = "AI Repo Audit"
SECTION_PATTERN = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _extract_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(SECTION_PATTERN.finditer(markdown))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group("title").strip()] = markdown[start:end].strip()
    return sections


def _extract_bullets(text: str) -> list[str]:
    return [line.strip()[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]


def _pick_lines(text: str, limit: int = 2) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:limit]).strip()


def _context_hint(context: dict) -> str:
    hints: list[str] = []
    related_files = context.get("related_files") or context.get("included_files") or []
    recent_issues = context.get("related_issues") or context.get("recent_issues") or []
    failed_runs = context.get("recent_failed_runs") or []
    degraded_reasons = context.get("degraded_reasons") or []

    if related_files:
        hints.append("看了关键文件：" + "、".join(str(item) for item in related_files[:4]))
    if recent_issues:
        hints.append(
            "参考了历史问题："
            + "、".join(f"#{item.get('number', '?')} {str(item.get('title', '')).strip()}" for item in recent_issues[:2])
        )
    if failed_runs:
        hints.append(
            "看了近期失败流水线："
            + "、".join(str(item.get("name", "workflow")).strip() for item in failed_runs[:2])
        )
    if context.get("degraded"):
        detail = "；".join(str(item) for item in degraded_reasons[:2]) or "部分上下文采集失败"
        hints.append(f"本次上下文有降级：{detail}")
    if not hints:
        return "- 这次主要根据仓库快照和上下文做了巡查。"
    return "\n".join(f"- {item}" for item in hints[:3])


def _format_issue_body(final_report: str, context: dict) -> str:
    sections = _extract_sections(final_report)
    purpose = _pick_lines(sections.get("这个仓库是在干什么", ""), limit=3) or "这轮还没提炼出明确的仓库业务画像。"
    findings = _extract_bullets(sections.get("最值得注意的 1-3 个问题", ""))[:3]
    suggestions = _extract_bullets(sections.get("大白话建议", ""))[:3]
    finding_lines = "\n".join(f"- {item}" for item in findings) or "- 这轮没看到需要立刻处理的大问题。"
    suggestion_lines = "\n".join(f"- {item}" for item in suggestions) or "- 可以继续跑现有方案，但建议结合真实数据流做一次抽查。"
    return (
        f"{render_timestamp_lines('Audit completed')}\n\n"
        "## 这个仓库是在干什么\n"
        f"{purpose}\n\n"
        "## 当前最值得注意的 1-3 个问题\n"
        f"{finding_lines}\n\n"
        "## 大白话建议\n"
        f"{suggestion_lines}\n\n"
        "## 它这次主要看了什么\n"
        f"{_context_hint(context)}"
    )


def _load_payload(input_path: str, context_path: str | None = None) -> dict:
    payload = read_json(input_path)
    if context_path and os.path.exists(context_path):
        payload["mcp_context"] = read_json(context_path)
    return payload


def prepare(output_path: str) -> None:
    snapshot = collect_repo_snapshot()
    payload = {
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "head_sha": snapshot["head_sha"],
        "base_sha": snapshot["head_sha"],
        "included_files": [item["path"] for item in snapshot["files"]],
        "skipped_files": [],
        "skipped_count": 0,
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


def reviewer(role: str, input_path: str, output_path: str, strict: bool, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    try:
        model = model_for("AI_AUDIT_MODEL", DEFAULT_MODEL)
        content = request_markdown(REVIEWER_SYSTEM, build_reviewer_prompt(role, payload), model)
        result = {"role": role, "ok": True, "content": content}
    except Exception as exc:
        result = {"role": role, "ok": False, "error": short_exc(exc)}
    ensure_parent(output_path)
    write_json(output_path, result)
    return 1 if strict and not result.get("ok") else 0


def _degraded_report(reviewer_results: list[dict], error: str | None = None) -> str:
    problem = (
        f"- [高] 巡查流程自己没跑通\n影响: 这次巡查结论不完整，不能完全相信“没问题”。\n判断依据: 直接证据，coordinator 失败，错误是 `{error}`。\n建议: 先修巡查流程，再重新跑一遍。"
        if error
        else "- [高] 巡查流程自己没跑通\n影响: 这次没有拿到可靠的仓库结论。\n判断依据: 直接证据，所有巡查 reviewer 都失败了。\n建议: 先检查密钥、MCP 和 GitHub 权限。"
    )
    test_gap = "- 先修复巡查流程本身，再重新跑一次完整巡查。"
    agents = [
        f"- {item.get('role', 'unknown')}: {'ok' if item.get('ok') else 'failed: ' + item.get('error', 'unknown error')}"
        for item in reviewer_results
    ] or ["- auditor: failed: no audit outputs found"]
    purpose = "这是一个围绕 CTP 行情采集、数据分发和运维链路的仓库，但本次巡查流程没有完整跑通，所以仓库画像可信度有限。"
    return (
        "## 这个仓库是在干什么\n"
        f"{purpose}\n\n"
        "## 最值得注意的 1-3 个问题\n"
        f"{problem}\n\n"
        "## 大白话建议\n"
        "- 先把巡查流程跑通，再谈后续风险判断。\n\n"
        "## 测试/验证缺口\n"
        f"{test_gap}\n\n"
        "## Agent 明细\n"
        + "\n".join(agents)
        + "\n"
    )


def coordinate(input_path: str, outputs: list[str], strict: bool, report_output: str | None = None, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    reviewer_results = [read_json(path) for path in outputs if os.path.exists(path)]
    failed = [item for item in reviewer_results if not item.get("ok")]

    if reviewer_results and any(item.get("ok") for item in reviewer_results):
        model = model_for("AI_AUDIT_MODEL", DEFAULT_MODEL)
        try:
            final_report = request_markdown(REVIEWER_SYSTEM, build_coordinate_prompt("audit", payload, reviewer_results), model)
        except Exception as exc:
            final_report = _degraded_report(reviewer_results, short_exc(exc))
            failed.append({"role": "coordinator", "ok": False, "error": short_exc(exc)})
    else:
        final_report = _degraded_report(reviewer_results)

    if report_output:
        ensure_parent(report_output)
        with open(report_output, "w", encoding="utf-8") as handle:
            handle.write(final_report.rstrip() + "\n")

    if os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_TOKEN"):
        ensure_label("ai-audit", "0052cc", "Automated AI repository audit")
        ensure_label("automation", "5319e7", "Automation-generated issue")
        ensure_label("triage", "d4c5f9", "Needs triage")
        context = payload.get("mcp_context", {}) if isinstance(payload.get("mcp_context"), dict) else {}
        upsert_audit_issue(AUDIT_TITLE, _format_issue_body(final_report, context), ["ai-audit", "automation", "triage"])

    write_summary(f"## AI 仓库巡查\n\n巡查模型: `{model_for('AI_AUDIT_MODEL', DEFAULT_MODEL)}`\n\n{final_report}")
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
    p_review.add_argument("--context")
    p_review.add_argument("--strict", action="store_true")

    p_coord = sub.add_parser("coordinate")
    p_coord.add_argument("--input", required=True)
    p_coord.add_argument("--review", dest="reviews", action="append", default=[])
    p_coord.add_argument("--context")
    p_coord.add_argument("--strict", action="store_true")
    p_coord.add_argument("--output-report")

    args = parser.parse_args()
    if args.cmd == "prepare":
        prepare(args.output)
    elif args.cmd == "review":
        raise SystemExit(reviewer(args.role, args.input, args.output, args.strict, args.context))
    elif args.cmd == "coordinate":
        raise SystemExit(coordinate(args.input, args.reviews, args.strict, args.output_report, args.context))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
