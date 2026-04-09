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

from .common import REPO_ROOT, ensure_parent, env_bool, env_int, main_cli_error, read_json, write_json
from .policy import assess_paths
from .runtime_smoke import DEFAULT_API_BASE, DEFAULT_COMPOSE_FILE, DEFAULT_ENV_FILE, collect_runtime_snapshot
from .validate_runtime import validate_runtime_report


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


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _tokenize_keywords(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        normalized = _normalize_text(part)
        if not normalized:
            continue
        tokens.update(token for token in re.findall(r"[a-z0-9_./:-]{4,}", normalized) if not token.isdigit())
    return tokens


def _runtime_artifact_path(candidate: str | None) -> str:
    if not candidate:
        return ""
    value = str(candidate).strip()
    if not value:
        return ""
    target = Path(value)
    if not target.is_absolute():
        target = REPO_ROOT / target
    return str(target)


def _load_runtime_validation(runtime_report_path: str, require_api: bool, require_services: bool) -> dict:
    return validate_runtime_report(runtime_report_path, require_api=require_api, require_services=require_services)


def _collect_live_runtime_snapshot(check_api: bool) -> dict:
    return collect_runtime_snapshot(
        compose_file=DEFAULT_COMPOSE_FILE,
        env_file=DEFAULT_ENV_FILE,
        api_base_url=DEFAULT_API_BASE if check_api else None,
    )


def _check_docker_smoke(paths: list[str], runtime_report_path: str | None = None) -> dict:
    if runtime_report_path and Path(runtime_report_path).exists():
        validation = _load_runtime_validation(runtime_report_path, require_api=False, require_services=False)
        docker_gate = next((item for item in validation.get("gates", []) if item.get("gate_name") == "docker_smoke"), None)
        if docker_gate:
            return _gate(
                "docker_smoke",
                str(docker_gate.get("status", "failed")),
                True,
                str(docker_gate.get("details", "Runtime docker smoke failed.")),
                runtime_report_path,
            )

    snapshot = _collect_live_runtime_snapshot(check_api=False)
    compose = snapshot.get("compose_config", {})
    return _gate(
        "docker_smoke",
        "passed" if compose.get("ok") else "failed",
        True,
        str(compose.get("details") or ("compose config passed" if compose.get("ok") else "compose config failed")),
        runtime_report_path or str(REPO_ROOT / DEFAULT_COMPOSE_FILE),
    )


def _check_runtime_smoke(paths: list[str], runtime_report_path: str | None = None) -> dict:
    if runtime_report_path and Path(runtime_report_path).exists():
        validation = _load_runtime_validation(runtime_report_path, require_api=True, require_services=True)
        required_gates = [item for item in validation.get("gates", []) if item.get("required")]
        failed = [f"{item.get('gate_name')}: {item.get('details')}" for item in required_gates if item.get("status") != "passed"]
        return _gate(
            "runtime_smoke",
            "failed" if failed else "passed",
            True,
            "; ".join(failed[:10]) if failed else str(validation.get("runtime_summary") or "Runtime smoke passed."),
            runtime_report_path,
        )

    snapshot = _collect_live_runtime_snapshot(check_api=True)
    compose = snapshot.get("compose_config", {})
    services = {item.get("name"): item for item in snapshot.get("services", []) if item.get("name")}
    unhealthy = []
    for name in ["seed", "worker", "dashboard", "admin"]:
        current = services.get(name)
        if not current:
            unhealthy.append(f"{name}:missing")
            continue
        state = str(current.get("state", "")).lower()
        health = str(current.get("health", "")).lower()
        if health and health not in {"healthy", "running"}:
            unhealthy.append(f"{name}:{health}")
        elif state not in {"healthy", "running"}:
            unhealthy.append(f"{name}:{state}")
    failed_urls = [str(item.get("url", "unknown")) for item in snapshot.get("api_checks", []) if not item.get("ok")]
    failures = []
    if not compose.get("ok"):
        failures.append(str(compose.get("details") or "docker compose config failed"))
    if unhealthy:
        failures.append("service health issues: " + ", ".join(unhealthy))
    if failed_urls:
        failures.append("api failures: " + ", ".join(failed_urls))
    return _gate(
        "runtime_smoke",
        "failed" if failures else "passed",
        True,
        "; ".join(failures[:10]) if failures else "Runtime services and API smoke passed.",
        runtime_report_path or str(REPO_ROOT / DEFAULT_COMPOSE_FILE),
    )


def _check_git_diff_scope(paths: list[str], fix: dict) -> dict:
    if not fix.get("changed"):
        return _gate("git_diff_scope", "skipped", False, "Auto-fix did not generate file changes.")

    max_files = env_int("AI_REVIEW_MAX_CHANGED_FILES", 8)
    max_lines = env_int("AI_REVIEW_MAX_CHANGED_LINES", 400)
    changed_paths = [str(item.get("path", "")).replace("\\", "/") for item in fix.get("changes", []) if item.get("path")]
    file_count = len(changed_paths)

    git_bin = shutil.which("git")
    total_lines = 0
    details = []
    if git_bin and changed_paths:
        code, output = _run_command([git_bin, "diff", "--numstat", "--", *changed_paths], REPO_ROOT)
        if code == 0 and output:
            for line in output.splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                try:
                    added = 0 if parts[0] == "-" else int(parts[0])
                    deleted = 0 if parts[1] == "-" else int(parts[1])
                except ValueError:
                    continue
                total_lines += added + deleted
            details.append(f"git diff reports {total_lines} changed line(s)")
    if total_lines == 0:
        for item in fix.get("changes", []):
            content = str(item.get("content") or "")
            total_lines += len(content.splitlines())
        details.append("Fell back to generated file lengths because git diff stats were unavailable.")

    failures = []
    if file_count > max_files:
        failures.append(f"changed file count {file_count} exceeds limit {max_files}")
    if total_lines > max_lines:
        failures.append(f"changed line count {total_lines} exceeds limit {max_lines}")
    details.append(f"{file_count} file(s), {total_lines} line(s), limits={max_files} files/{max_lines} lines")
    return _gate(
        "git_diff_scope",
        "failed" if failures else "passed",
        True,
        "; ".join(failures + details[:2]) if failures else "; ".join(details),
    )


def _check_review_consensus(paths: list[str], fix: dict, payload: dict | None = None) -> dict:
    if not fix.get("changed"):
        return _gate("review_consensus", "skipped", False, "Auto-fix did not generate file changes.")
    if not payload:
        return _gate("review_consensus", "skipped", False, "No source payload provided for consensus check.")

    root_cause = str(fix.get("root_cause_guess") or "").strip()
    summary = str(fix.get("summary") or "").strip()
    evidence_sources = [str(item).strip().replace("\\", "/") for item in fix.get("evidence_sources", []) if str(item).strip()]
    included_files = [str(item).strip().replace("\\", "/") for item in payload.get("included_files", []) if str(item).strip()]
    source_summary = "\n".join(
        part
        for part in [
            str(payload.get("runtime_summary") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("review_material") or "")[:4000],
        ]
        if str(part).strip()
    )

    if not root_cause:
        return _gate("review_consensus", "failed", True, "Auto-fix metadata is missing root_cause_guess.")

    rationale_text = "\n".join([root_cause, summary, *evidence_sources])
    source_tokens = _tokenize_keywords(source_summary)
    rationale_tokens = _tokenize_keywords(rationale_text)
    overlapping_tokens = sorted(token for token in source_tokens.intersection(rationale_tokens) if token not in {"failed", "error", "health", "runtime", "review"})
    evidence_file_matches = [item for item in evidence_sources if item in included_files]
    referenced_files = [path for path in included_files if path and path in rationale_text]

    if evidence_file_matches or referenced_files or overlapping_tokens:
        details = []
        if evidence_file_matches:
            details.append("evidence matches included files: " + ", ".join(evidence_file_matches[:5]))
        if referenced_files:
            details.append("rationale references included files: " + ", ".join(referenced_files[:5]))
        if overlapping_tokens:
            details.append("shared keywords: " + ", ".join(overlapping_tokens[:8]))
        return _gate("review_consensus", "passed", True, "; ".join(details[:3]))

    return _gate(
        "review_consensus",
        "failed",
        True,
        "Auto-fix rationale is not clearly grounded in the source review/runtime payload.",
    )


def validate_fix(fix_path: str, output_path: str, payload_path: str | None = None, runtime_report_path: str | None = None) -> int:
    fix = read_json(fix_path)
    payload = read_json(payload_path) if payload_path and Path(payload_path).exists() else None
    runtime_report = _runtime_artifact_path(runtime_report_path or os.getenv("AI_REVIEW_RUNTIME_REPORT", ""))
    changed_paths = [str(item.get("path", "")).replace("\\", "/") for item in fix.get("changes", []) if item.get("path")]
    assessment = assess_paths(changed_paths)
    requested_gates = assessment.get("gates", [])
    gate_results = []
    gate_map = {
        "markdown_links": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_markdown_links(current_paths),
        "python_compile": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_python_compile(current_paths),
        "java_compile": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_java_compile(current_paths),
        "docker_compose_config": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_docker_compose(current_paths),
        "git_diff_scope": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_git_diff_scope(current_paths, current_fix),
        "docker_smoke": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_docker_smoke(current_paths, current_runtime_report),
        "runtime_smoke": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_runtime_smoke(current_paths, current_runtime_report),
        "review_consensus": lambda current_paths, current_fix, current_payload, current_runtime_report: _check_review_consensus(current_paths, current_fix, current_payload),
    }

    for gate_name in requested_gates:
        handler = gate_map.get(gate_name)
        if not handler:
            gate_results.append(_gate(gate_name, "skipped", False, "No handler registered."))
            continue
        gate_results.append(handler(changed_paths, fix, payload, runtime_report))

    required_ok = all(item["status"] == "passed" for item in gate_results if item["required"])
    auto_merge_enabled = env_bool("AI_REVIEW_ENABLE_AUTO_MERGE", True)
    require_consensus_for_merge = env_bool("AI_REVIEW_REQUIRE_CONSENSUS_FOR_MERGE", True)
    consensus_gate = next((item for item in gate_results if item.get("gate_name") == "review_consensus"), None)
    consensus_ok = not require_consensus_for_merge or not consensus_gate or consensus_gate.get("status") == "passed"
    auto_merge_allowed = bool(fix.get("changed")) and auto_merge_enabled and assessment["auto_merge_allowed"] and required_ok and consensus_ok

    output = {
        "ok": required_ok,
        "changed_paths": changed_paths,
        "risk_level": assessment["risk_level"],
        "auto_fix_allowed": assessment["auto_fix_allowed"],
        "auto_merge_allowed": auto_merge_allowed,
        "auto_merge_enabled": auto_merge_enabled,
        "require_consensus_for_merge": require_consensus_for_merge,
        "blocked_auto_fix_paths": assessment["blocked_auto_fix_paths"],
        "blocked_auto_merge_paths": assessment["blocked_auto_merge_paths"],
        "gates": gate_results,
        "runtime_report": runtime_report,
        "reason": "",
    }

    if not fix.get("changed"):
        output["reason"] = "Auto-fix did not generate file changes."
    elif not assessment["auto_merge_allowed"]:
        output["reason"] = "At least one changed file is outside the auto-merge policy."
    elif not auto_merge_enabled:
        output["reason"] = "AI_REVIEW_ENABLE_AUTO_MERGE disabled auto-merge."
    elif not required_ok:
        output["reason"] = "Required validation gate failed."
    elif not consensus_ok:
        output["reason"] = "Consensus gate did not pass, so auto-merge remains disabled."
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
    parser.add_argument("--payload")
    parser.add_argument("--runtime-report")
    args = parser.parse_args()
    if args.cmd == "run":
        raise SystemExit(validate_fix(args.fix, args.output, args.payload, args.runtime_report))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
