#!/usr/bin/env python3
"""Collect runtime diagnostics and produce auto-fix-ready payloads."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .common import ensure_parent, main_cli_error, write_json
from .runtime_smoke import DEFAULT_API_BASE, DEFAULT_COMPOSE_FILE, DEFAULT_ENV_FILE, collect_runtime_snapshot, evaluate_runtime_snapshot


SERVICE_FILE_MAP = {
    "seed": ["docker_ctp/seed/ctp_seed.py", "docker_ctp/seed/ha_seed.py"],
    "worker": ["docker_ctp/worker/worker.py"],
    "dashboard": ["runtime/dashboard/app.py", "docker_ctp/dashboard/src/main/java/com/ctp/dashboard/controller/MarketController.java"],
    "admin": ["docker_ctp/admin/app.py"],
}
FALLBACK_FILES = [
    "docker_ctp/docker-compose.ha.yml",
    "docker_ctp/start-real.ps1",
    "tools/ai_review/runtime_debug.py",
    "tools/ai_review/runtime_smoke.py",
    "tools/ai_review/validate_runtime.py",
]


def _suspected_files(snapshot: dict) -> list[str]:
    files: list[str] = []
    if not snapshot.get("compose_config", {}).get("ok"):
        files.append("docker_ctp/docker-compose.ha.yml")

    for service in snapshot.get("services", []):
        name = str(service.get("name", "")).strip()
        state = str(service.get("state", "")).lower()
        health = str(service.get("health", "")).lower()
        if name in SERVICE_FILE_MAP and (state not in {"running", "healthy"} or (health and health not in {"running", "healthy"})):
            files.extend(SERVICE_FILE_MAP[name])

    for item in snapshot.get("api_checks", []):
        url = str(item.get("url", ""))
        if item.get("ok"):
            continue
        if "/api/" in url:
            files.extend(SERVICE_FILE_MAP.get("dashboard", []))
            files.append("docker_ctp/docker-compose.ha.yml")

    files.extend(FALLBACK_FILES)
    deduped = []
    for path in files:
        if path not in deduped:
            deduped.append(path)
    return deduped


def _render_markdown(snapshot: dict, evaluation: dict, suspected_files: list[str]) -> str:
    lines = [
        "## 运行态概况",
        f"- 诊断结论: {'通过' if evaluation.get('ok') else '失败'}",
        f"- 问题摘要: {evaluation.get('summary', '无')}",
        f"- 诊断来源: `{snapshot.get('compose_file', '')}`",
        "",
        "## 关键服务状态",
    ]
    services = snapshot.get("services", [])
    if services:
        for service in services:
            lines.append(
                f"- {service.get('name', 'unknown')}: state=`{service.get('state', '')}` health=`{service.get('health', '')}`"
            )
    else:
        lines.append("- 未读取到 docker compose ps 输出。")

    lines.extend(["", "## API 检查"])
    api_checks = snapshot.get("api_checks", [])
    if api_checks:
        for item in api_checks:
            status = item.get("status", 0)
            lines.append(f"- {item.get('url', 'unknown')}: {'ok' if item.get('ok') else 'failed'} (status={status})")
    else:
        lines.append("- 未执行 API 探测。")

    lines.extend(["", "## 可疑文件归因"])
    for path in suspected_files:
        lines.append(f"- {path}")

    lines.extend(["", "## 日志线索"])
    for service, log_info in (snapshot.get("logs", {}) or {}).items():
        excerpt = str(log_info.get("stdout") or log_info.get("details") or "").strip()
        if not excerpt:
            continue
        compact = " ".join(excerpt.splitlines()[-3:])[:400]
        lines.append(f"- {service}: {compact}")
    if lines[-1] == "## 日志线索":
        lines.append("- 未收集到可用日志。")
    return "\n".join(lines).rstrip() + "\n"


def collect(
    json_output: str,
    report_output: str,
    payload_output: str,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    env_file: str | None = DEFAULT_ENV_FILE,
    api_base_url: str | None = DEFAULT_API_BASE,
    log_tail: int = 150,
) -> int:
    snapshot = collect_runtime_snapshot(compose_file, env_file, api_base_url, log_tail=log_tail)
    evaluation = evaluate_runtime_snapshot(snapshot)
    suspected_files = _suspected_files(snapshot)

    payload = {
        "type": "runtime_debug",
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "base_sha": os.getenv("GITHUB_SHA", ""),
        "head_sha": os.getenv("GITHUB_SHA", ""),
        "included_files": suspected_files,
        "skipped_files": [],
        "skipped_count": 0,
        "review_material": _render_markdown(snapshot, evaluation, suspected_files),
        "runtime_snapshot": snapshot,
        "runtime_summary": evaluation.get("summary", ""),
    }

    diagnostic = {
        "ok": evaluation.get("ok", False),
        "summary": evaluation.get("summary", ""),
        "compose_file": compose_file,
        "env_file": env_file or "",
        "suspected_files": suspected_files,
        "snapshot": snapshot,
    }

    ensure_parent(json_output)
    write_json(json_output, diagnostic)
    ensure_parent(report_output)
    Path(report_output).write_text(payload["review_material"], encoding="utf-8")
    ensure_parent(payload_output)
    write_json(payload_output, payload)
    return 0 if evaluation.get("ok") else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["collect"])
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--output-payload", required=True)
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE)
    parser.add_argument("--log-tail", type=int, default=150)
    args = parser.parse_args()
    raise SystemExit(
        collect(
            args.output_json,
            args.output_report,
            args.output_payload,
            compose_file=args.compose_file,
            env_file=args.env_file,
            api_base_url=args.api_base_url,
            log_tail=args.log_tail,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
