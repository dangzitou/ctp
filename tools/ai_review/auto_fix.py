#!/usr/bin/env python3
"""Best-effort AI auto-fix for reviewed changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import REPO_ROOT, ensure_parent, main_cli_error, read_json, write_json, write_summary
from .llm import model_for, request_text
from .policy import assess_paths
from .prompts import FIXER_SYSTEM, build_fix_prompt
from .review_data import should_auto_fix


DEFAULT_MODEL = "MiniMax-M2.5"


def _extract_json_blob(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Auto-fix model did not return valid JSON.")


def _normalize_changes(changes: list[dict], allowed_paths: set[str]) -> list[dict]:
    normalized = []
    seen = set()
    for item in changes:
        path = str(item.get("path", "")).strip().replace("\\", "/")
        content = item.get("content")
        if not path or path in seen or path not in allowed_paths:
            continue
        if not should_auto_fix(path) or not isinstance(content, str):
            continue
        seen.add(path)
        normalized.append({"path": path, "content": content})
    return normalized


def _base_result() -> dict:
    return {
        "ok": True,
        "changed": False,
        "summary": "",
        "root_cause_guess": "",
        "evidence_sources": [],
        "changes": [],
        "changed_files": [],
        "risk_level": "",
        "auto_fix_allowed": False,
        "auto_merge_allowed": False,
        "blocked_reason": "",
        "reason": "",
        "blocked_auto_fix_paths": [],
        "blocked_auto_merge_paths": [],
        "path_policies": [],
        "gates": [],
    }


def _load_payload(input_path: str, context_path: str | None = None) -> dict:
    payload = read_json(input_path)
    if context_path and Path(context_path).exists():
        payload["mcp_context"] = read_json(context_path)
    return payload


def _write_result(metadata_output: str, summary_output: str | None, result: dict) -> None:
    ensure_parent(metadata_output)
    write_json(metadata_output, result)
    if summary_output:
        ensure_parent(summary_output)
        body = result["summary"] + (
            "\n\n修改文件:\n" + "\n".join(f"- {item['path']}" for item in result.get("changes", []))
            if result.get("changes")
            else "\n\n未生成文件修改。"
        )
        Path(summary_output).write_text(body.rstrip() + "\n", encoding="utf-8")


def apply_fix(input_path: str, report_path: str, metadata_output: str, summary_output: str | None, context_path: str | None = None) -> int:
    payload = _load_payload(input_path, context_path)
    report_text = Path(report_path).read_text(encoding="utf-8")

    no_issue_markers = [
        "未发现需要优先处理的重大问题",
        "没有检测到可审查的有效变更",
    ]
    if any(marker in report_text for marker in no_issue_markers):
        result = _base_result()
        result["summary"] = "审查结果未发现需要自动修复的明确问题。"
        result["reason"] = result["summary"]
        result["blocked_reason"] = result["summary"]
        _write_result(metadata_output, summary_output, result)
        write_summary("## AI 自动修复\n\n未检测到需要自动修复的明确问题。")
        return 0

    file_snapshots = []
    all_paths = []
    allowed_paths = set()
    for path in payload.get("included_files", []):
        normalized = str(path).replace("\\", "/")
        full_path = REPO_ROOT / normalized
        if not full_path.exists() or not full_path.is_file():
            continue
        content = full_path.read_text(encoding="utf-8", errors="replace")
        file_snapshots.append({"path": normalized, "content": content})
        all_paths.append(normalized)
        if should_auto_fix(normalized):
            allowed_paths.add(normalized)

    assessment = assess_paths(all_paths)
    if not file_snapshots:
        result = _base_result()
        result["ok"] = False
        result["summary"] = "自动修复未执行：没有找到可安全修改的文件快照。"
        result["reason"] = result["summary"]
        result["blocked_reason"] = result["summary"]
        result["risk_level"] = assessment["risk_level"]
        result["auto_fix_allowed"] = assessment["auto_fix_allowed"]
        result["auto_merge_allowed"] = assessment["auto_merge_allowed"]
        result["blocked_auto_fix_paths"] = assessment["blocked_auto_fix_paths"]
        result["blocked_auto_merge_paths"] = assessment["blocked_auto_merge_paths"]
        result["path_policies"] = assessment["paths"]
        _write_result(metadata_output, summary_output, result)
        write_summary(f"## AI 自动修复\n\n{result['summary']}")
        return 1

    model = model_for("AI_REVIEW_MODEL", DEFAULT_MODEL)
    raw = request_text(FIXER_SYSTEM, build_fix_prompt(payload, report_text, file_snapshots), model, temperature=0.1)
    parsed = _extract_json_blob(raw)
    changes = _normalize_changes(parsed.get("changes") or [], allowed_paths)
    changed_paths = [item["path"] for item in changes]
    change_assessment = assess_paths(changed_paths)

    for item in changes:
        target = REPO_ROOT / item["path"]
        target.write_text(item["content"], encoding="utf-8")

    result = _base_result()
    result.update(
        {
            "changed": bool(changes),
            "summary": str(parsed.get("summary") or "").strip() or ("自动修复已执行。" if changes else "自动修复未生成可落地的修改。"),
            "root_cause_guess": str(parsed.get("root_cause_guess") or "").strip(),
            "evidence_sources": [str(item) for item in parsed.get("evidence_sources", []) if str(item).strip()],
            "changes": changes,
            "changed_files": changed_paths,
            "risk_level": change_assessment["risk_level"],
            "auto_fix_allowed": change_assessment["auto_fix_allowed"],
            "auto_merge_allowed": change_assessment["auto_merge_allowed"],
            "blocked_auto_fix_paths": change_assessment["blocked_auto_fix_paths"],
            "blocked_auto_merge_paths": change_assessment["blocked_auto_merge_paths"],
            "path_policies": change_assessment["paths"],
        }
    )
    if not changes:
        result["reason"] = "Model did not produce policy-compliant changes."
        result["blocked_reason"] = result["reason"]
    elif change_assessment["blocked_auto_merge_paths"]:
        result["reason"] = "Changed files include paths outside low-risk auto-merge policy."
        result["blocked_reason"] = result["reason"]
    else:
        result["reason"] = "Auto-fix generated policy-compliant changes."

    _write_result(metadata_output, summary_output, result)
    write_summary(
        "## AI 自动修复\n\n"
        + result["summary"]
        + (
            "\n\n修改文件:\n" + "\n".join(f"- `{item['path']}`" for item in changes)
            if changes
            else "\n\n未生成文件修改。"
        )
    )
    return 0


def materialize_fix(metadata_path: str) -> int:
    payload = read_json(metadata_path)
    for item in payload.get("changes", []):
        path = str(item.get("path", "")).replace("\\", "/").strip()
        content = item.get("content")
        if not path or not isinstance(content, str):
            continue
        target = REPO_ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["apply", "materialize"])
    parser.add_argument("--input")
    parser.add_argument("--report")
    parser.add_argument("--output")
    parser.add_argument("--summary-output")
    parser.add_argument("--context")
    args = parser.parse_args()

    if args.cmd == "apply":
        if not args.input or not args.report or not args.output:
            raise RuntimeError("`apply` requires --input, --report, and --output.")
        raise SystemExit(apply_fix(args.input, args.report, args.output, args.summary_output, args.context))
    if not args.input:
        raise RuntimeError("`materialize` requires --input.")
    raise SystemExit(materialize_fix(args.input))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
