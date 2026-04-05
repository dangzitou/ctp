#!/usr/bin/env python3
"""Create or update an AI auto-fix pull request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import main_cli_error, write_summary
from .github_api import (
    GitHubApiError,
    compare_url,
    enable_pull_request_auto_merge,
    ensure_label,
    merge_pull_request,
    pr_url,
    upsert_pull_request,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--merge-mode", choices=["none", "squash", "merge", "rebase"], default="none")
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    result = {
        "ok": True,
        "pr_created": False,
        "pr_number": None,
        "pr_url": "",
        "compare_url": compare_url(args.base, args.head),
        "merge_requested": args.merge_mode != "none",
        "merge_status": "not_requested",
    }

    try:
        ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
        ensure_label("triage", "d4c5f9", "Needs triage")
        pr = upsert_pull_request(args.title, body, args.head, args.base, ["automation", "triage"])
        pr_number = int(pr["number"])
        pr_html_url = str(pr.get("html_url") or pr_url(pr_number))
        result["pr_created"] = True
        result["pr_number"] = pr_number
        result["pr_url"] = pr_html_url

        if args.merge_mode != "none":
            try:
                merge_result = merge_pull_request(pr_number, args.merge_mode)
                result["merge_status"] = "merged" if merge_result.get("merged") else "merge_not_completed"
                if result["merge_status"] == "merged":
                    write_summary(
                        "## AI 自动修复自动合并\n\n"
                        f"PR #{pr_number} 已自动合并到 `{args.base}`。\n\n"
                        f"- PR: {pr_html_url}\n"
                        f"- 合并方式: `{args.merge_mode}`"
                    )
            except GitHubApiError as exc:
                if exc.code not in {405, 409, 422}:
                    raise
                pr_node_id = str(pr.get("node_id") or "").strip()
                if not pr_node_id:
                    raise
                enable_pull_request_auto_merge(pr_node_id, args.merge_mode.upper())
                result["merge_status"] = "auto_merge_enabled"
                write_summary(
                    "## AI 自动修复自动合并\n\n"
                    f"已为 PR #{pr_number} 启用 GitHub auto-merge，等待条件满足后自动合并到 `{args.base}`。\n\n"
                    f"- PR: {pr_html_url}\n"
                    f"- 合并方式: `{args.merge_mode}`"
                )

        print(pr_html_url)
    except GitHubApiError as exc:
        if exc.code != 403:
            raise
        fallback_url = compare_url(args.base, args.head)
        result["ok"] = False
        result["merge_status"] = "permission_denied"
        write_summary(
            "## AI 自动修复 PR\n\n"
            "当前 GitHub Token 没有创建 Pull Request 的权限，已降级为保留自动修复分支并输出对比链接。\n\n"
            f"- 修复分支: `{args.head}`\n"
            f"- 目标分支: `{args.base}`\n"
            f"- Compare 链接: {fallback_url}\n\n"
            "要让 workflow 自动创建 PR 或自动合并，请为当前令牌补齐 `pull_requests:write` 和 `contents:write` 权限，"
            "或在仓库 Secret 中配置具备该权限的 `AI_REVIEW_GH_TOKEN` 或 `AI_AUTOFIX_GITHUB_TOKEN`。\n\n"
            f"GitHub API 返回: HTTP {exc.code}\n\n```\n{exc}\n```"
        )
        print(fallback_url)
    finally:
        if args.json_output:
            try:
                Path(args.json_output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception as write_exc:
                write_summary(f"写入 JSON 输出文件失败: {write_exc}")
                try:
                    print(f"ERROR: JSON 输出写入失败: {write_exc}", file=sys.stderr)
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
