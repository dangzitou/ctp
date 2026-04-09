#!/usr/bin/env python3
"""Validate runtime smoke artifacts for guarded automation."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import ensure_parent, main_cli_error, read_json, write_json
from .runtime_smoke import evaluate_runtime_snapshot


REQUIRED_RUNTIME_SERVICES = ["seed", "worker", "dashboard", "admin"]


def _gate(name: str, status: str, required: bool, details: str, artifact_path: str = "") -> dict:
    return {
        "gate_name": name,
        "status": status,
        "required": required,
        "details": details,
        "artifact_path": artifact_path,
    }


def validate_runtime_report(report_path: str, require_api: bool = True, require_services: bool = True) -> dict:
    report = read_json(report_path)
    evaluation = evaluate_runtime_snapshot(report)
    gates: list[dict] = []

    compose = report.get("compose_config", {}) if isinstance(report, dict) else {}
    gates.append(
        _gate(
            "docker_smoke",
            "passed" if compose.get("ok") else "failed",
            True,
            str(compose.get("details") or ("compose config passed" if compose.get("ok") else "compose config failed")),
            report_path,
        )
    )

    services = {item.get("name"): item for item in report.get("services", []) if isinstance(item, dict)}
    if require_services:
        missing_or_unhealthy = []
        for name in REQUIRED_RUNTIME_SERVICES:
            current = services.get(name)
            if not current:
                missing_or_unhealthy.append(f"{name}:missing")
                continue
            state = str(current.get("state", "")).lower()
            health = str(current.get("health", "")).lower()
            if health and health not in {"healthy", "running"}:
                missing_or_unhealthy.append(f"{name}:{health}")
            elif state not in {"running", "healthy"}:
                missing_or_unhealthy.append(f"{name}:{state}")
        gates.append(
            _gate(
                "service_health",
                "failed" if missing_or_unhealthy else "passed",
                True,
                ", ".join(missing_or_unhealthy) if missing_or_unhealthy else "Tracked runtime services are healthy.",
                report_path,
            )
        )

    api_checks = report.get("api_checks", []) if isinstance(report, dict) else []
    if require_api:
        failed_urls = [str(item.get("url", "unknown")) for item in api_checks if not item.get("ok")]
        gates.append(
            _gate(
                "runtime_smoke",
                "failed" if failed_urls else "passed",
                True,
                ", ".join(failed_urls) if failed_urls else "Runtime API smoke passed.",
                report_path,
            )
        )
    else:
        gates.append(_gate("runtime_smoke", "skipped", False, "Runtime API smoke not required.", report_path))

    ok = all(item["status"] == "passed" for item in gates if item["required"])
    return {
        "ok": ok and evaluation.get("ok", False),
        "reason": evaluation.get("summary", "runtime validation completed"),
        "gates": gates,
        "runtime_report": str(Path(report_path)),
        "runtime_summary": evaluation.get("summary", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["run"])
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-require-api", action="store_true")
    parser.add_argument("--no-require-services", action="store_true")
    args = parser.parse_args()

    payload = validate_runtime_report(
        args.report,
        require_api=not args.no_require_api,
        require_services=not args.no_require_services,
    )
    ensure_parent(args.output)
    write_json(args.output, payload)
    raise SystemExit(0 if payload["ok"] else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
