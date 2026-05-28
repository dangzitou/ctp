#!/usr/bin/env python3
"""Local verification entrypoint for the guarded AI review stack."""

from __future__ import annotations

import argparse
import py_compile
from pathlib import Path

import yaml

from .audit_repo import prepare as prepare_audit
from .common import REPO_ROOT, ensure_parent, main_cli_error, write_json
from .review_push import prepare as prepare_review
from .runtime_debug import collect as collect_runtime
from .validate_runtime import validate_runtime_report

WORKFLOWS = [
    ".github/workflows/ci.yml",
]
PYTHON_ROOTS = ["tools/ai_review"]


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _compile_python() -> dict:
    files: list[Path] = []
    for relative in PYTHON_ROOTS:
        target = REPO_ROOT / relative
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.is_file():
            files.append(target)

    failures: list[str] = []
    for file_path in files:
        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{file_path.relative_to(REPO_ROOT)}: {exc.msg}")

    return {
        "name": "python_compile",
        "ok": not failures,
        "details": failures or [f"Compiled {len(files)} Python file(s)."],
        "files": [str(path.relative_to(REPO_ROOT)) for path in files],
    }


def _validate_workflows() -> dict:
    failures: list[str] = []
    checked: list[str] = []
    for relative in WORKFLOWS:
        target = REPO_ROOT / relative
        checked.append(relative)
        if not target.exists():
            failures.append(f"{relative}: missing")
            continue
        try:
            payload = yaml.safe_load(target.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            failures.append(f"{relative}: YAML parse failed: {exc}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"{relative}: expected mapping at top level")

    return {
        "name": "workflow_yaml",
        "ok": not failures,
        "details": failures or [f"Validated {len(checked)} workflow file(s)."],
        "files": checked,
    }


def _review_prepare(workdir: Path) -> dict:
    output = workdir / "review-payload.json"
    try:
        prepare_review(str(output))
        return {
            "name": "review_prepare",
            "ok": True,
            "details": [f"Generated {_relative_or_absolute(output)}"],
            "artifacts": {"payload": _relative_or_absolute(output)},
        }
    except Exception as exc:
        return {
            "name": "review_prepare",
            "ok": False,
            "details": [f"{type(exc).__name__}: {exc}"],
            "artifacts": {"payload": _relative_or_absolute(output)},
        }


def _audit_prepare(workdir: Path) -> dict:
    output = workdir / "audit-payload.json"
    try:
        prepare_audit(str(output))
        return {
            "name": "audit_prepare",
            "ok": True,
            "details": [f"Generated {_relative_or_absolute(output)}"],
            "artifacts": {"payload": _relative_or_absolute(output)},
        }
    except Exception as exc:
        return {
            "name": "audit_prepare",
            "ok": False,
            "details": [f"{type(exc).__name__}: {exc}"],
            "artifacts": {"payload": _relative_or_absolute(output)},
        }


def _runtime_check(workdir: Path, compose_file: str, env_file: str | None, api_base_url: str | None, log_tail: int) -> dict:
    json_output = workdir / "runtime-debug.json"
    report_output = workdir / "runtime-debug.md"
    payload_output = workdir / "runtime-payload.json"
    validation_output = workdir / "runtime-validation.json"

    try:
        exit_code = collect_runtime(
            str(json_output),
            str(report_output),
            str(payload_output),
            compose_file=compose_file,
            env_file=env_file,
            api_base_url=api_base_url,
            log_tail=log_tail,
        )
        validation = validate_runtime_report(
            str(json_output),
            require_api=bool(api_base_url),
            require_services=True,
        )
        write_json(validation_output, validation)
        ok = exit_code == 0 and validation.get("ok", False)
        details = [
            f"runtime collect exit={exit_code}",
            str(validation.get("reason") or "runtime validation completed"),
        ]
        return {
            "name": "runtime_smoke",
            "ok": ok,
            "details": details,
            "artifacts": {
                "report": str(report_output.relative_to(REPO_ROOT)),
                "snapshot": str(json_output.relative_to(REPO_ROOT)),
                "payload": str(payload_output.relative_to(REPO_ROOT)),
                "validation": str(validation_output.relative_to(REPO_ROOT)),
            },
            "validation": validation,
        }
    except Exception as exc:
        return {
            "name": "runtime_smoke",
            "ok": False,
            "details": [f"{type(exc).__name__}: {exc}"],
            "artifacts": {
                "report": str(report_output.relative_to(REPO_ROOT)),
                "snapshot": str(json_output.relative_to(REPO_ROOT)),
                "payload": str(payload_output.relative_to(REPO_ROOT)),
                "validation": str(validation_output.relative_to(REPO_ROOT)),
            },
        }


def run_verification(
    output_path: str,
    workspace: str,
    include_review: bool,
    include_audit: bool,
    include_runtime: bool,
    compose_file: str,
    env_file: str | None,
    api_base_url: str | None,
    log_tail: int,
) -> int:
    output = Path(output_path)
    workdir = Path(workspace)
    if not workdir.is_absolute():
        workdir = REPO_ROOT / workdir
    ensure_parent(output)
    workdir.mkdir(parents=True, exist_ok=True)

    checks: list[dict] = [
        _compile_python(),
        _validate_workflows(),
    ]
    if include_review:
        checks.append(_review_prepare(workdir))
    if include_audit:
        checks.append(_audit_prepare(workdir))
    if include_runtime:
        checks.append(_runtime_check(workdir, compose_file, env_file, api_base_url, log_tail))

    ok = all(item.get("ok", False) for item in checks)
    payload = {
        "ok": ok,
        "workspace": str(workdir.relative_to(REPO_ROOT)) if workdir.is_relative_to(REPO_ROOT) else str(workdir),
        "checks": checks,
    }
    write_json(output, payload)
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["run"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--workspace", default=".ai/local-verify")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--log-tail", type=int, default=150)
    args = parser.parse_args()

    include_review = args.all or args.review
    include_audit = args.all or args.audit
    include_runtime = args.all or args.runtime
    api_base_url = None if args.no_api else args.api_base_url

    raise SystemExit(
        run_verification(
            output_path=args.output,
            workspace=args.workspace,
            include_review=include_review,
            include_audit=include_audit,
            include_runtime=include_runtime,
            compose_file=args.compose_file,
            env_file=args.env_file,
            api_base_url=api_base_url,
            log_tail=args.log_tail,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
