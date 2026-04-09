#!/usr/bin/env python3
"""Runtime smoke helpers for the CTP HA stack."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import REPO_ROOT, ensure_parent, main_cli_error, write_json


DEFAULT_COMPOSE_FILE = "docker_ctp/docker-compose.ha.yml"
DEFAULT_ENV_FILE = "docker_ctp/.env.ha.local"
DEFAULT_API_BASE = "http://127.0.0.1:18080"
DEFAULT_SERVICES = ["seed", "worker", "dashboard", "admin"]
DEFAULT_ENDPOINTS = ["/api/stats", "/api/instruments", "/api/kline/AL2604", "/api/kline/CU2605"]


def _normalize_repo_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def _env_file_args(env_file: str | None) -> list[str]:
    if not env_file:
        return []
    target = _normalize_repo_path(env_file)
    if not target.exists():
        return []
    return ["--env-file", str(target)]


def compose_base_command(compose_file: str = DEFAULT_COMPOSE_FILE, env_file: str | None = DEFAULT_ENV_FILE) -> list[str]:
    compose_path = _normalize_repo_path(compose_file)
    return ["docker", "compose", "-f", str(compose_path), *_env_file_args(env_file)]


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_command(command: list[str], timeout: int = 120, check: bool = False) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=check,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "command": command,
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "command": command,
        }


def wait_for_stack(compose_file: str, env_file: str | None, timeout_sec: int = 180, poll_sec: int = 5) -> dict:
    deadline = time.time() + max(timeout_sec, 1)
    last = {
        "ok": False,
        "details": "Timed out waiting for runtime services.",
    }
    while time.time() < deadline:
        snapshot = collect_runtime_snapshot(compose_file, env_file, api_base_url=None, service_names=DEFAULT_SERVICES)
        unhealthy = [service for service in snapshot.get("services", []) if service.get("state") not in {"running", "healthy"}]
        if not unhealthy:
            return {"ok": True, "details": "All tracked services are running or healthy.", "snapshot": snapshot}
        last = {
            "ok": False,
            "details": "Waiting for services: " + ", ".join(service.get("name", "unknown") for service in unhealthy),
            "snapshot": snapshot,
        }
        time.sleep(max(poll_sec, 1))
    return last


def _parse_ps_json(raw: str) -> list[dict]:
    services: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        services.append(
            {
                "name": item.get("Service", ""),
                "state": str(item.get("State", "")).lower(),
                "health": str(item.get("Health", "")).lower(),
                "publishers": item.get("Publishers") or [],
            }
        )
    return services


def _collect_logs(compose_file: str, env_file: str | None, service_names: list[str], tail: int = 150) -> dict:
    if not docker_available():
        return {service: {"ok": False, "details": "docker unavailable"} for service in service_names}
    base = compose_base_command(compose_file, env_file)
    output: dict[str, dict] = {}
    for service in service_names:
        result = run_command([*base, "logs", f"--tail={tail}", service], timeout=120)
        output[service] = {
            "ok": result["ok"],
            "details": result["stderr"] or result["stdout"][-2000:],
            "stdout": result["stdout"][-4000:],
            "stderr": result["stderr"][-2000:],
        }
    return output


def _http_probe(url: str, timeout: int = 8) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ctp-ai-runtime-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(4096).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "body_excerpt": payload[:1000],
                "error": "",
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "body_excerpt": exc.read().decode("utf-8", errors="replace")[:1000],
            "error": str(exc),
            "url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "body_excerpt": "",
            "error": str(exc),
            "url": url,
        }


def collect_runtime_snapshot(
    compose_file: str = DEFAULT_COMPOSE_FILE,
    env_file: str | None = DEFAULT_ENV_FILE,
    api_base_url: str | None = DEFAULT_API_BASE,
    service_names: list[str] | None = None,
    log_tail: int = 150,
    endpoints: list[str] | None = None,
) -> dict:
    services = service_names or DEFAULT_SERVICES
    endpoint_list = endpoints or DEFAULT_ENDPOINTS
    compose_path = _normalize_repo_path(compose_file)
    env_path = _normalize_repo_path(env_file) if env_file else None
    snapshot = {
        "compose_file": str(compose_path.relative_to(REPO_ROOT)) if compose_path.exists() else str(compose_path),
        "env_file": str(env_path.relative_to(REPO_ROOT)) if env_path and env_path.exists() else (str(env_path) if env_path else ""),
        "docker_available": docker_available(),
        "compose_config": {},
        "services": [],
        "logs": {},
        "api_checks": [],
    }

    if snapshot["docker_available"]:
        config_result = run_command([*compose_base_command(compose_file, env_file), "config"], timeout=120)
        snapshot["compose_config"] = {
            "ok": config_result["ok"],
            "details": config_result["stderr"] or ("compose config passed" if config_result["ok"] else config_result["stdout"]),
        }
        ps_result = run_command([*compose_base_command(compose_file, env_file), "ps", "--format", "json"], timeout=120)
        snapshot["services"] = _parse_ps_json(ps_result["stdout"]) if ps_result["ok"] else []
        snapshot["ps_details"] = ps_result["stderr"] or ps_result["stdout"][:1000]
        snapshot["logs"] = _collect_logs(compose_file, env_file, services, tail=log_tail)
    else:
        snapshot["compose_config"] = {"ok": False, "details": "docker unavailable"}
        snapshot["ps_details"] = "docker unavailable"
        snapshot["logs"] = {service: {"ok": False, "details": "docker unavailable"} for service in services}

    if api_base_url:
        base = api_base_url.rstrip("/")
        snapshot["api_checks"] = [_http_probe(base + endpoint) for endpoint in endpoint_list]

    return snapshot


def evaluate_runtime_snapshot(snapshot: dict) -> dict:
    failures: list[str] = []
    compose_ok = bool(snapshot.get("compose_config", {}).get("ok"))
    if not compose_ok:
        failures.append("docker compose config failed")

    services = snapshot.get("services", [])
    tracked = {service.get("name"): service for service in services if service.get("name")}
    unhealthy = []
    for service_name in DEFAULT_SERVICES:
        current = tracked.get(service_name)
        if not current:
            unhealthy.append(f"{service_name}:missing")
            continue
        health = str(current.get("health", "")).lower()
        state = str(current.get("state", "")).lower()
        if health and health not in {"healthy", "running"}:
            unhealthy.append(f"{service_name}:{health}")
        elif state not in {"running", "healthy"}:
            unhealthy.append(f"{service_name}:{state}")
    if unhealthy:
        failures.append("service health issues: " + ", ".join(unhealthy))

    api_checks = snapshot.get("api_checks", [])
    api_failures = [item.get("url", "unknown") for item in api_checks if not item.get("ok")]
    if api_failures:
        failures.append("api failures: " + ", ".join(api_failures))

    return {
        "ok": not failures,
        "failures": failures,
        "summary": "runtime smoke passed" if not failures else "; ".join(failures[:6]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["run"])
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log-tail", type=int, default=150)
    args = parser.parse_args()

    snapshot = collect_runtime_snapshot(args.compose_file, args.env_file, args.api_base_url, log_tail=args.log_tail)
    snapshot["evaluation"] = evaluate_runtime_snapshot(snapshot)
    ensure_parent(args.output)
    write_json(args.output, snapshot)
    raise SystemExit(0 if snapshot["evaluation"]["ok"] else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
