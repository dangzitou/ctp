#!/usr/bin/env python3
"""Publish push-review results to a reusable GitHub issue."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from .common import main_cli_error, render_timestamp_lines
from .github_api import close_legacy_ai_issues, ensure_label, upsert_center_issue_section
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


def _format_context_hint(audit: dict) -> str:
    hints: list[str] = []
    related_files = audit.get("related_files", [])[:4]
    related_issues = audit.get("related_issues", [])[:2]
    failed_runs = audit.get("recent_failed_runs", [])[:2]
    degraded_reasons = audit.get("degraded_reasons", [])[:2]

    if related_files:
        hints.append("看了相关文件：" + "、".join(str(item) for item in related_files))
    if related_issues:
        hints.append(
            "参考了历史问题："
            + "、".join(f"#{item.get('number', '?')} {str(item.get('title', '')).strip()}" for item in related_issues)
        )
    if failed_runs:
        hints.append(
            "检查了近期失败流水线："
            + "、".join(str(item.get("name", "workflow")).strip() for item in failed_runs)
        )
    if audit.get("degraded"):
        detail = "；".join(str(item) for item in degraded_reasons) or "部分上下文采集失败"
        hints.append(f"本次上下文有降级：{detail}")
    if not hints:
        return "- 这次主要根据 diff 和仓库上下文做了判断。"
    return "\n".join(f"- {item}" for item in hints[:3])


def _format_auto_fix(audit: dict) -> str:
    auto_fix = audit.get("auto_fix", {}) if isinstance(audit, dict) else {}
    reason = str(auto_fix.get("reason", "")).strip()
    blocked = str(auto_fix.get("blocked_reason", "")).strip()
    if auto_fix.get("changed"):
        changed_files = auto_fix.get("changed_files", [])
        changed_text = "、".join(changed_files[:4]) if changed_files else "有改动"
        return f"- 已生成自动修复改动：{changed_text}"
    if blocked:
        return f"- 这次没有自动修复，原因：{blocked}"
    if reason:
        return f"- 这次没有自动修复，原因：{reason}"
    return "- 这次没有自动修复。"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--review-status", required=True)
    parser.add_argument("--auto-fix-status", required=True)
    parser.add_argument("--audit-file")
    parser.add_argument("--mode", choices=["review", "audit", "runtime"], default="review")
    args = parser.parse_args()

    report = Path(args.report_file).read_text(encoding="utf-8")
    audit = {}
    if args.audit_file and Path(args.audit_file).exists():
        audit = json.loads(Path(args.audit_file).read_text(encoding="utf-8"))

    sections = _extract_sections(report)
    purpose = _pick_lines(sections.get("这个仓库是在干什么", ""), limit=3) or "这轮还没提炼出明确的仓库业务画像。"
    findings = _extract_bullets(sections.get("最值得注意的 1-3 个问题", ""))[:3]
    suggestions = _extract_bullets(sections.get("大白话建议", ""))[:3]

    repo = os.getenv("GITHUB_REPOSITORY", "unknown")
    ref_name = os.getenv("GITHUB_REF_NAME", "unknown")
    sha = os.getenv("GITHUB_SHA", "unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "unknown")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")

    coordinator = audit.get("coordinator", {}) if isinstance(audit, dict) else {}
    risk_level = audit.get("auto_fix", {}).get("risk_level", "unknown") if isinstance(audit, dict) else "unknown"

    finding_lines = "\n".join(f"- {item}" for item in findings) or "- 这轮没看到需要立刻处理的大问题。"
    suggestion_lines = "\n".join(f"- {item}" for item in suggestions) or "- 可以继续按现有方向推进，但建议结合真实数据流再做一次验证。"

    header_map = {
        "review": "最新一次 push 审查结果如下。",
        "audit": "最新一次仓库巡检结果如下。",
        "runtime": "最新一次运行态诊断结果如下。",
    }
    timestamp_map = {
        "review": "Review completed",
        "audit": "Audit completed",
        "runtime": "Runtime debug completed",
    }
    mode_key_map = {
        "review": "review",
        "audit": "audit",
        "runtime": "runtime",
    }

    body = (
        f"{header_map[args.mode]}\n\n"
        f"{render_timestamp_lines(timestamp_map[args.mode])}\n"
        f"- 仓库: `{repo}`\n"
        f"- 分支: `{ref_name}`\n"
        f"- 提交: `{sha}`\n"
        f"- Review 状态: `{args.review_status}`\n"
        f"- Auto-fix 状态: `{args.auto_fix_status}`\n"
        f"- Verdict: `{coordinator.get('verdict', 'unknown')}`\n"
        f"- 风险等级: `{risk_level or 'unknown'}`\n"
        f"- Workflow: {server_url}/{repo}/actions/runs/{run_id}\n"
        f"- Commit: {server_url}/{repo}/commit/{sha}\n\n"
        "## 这个仓库是在干什么\n"
        f"{purpose}\n\n"
        "## 最值得注意的 1-3 个问题\n"
        f"{finding_lines}\n\n"
        "## 大白话建议\n"
        f"{suggestion_lines}\n\n"
        "## 它这次主要看了什么\n"
        f"{_format_context_hint(audit)}\n\n"
        "## 自动修复结论\n"
        f"{_format_auto_fix(audit)}"
    )

    ensure_label("ai-review", "1d76db", "Automated AI push review result")
    ensure_label("ai-audit", "0052cc", "Automated AI repository audit")
    ensure_label("runtime-fix", "fb923c", "Runtime diagnostic or recovery change")
    ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
    ensure_label("triage", "d4c5f9", "Needs triage")
    labels = ["automation", "triage"]
    if args.mode == "review":
        labels.insert(0, "ai-review")
    else:
        labels.insert(0, "ai-audit")
    if args.mode == "runtime":
        labels.append("runtime-fix")
    upsert_center_issue_section(mode_key_map[args.mode], body, labels)
    close_legacy_ai_issues()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
