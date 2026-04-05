#!/usr/bin/env python3
"""Validate auto-fix changes before PR or auto-merge."""

from __future__ import annotations

import argparse
import os
import py_compile
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from .common import REPO_ROOT, ensure_parent, main_cli_error, read_json, write_json
from .policy import assess_paths


def _gate(name: str, status: str, required: bool, details: str, artifact_path: str = "") -> dict:
    return {
        "gate_name": name,
        "status": status,
        "required": required,
        "details": details,
        "artifact_path": artifact_path,
    }


def _collect_markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    return [match.group(1).strip() for match in pattern.finditer(text)]


def _check_markdown_links(paths: list[str]) -> dict:
    markdown_paths = [Path(REPO_ROOT / path) for path in paths if path.lower().endswith(".md")]
    if not markdown_paths:
        return _gate("markdown_links", "skipped", False, "No markdown files changed.")

    missing = []
    for path in markdown_paths:
        for target in _collect_markdown_links(path):
            if not target or target.startswith(("http://", "https://", "mailto:", "#", "/")):
                continue
            normalized = target.split("#", 1)[0]
            resolved = (path.parent / normalized).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {target}")

    if missing:
        return _gate("markdown_links", "failed", True, "Missing markdown links: " + "; ".join(missing[:20]))
    return _gate("markdown_links", "passed", True, "Markdown links resolved successfully.")


def _check_python_compile(paths: list[str]) -> dict:
    targets = {"tools/ai_review"}
    targets.update(path for path in paths if path.lower().endswith(".py"))
    files: list[Path] = []
    for target in sorted(targets):
        absolute = REPO_ROOT / target
        if absolute.is_dir():
            files.extend(sorted(absolute.rglob("*.py")))
        elif absolute.is_file():
            files.append(absolute)

    if not files:
        return _gate("python_compile", "skipped", False, "No Python files available for compilation.")

    failures = []
    for file_path in files:
        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{file_path.relative_to(REPO_ROOT)}: {exc.msg}")

    if failures:
        return _gate("python_compile", "failed", True, "Python compile failed: " + "; ".join(failures[:20]))
    return _gate("python_compile", "passed", True, f"Compiled {len(files)} Python file(s).")


def _run_command(command: list[str], workdir: Path) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()
    return result.returncode, output


def _check_java_compile(paths: list[str]) -> dict:
    java_paths = [path for path in paths if path.startswith("java_ctp_md/") or path.endswith("pom.xml")]
    if not java_paths:
        return _gate("java_compile", "skipped", False, "No Java files changed.")

    java_root = REPO_ROOT / "java_ctp_md"
    pom_path = java_root / "pom.xml"
    if not pom_path.exists():
        return _gate("java_compile", "failed", True, "java_ctp_md/pom.xml is missing.")

    try:
        ET.parse(pom_path)
    except ET.ParseError as exc:
        return _gate("java_compile", "failed", True, f"pom.xml is not well-formed XML: {exc}")

    mvn = shutil.which("mvn")
    if not mvn:
        return _gate("java_compile", "passed", True, "pom.xml is readable; Maven unavailable so compile was skipped.")

    code, output = _run_command([mvn, "-q", "-DskipTests", "compile"], java_root)
    if code != 0:
        return _gate("java_compile", "failed", True, output or "Maven compile failed.")
    return _gate("java_compile", "passed", True, "Maven compile passed.")


def _yaml_gate_for_compose(target: Path) -> str | None:
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return f"{target.name}: YAML parse failed: {exc}"
    if not isinstance(payload, dict):
        return f"{target.name}: expected a mapping at top level."
    services = payload.get("services")
    if not isinstance(services, dict) or not services:
        return f"{target.name}: missing non-empty services section."
    return None


def _check_docker_compose(paths: list[str]) -> dict:
    docker_paths = [
        path
        for path in paths
        if path.startswith("docker_ctp/")
        and (
            path.endswith((".yml", ".yaml"))
            or Path(path).name == "Dockerfile"
            or path.endswith(".sh")
        )
    ]
    if not docker_paths:
        return _gate("docker_compose_config", "skipped", False, "No Docker-related files changed.")

    targets = [
        REPO_ROOT / "docker_ctp" / "docker-compose.yml",
        REPO_ROOT / "docker_ctp" / "docker-compose.ha.yml",
    ]

    docker_bin = shutil.which("docker")
    if docker_bin:
        failures = []
        for target in targets:
            if not target.exists():
                continue
            code, output = _run_command([docker_bin, "compose", "-f", str(target), "config"], REPO_ROOT)
            if code != 0:
                failures.append(f"{target.name}: {output or 'docker compose config failed'}")
        if failures:
            return _gate("docker_compose_config", "failed", True, "; ".join(failures[:10]))
        return _gate("docker_compose_config", "passed", True, "docker compose config passed.")

    failures = [message for target in targets if target.exists() for message in [_yaml_gate_for_compose(target)] if message]
    if failures:
        return _gate("docker_compose_config", "failed", True, "; ".join(failures[:10]))
    return _gate("docker_compose_config", "passed", True, "Docker unavailable; YAML compose structure validation passed.")


def validate_fix(fix_path: str, output_path: str) -> int:
    fix = read_json(fix_path)
    changed_paths = [str(item.get("path", "")).replace("\\", "/") for item in fix.get("changes", []) if item.get("path")]
    assessment = assess_paths(changed_paths)
    requested_gates = assessment.get("gates", [])
    gate_results = []
    gate_map = {
        "markdown_links": _check_markdown_links,
        "python_compile": _check_python_compile,
        "java_compile": _check_java_compile,
        "docker_compose_config": _check_docker_compose,
    }

    for gate_name in requested_gates:
        handler = gate_map.get(gate_name)
        if not handler:
            gate_results.append(_gate(gate_name, "skipped", False, "No handler registered."))
            continue
        gate_results.append(handler(changed_paths))

    required_ok = all(item["status"] == "passed" for item in gate_results if item["required"])
    auto_merge_enabled = os.getenv("AI_REVIEW_ENABLE_AUTO_MERGE", "true").strip().lower() not in {"0", "false", "no", "off"}
    auto_merge_allowed = bool(fix.get("changed")) and auto_merge_enabled and assessment["auto_merge_allowed"] and required_ok

    output = {
        "ok": required_ok,
        "changed_paths": changed_paths,
        "risk_level": assessment["risk_level"],
        "auto_fix_allowed": assessment["auto_fix_allowed"],
        "auto_merge_allowed": auto_merge_allowed,
        "auto_merge_enabled": auto_merge_enabled,
        "blocked_auto_fix_paths": assessment["blocked_auto_fix_paths"],
        "blocked_auto_merge_paths": assessment["blocked_auto_merge_paths"],
        "gates": gate_results,
        "reason": "",
    }

    if not fix.get("changed"):
        output["reason"] = "Auto-fix did not generate file changes."
    elif not assessment["auto_merge_allowed"]:
        output["reason"] = "At least one changed file is outside the low-risk auto-merge policy."
    elif not auto_merge_enabled:
        output["reason"] = "AI_REVIEW_ENABLE_AUTO_MERGE disabled auto-merge."
    elif not required_ok:
        output["reason"] = "Required validation gate failed."
    else:
        output["reason"] = "All required validation gates passed."

    ensure_parent(output_path)
    write_json(output_path, output)
    return 0 if required_ok or not fix.get("changed") else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["run"])
    parser.add_argument("--fix", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.cmd == "run":
        raise SystemExit(validate_fix(args.fix, args.output))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
