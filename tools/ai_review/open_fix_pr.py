#!/usr/bin/env python3
"""Create or update an AI auto-fix pull request."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import main_cli_error, write_summary
from .github_api import GitHubApiError, compare_url, ensure_label, upsert_pull_request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    try:
        ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
        ensure_label("triage", "d4c5f9", "Needs triage")
        pr = upsert_pull_request(args.title, body, args.head, args.base, ["automation", "triage"])
        print(pr.get("html_url", ""))
    except GitHubApiError as exc:
        if exc.code != 403:
            raise
        fallback_url = compare_url(args.base, args.head)
        write_summary(
            "## AI 自动修复 PR\n\n"
            "当前 GitHub Token 没有创建 Pull Request 的权限，已降级为保留自动修复分支并输出对比链接。\n\n"
            f"- 修复分支: `{args.head}`\n"
            f"- 目标分支: `{args.base}`\n"
            f"- Compare 链接: {fallback_url}\n\n"
            "要让 workflow 自动创建 PR，请为当前令牌补齐 `pull_requests:write` 权限，"
            "或在仓库 Secret 中配置具备该权限的 `AI_REVIEW_GH_TOKEN` 或 `AI_AUTOFIX_GITHUB_TOKEN`。\n\n"
            f"GitHub API 返回: HTTP {exc.code}\n\n```\n{exc}\n```"
        )
        print(fallback_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
