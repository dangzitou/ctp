#!/usr/bin/env python3
"""Best-effort AI auto-fix for reviewed changes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .common import REPO_ROOT, ensure_parent, main_cli_error, read_json, write_json, write_summary
from .llm import model_for, request_text
from .prompts import FIXER_SYSTEM, build_fix_prompt
from .review_data import should_review


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
    raise RuntimeError("自动修复模型没有返回合法 JSON。")


def _normalize_changes(changes: list[dict], allowed_paths: set[str]) -> list[dict]:
    normalized = []
    seen = set()
    for item in changes:
        path = str(item.get("path", "")).strip().replace("\\", "/")
        content = item.get("content")
        if not path or path in seen:
            continue
        if path not in allowed_paths:
            continue
        if not should_review(path):
            continue
        if not isinstance(content, str):
            continue
        seen.add(path)
        normalized.append({"path": path, "content": content})
    return normalized


def _looks_placeholder_summary(summary: str) -> bool:
    normalized = (summary or "").strip().lower()
    if not normalized:
        return True
    return normalized in {"一句中文总结", "自动修复已执行。", "auto fix applied"}


def _heuristic_secret_fix(file_snapshots: list[dict], report_text: str) -> tuple[str, list[dict]]:
    markers = ["硬编码", "api 密钥", "api key", "hardcoded", "secret", "token", "password"]
    if not any(marker.lower() in report_text.lower() for marker in markers):
        return "", []

    assignment_pattern = re.compile(
        r'^(?P<indent>\s*)(?P<name>[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\s*=\s*[\'"](?P<value>[^\'"]+)[\'"]\s*$',
        re.MULTILINE,
    )
    import_os_pattern = re.compile(r"^\s*import os\s*$", re.MULTILINE)

    changes = []
    for item in file_snapshots:
        original = item["content"]
        match = assignment_pattern.search(original)
        if not match:
            continue

        name = match.group("name")
        replacement = f'{match.group("indent")}{name} = os.environ.get("{name}", "")'
        updated = assignment_pattern.sub(replacement, original, count=1)
        if not import_os_pattern.search(updated):
            updated = "import os\n\n" + updated
        if updated != original:
            changes.append({"path": item["path"], "content": updated})

    if not changes:
        return "", []
    return "已通过兜底规则将硬编码敏感信息改为环境变量读取。", changes


def apply_fix(input_path: str, report_path: str, metadata_output: str, summary_output: str | None) -> int:
    payload = read_json(input_path)
    report_text = Path(report_path).read_text(encoding="utf-8")

    no_issue_markers = [
        "未发现需要优先处理的重大问题",
        "没有检测到可审查的有效变更",
    ]
    if any(marker in report_text for marker in no_issue_markers):
        result = {
            "ok": True,
            "changed": False,
            "summary": "审查结果未发现需要自动修复的明确问题。",
            "changes": [],
        }
        ensure_parent(metadata_output)
        write_json(metadata_output, result)
        if summary_output:
            ensure_parent(summary_output)
            Path(summary_output).write_text(result["summary"] + "\n", encoding="utf-8")
        write_summary("## AI 自动修复\n\n未检测到需要自动修复的明确问题。")
        return 0

    file_snapshots = []
    allowed_paths = set()
    for path in payload.get("included_files", []):
        normalized = str(path).replace("\\", "/")
        full_path = REPO_ROOT / normalized
        if not full_path.exists() or not full_path.is_file():
            continue
        content = full_path.read_text(encoding="utf-8", errors="replace")
        file_snapshots.append({"path": normalized, "content": content})
        allowed_paths.add(normalized)

    if not file_snapshots:
        result = {
            "ok": False,
            "changed": False,
            "summary": "自动修复未执行：没有找到可安全修改的文件快照。",
            "changes": [],
        }
        ensure_parent(metadata_output)
        write_json(metadata_output, result)
        if summary_output:
            ensure_parent(summary_output)
            Path(summary_output).write_text(result["summary"] + "\n", encoding="utf-8")
        write_summary(f"## AI 自动修复\n\n{result['summary']}")
        return 1

    model = model_for("AI_REVIEW_MODEL", DEFAULT_MODEL)
    raw = request_text(FIXER_SYSTEM, build_fix_prompt(payload, report_text, file_snapshots), model, temperature=0.1)
    parsed = _extract_json_blob(raw)
    summary = str(parsed.get("summary") or "").strip()
    changes = _normalize_changes(parsed.get("changes") or [], allowed_paths)

    if not changes:
        fallback_summary, fallback_changes = _heuristic_secret_fix(file_snapshots, report_text)
        if fallback_changes:
            changes = fallback_changes
            if _looks_placeholder_summary(summary):
                summary = fallback_summary

    for item in changes:
        target = REPO_ROOT / item["path"]
        target.write_text(item["content"], encoding="utf-8")

    if _looks_placeholder_summary(summary):
        summary = "自动修复已执行。"

    result = {
        "ok": True,
        "changed": bool(changes),
        "summary": summary,
        "changes": changes,
    }
    ensure_parent(metadata_output)
    write_json(metadata_output, result)
    if summary_output:
        ensure_parent(summary_output)
        body = summary + (
            "\n\n修改文件：\n" + "\n".join(f"- {item['path']}" for item in changes)
            if changes
            else "\n\n未生成文件修改。"
        )
        Path(summary_output).write_text(body.rstrip() + "\n", encoding="utf-8")
    write_summary(
        "## AI 自动修复\n\n"
        + summary
        + (
            "\n\n修改文件：\n" + "\n".join(f"- `{item['path']}`" for item in changes)
            if changes
            else "\n\n未生成文件修改。"
        )
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["apply"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output")
    args = parser.parse_args()

    if args.cmd == "apply":
        raise SystemExit(apply_fix(args.input, args.report, args.output, args.summary_output))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
