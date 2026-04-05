#!/usr/bin/env python3
"""Multi-agent push review workflow entrypoint."""

from __future__ import annotations

import argparse
import os

from .common import ensure_parent, load_event, main_cli_error, read_json, resolve_base_sha, run_git, short_exc, write_json, write_summary
from .github_api import upsert_commit_comment
from .llm import model_for, request_markdown
from .prompts import REVIEWER_SYSTEM, build_coordinate_prompt, build_reviewer_prompt
from .review_data import collect_diff, should_review


DEFAULT_MODEL = "MiniMax-M2.5"


def _compact_comment(report: str) -> str:
    kept = []
    bullet_count = 0
    for line in report.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("## ") and kept and stripped in {"## 测试/验证缺口", "## Agent 明细"}:
            break
        if stripped:
            kept.append(stripped)
        if stripped.startswith("- "):
            bullet_count += 1
            if bullet_count >= 5:
                break
    return "\n".join(kept).strip() or report.strip()


def _load_payload(input_path: str, context_path: str | None = None) -> dict:
    payload = read_json(input_path)
    if context_path and os.path.exists(context_path):
        payload["mcp_context"] = read_json(context_path)
    return payload


def prepare(output_path: str) -> None:
    head_sha = os.getenv("GITHUB_SHA", "").strip() or run_git("rev-parse", "HEAD")
    event = load_event()
    base_sha = resolve_base_sha(event, head_sha)
    all_changed_files = [line.strip() for line in run_git("diff", "--name-only", base_sha, head_sha).splitlines() if line.strip()]
    reviewable_files = [path for path in all_changed_files if should_review(path)]
    diff_text, included_files, skipped_count = collect_diff(base_sha, head_sha, reviewable_files)
    included_set = set(included_files)
    skipped_files = [path for path in reviewable_files if path not in included_set]
    payload = {
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "all_changed_files": all_changed_files,
        "included_files": included_files,
        "skipped_files": skipped_files,
        "skipped_count": skipped_count,
        "review_material": diff_text,
    }
    ensure_parent(output_path)
    write_json(output_path, payload)


def reviewer(role: str, input_path: str, output_path: str, strict: bool, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    try:
        if not payload.get("review_material"):
            result = {
                "role": role,
                "ok": True,
                "content": (
                    "## 这个仓库是在干什么\n"
                    "这是一个围绕 CTP 行情采集、数据分发和运行维护的仓库，但这次提交没有带来可审查的有效代码改动。\n\n"
                    "## 最值得注意的 1-3 个问题\n"
                    "- 这轮没看到需要立刻处理的大问题。\n\n"
                    "## 大白话建议\n"
                    "- 继续关注真实数据流和运行状态，不要只看流程是否执行成功。\n\n"
                    "## 测试/验证缺口\n"
                    "- 这轮没有额外必须补的验证动作。\n"
                ),
            }
        else:
            model = model_for("AI_REVIEW_MODEL", DEFAULT_MODEL)
            content = request_markdown(REVIEWER_SYSTEM, build_reviewer_prompt(role, payload), model)
            result = {"role": role, "ok": True, "content": content}
    except Exception as exc:
        result = {"role": role, "ok": False, "error": short_exc(exc)}
    ensure_parent(output_path)
    write_json(output_path, result)
    return 1 if strict and not result.get("ok") else 0


def _degraded_report(reviewer_results: list[dict], error: str | None = None) -> str:
    findings = (
        f"- [高] 审查流程自己没跑通\n影响: 这次结论不完整，不能把“没报错”当成真的没问题。\n判断依据: 直接证据，coordinator 失败，错误是 `{error}`。\n建议: 先修审查流程，再重新跑一遍。"
        if error
        else "- [高] 审查流程自己没跑通\n影响: 这次没有拿到可靠的审查结论。\n判断依据: 直接证据，所有 reviewer agent 都失败了。\n建议: 先检查模型密钥、MCP 和 GitHub 权限。"
    )
    agents = [
        f"- {item.get('role', 'unknown')}: {'ok' if item.get('ok') else 'failed: ' + item.get('error', 'unknown error')}"
        for item in reviewer_results
    ]
    return (
        "## 这个仓库是在干什么\n"
        "这是一个围绕 CTP 行情采集、数据分发和运维链路的仓库，但这次审查流程没有完整跑通，所以当前结论可信度有限。\n\n"
        "## 最值得注意的 1-3 个问题\n"
        f"{findings}\n\n"
        "## 大白话建议\n"
        "- 先把审查流程跑通，再谈仓库是否真的安全。\n\n"
        "## 测试/验证缺口\n"
        "- 先修复审查流程本身，再重新跑一次完整审查。\n\n"
        "## Agent 明细\n"
        + "\n".join(agents)
    )


def coordinate(input_path: str, outputs: list[str], strict: bool, report_output: str | None = None, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    reviewer_results = [read_json(path) for path in outputs if os.path.exists(path)]
    failed = [item for item in reviewer_results if not item.get("ok")]

    if reviewer_results and any(item.get("ok") for item in reviewer_results):
        model = model_for("AI_REVIEW_MODEL", DEFAULT_MODEL)
        try:
            final_report = request_markdown(REVIEWER_SYSTEM, build_coordinate_prompt("review", payload, reviewer_results), model)
        except Exception as exc:
            final_report = _degraded_report(reviewer_results, short_exc(exc))
            failed.append({"role": "coordinator", "ok": False, "error": short_exc(exc)})
    else:
        final_report = _degraded_report(reviewer_results)

    if report_output:
        ensure_parent(report_output)
        with open(report_output, "w", encoding="utf-8") as handle:
            handle.write(final_report.rstrip() + "\n")
    write_summary(f"## AI 代码审查\n\n审查模型: `{model_for('AI_REVIEW_MODEL', DEFAULT_MODEL)}`\n\n{final_report}")
    if os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_TOKEN"):
        upsert_commit_comment(_compact_comment(final_report), payload["head_sha"])
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
