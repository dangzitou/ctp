#!/usr/bin/env python3
"""Publish push-review results to a reusable GitHub issue."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import main_cli_error
from .github_api import ensure_label, upsert_review_issue


REVIEW_ISSUE_TITLE = "AI Code Review Inbox"



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--review-status", required=True)
    parser.add_argument("--auto-fix-status", required=True)
    args = parser.parse_args()

    report_path = Path(args.report_file)
    if not report_path.exists():
        print(f"错误: 报告文件不存在: {args.report_file}", file=sys.stderr)
        sys.exit(1)

    print(f"读取审查报告: {args.report_file}")
    report = report_path.read_text(encoding="utf-8")

    repo = os.getenv("GITHUB_REPOSITORY", "unknown")
    ref_name = os.getenv("GITHUB_REF_NAME", "unknown")
    sha = os.getenv("GITHUB_SHA", "unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "unknown")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")

    body = (
        "最新一次 push 审查结果如下。\n\n"
        f"- 仓库: `\`{repo}\`\`\n"
        f"- 分支: `\`{ref_name}\`\`\n"
        f"- 提交: `\`{sha}\`\`\n"
        f"- Review 状态: `\`{args.review_status}\`\`\n"
        f"- Auto-fix 状态: `\`{args.auto_fix_status}\`\`\n"
        f"- Workflow: {server_url}/{repo}/actions/runs/{run_id}\n"
        f"- Commit: {server_url}/{repo}/commit/{sha}\n\n"
        f"{report}"
    )


    print(f"发布审查 Issue 到仓库: {repo}")
    ensure_label("ai-review", "1d76db", "Automated AI push review result")
    ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
    ensure_label("triage", "d4c5f9", "Needs triage")
    upsert_review_issue(REVIEW_ISSUE_TITLE, body, ["ai-review", "automation", "triage"])
    print("审查 Issue 已更新完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
