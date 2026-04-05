#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = os.getenv("GITHUB_STEP_SUMMARY", "")


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "").strip()


def write_summary(text: str) -> None:
    if not SUMMARY_PATH:
        return
    with open(SUMMARY_PATH, "a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


def append_heading(title: str, body: str) -> None:
    write_summary(f"## {title}\n\n{body}")


def load_event() -> dict:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return {}
    with open(event_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_base_sha(event: dict, head_sha: str) -> str:
    before = str(event.get("before") or "").strip()
    if before and before != "0" * 40:
        return before
    try:
        return run_git("rev-parse", f"{head_sha}^")
    except subprocess.CalledProcessError:
        return EMPTY_TREE_SHA


def read_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str | Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def run_command(command: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd or REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def short_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def main_cli_error(exc: BaseException) -> None:
    append_heading("AI automation", f"Workflow failed: `{short_exc(exc)}`")
    raise exc
