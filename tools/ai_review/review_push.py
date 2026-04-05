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
        if stripped.startswith("## ") and kept and ("测试缺口" in stripped or "娴嬭瘯缂哄彛" in stripped):
            break
        if stripped:
            kept.append(stripped)
        if stripped.startswith("- "):
            bullet_count += 1
            if bullet_count >= 6:
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
                    "## 总结\n本次提交没有检测到可审查的有效变更。\n\n"
                    "## 发现\n- 未发现需要优先处理的重大问题。\n\n"
                    "## 测试缺口\n- 本轮审查未识别出关键的额外测试缺口。\n"
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


def coordinate(input_path: str, outputs: list[str], strict: bool, report_output: str | None = None, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    reviewer_results = [read_json(path) for path in outputs if os.path.exists(path)]
    failed = [item for item in reviewer_results if not item.get("ok")]

    if reviewer_results and any(item.get("ok") for item in reviewer_results):
        model = model_for("AI_REVIEW_MODEL", DEFAULT_MODEL)
        try:
            final_report = request_markdown(REVIEWER_SYSTEM, build_coordinate_prompt("review", payload, reviewer_results), model)
        except Exception as exc:
            final_report = (
                "## 总结\ncoordinator 执行失败，当前仅提供降级结果。\n"
                "## 发现\n"
                f"- [高] workflow - coordinator 执行失败，错误为 `{short_exc(exc)}`；当前审查结论可能不完整。\n"
                "## 测试缺口\n- 修复 coordinator 后重新运行代码审查 workflow。\n"
                "## Agent 明细\n"
                + "\n".join(
                    f"- {item.get('role', 'unknown')}: {'ok' if item.get('ok') else 'failed: ' + item.get('error', 'unknown error')}"
                    for item in reviewer_results
                )
            )
            failed.append({"role": "coordinator", "ok": False, "error": short_exc(exc)})
    else:
        final_report = (
            "## 总结\n多 agent 代码审查未能成功完成。\n"
            "## 发现\n- [高] workflow - 所有 reviewer agent 都失败了，本次没有产出可依赖的审查结论。\n"
            "## 测试缺口\n- 请检查 API 密钥、MCP 上下文采集与 reviewer 失败原因后重新运行 workflow。\n"
            "## Agent 明细\n"
            + "\n".join(
                f"- {item.get('role', 'unknown')}: failed: {item.get('error', 'unknown error')}"
                for item in reviewer_results
            )
        )

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
