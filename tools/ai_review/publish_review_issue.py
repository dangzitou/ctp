#!/usr/bin/env python3
"""Publish push-review results to a reusable GitHub issue."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .common import main_cli_error, render_timestamp_lines
from .github_api import ensure_label, upsert_review_issue


REVIEW_ISSUE_TITLE = "AI Code Review Inbox"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--review-status", required=True)
    parser.add_argument("--auto-fix-status", required=True)
    parser.add_argument("--audit-file")
    args = parser.parse_args()

    report = Path(args.report_file).read_text(encoding="utf-8")
    audit = {}
    if args.audit_file and Path(args.audit_file).exists():
        audit = json.loads(Path(args.audit_file).read_text(encoding="utf-8"))

    repo = os.getenv("GITHUB_REPOSITORY", "unknown")
    ref_name = os.getenv("GITHUB_REF_NAME", "unknown")
    sha = os.getenv("GITHUB_SHA", "unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "unknown")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")

    auto_fix = audit.get("auto_fix", {}) if isinstance(audit, dict) else {}
    coordinator = audit.get("coordinator", {}) if isinstance(audit, dict) else {}
    validation_gates = audit.get("validation_gates", []) if isinstance(audit, dict) else []
    mcp_tool_calls = audit.get("mcp_tool_calls", []) if isinstance(audit, dict) else []
    skipped_files = audit.get("skipped_files", []) if isinstance(audit, dict) else []

    gate_lines = "\n".join(
        f"- `{gate.get('gate_name')}`: `{gate.get('status')}` (required={gate.get('required')})"
        for gate in validation_gates
    ) or "- No validation gates executed."
    mcp_lines = "\n".join(
        f"- `{item.get('server')}` / `{item.get('tool')}` / ok=`{item.get('ok')}` {item.get('detail', '')}".rstrip()
        for item in mcp_tool_calls[:20]
    ) or "- No MCP calls recorded."
    skipped_lines = "\n".join(f"- `{path}`" for path in skipped_files[:20]) or "- None"

    body = (
        "最新一次 push 审查结果如下。\n"
        f"{render_timestamp_lines('Review completed')}\n"
        f"- 仓库: `{repo}`\n"
        f"- 分支: `{ref_name}`\n"
        f"- 提交: `{sha}`\n"
        f"- Review 状态: `{args.review_status}`\n"
        f"- Auto-fix 状态: `{args.auto_fix_status}`\n"
        f"- Verdict: `{coordinator.get('verdict', 'unknown')}`\n"
        f"- MCP 启用: `{audit.get('mcp_enabled', False)}`\n"
        f"- MCP 来源: `{', '.join(audit.get('mcp_sources', [])) or 'none'}`\n"
        f"- 风险等级: `{auto_fix.get('risk_level', 'unknown') or 'unknown'}`\n"
        f"- 审查范围风险等级: `{auto_fix.get('review_scope', {}).get('risk_level', 'unknown') or 'unknown'}`\n"
        f"- 允许自动修复: `{auto_fix.get('auto_fix_allowed', False)}`\n"
        f"- 允许自动合并: `{auto_fix.get('auto_merge_allowed', False)}`\n"
        f"- 合并状态: `{auto_fix.get('merge_status', 'not_requested') or 'not_requested'}`\n"
        f"- Workflow: {server_url}/{repo}/actions/runs/{run_id}\n"
        f"- Commit: {server_url}/{repo}/commit/{sha}\n\n"
        "## MCP 摘要\n"
        f"{mcp_lines}\n\n"
        "## 跳过文件\n"
        f"{skipped_lines}\n\n"
        "## 门禁摘要\n"
        f"{gate_lines}\n\n"
        "## 自动修复结论\n"
        f"- 原因: {auto_fix.get('reason', '') or 'unknown'}\n"
        f"- 阻断原因: {auto_fix.get('blocked_reason', '') or 'none'}\n"
        f"- 阻断 auto-fix 路径: {', '.join(auto_fix.get('blocked_auto_fix_paths', [])) or 'none'}\n"
        f"- 阻断 auto-merge 路径: {', '.join(auto_fix.get('blocked_auto_merge_paths', [])) or 'none'}\n\n"
        "## 审查报告\n"
        f"{report}"
    )

    ensure_label("ai-review", "1d76db", "Automated AI push review result")
    ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
    ensure_label("triage", "d4c5f9", "Needs triage")
    upsert_review_issue(REVIEW_ISSUE_TITLE, body, ["ai-review", "automation", "triage"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
