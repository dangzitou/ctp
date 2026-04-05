#!/usr/bin/env python3
"""Repo-local MCP server for AICR context collection."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .common import REPO_ROOT, env_int, read_json, run_command, run_git, short_exc
from .github_api import list_commit_check_runs, list_repo_issues, list_repo_pulls, list_workflow_runs


JSONRPC_VERSION = "2.0"


def _write_message(payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header)
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or "0")
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _response(msg_id: object, result: dict) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "result": result}


def _error(msg_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "error": {"code": code, "message": message}}


def _tool(name: str, description: str, schema: dict | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": schema or {"type": "object", "properties": {}},
    }


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _existing_file(path: str) -> Path | None:
    normalized = _normalize_path(path)
    candidate = (REPO_ROOT / normalized).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() and candidate.is_file() else None


def _make_relative(path_text: str) -> str:
    try:
        return os.path.relpath(path_text, REPO_ROOT).replace("\\", "/")
    except Exception:
        return path_text.replace("\\", "/")


def _module_keywords(path: str) -> list[str]:
    normalized = _normalize_path(path)
    parts = [part for part in normalized.split("/") if part and "." not in part]
    stem = Path(normalized).stem
    keywords = parts[-3:] + ([stem] if stem else [])
    return [item.lower() for item in keywords if item]


def tool_get_changed_files(arguments: dict) -> dict:
    base_sha = str(arguments.get("base_sha", "")).strip()
    head_sha = str(arguments.get("head_sha", "")).strip() or "HEAD"
    command = ["diff", "--name-only"]
    if base_sha:
        command.extend([base_sha, head_sha])
    else:
        command.append(head_sha)
    files = [line.strip() for line in run_git(*command).splitlines() if line.strip()]
    return {"files": files}


def tool_get_diff_patch(arguments: dict) -> dict:
    base_sha = str(arguments.get("base_sha", "")).strip()
    head_sha = str(arguments.get("head_sha", "")).strip() or "HEAD"
    paths = [_normalize_path(item) for item in arguments.get("paths", []) if str(item).strip()]
    command = ["diff", "--unified=3", "--no-color"]
    if base_sha:
        command.extend([base_sha, head_sha])
    else:
        command.append(head_sha)
    if paths:
        command.append("--")
        command.extend(paths)
    patch = run_git(*command)
    return {"patch": patch}


def tool_get_file_content(arguments: dict) -> dict:
    path = str(arguments.get("path", "")).strip()
    max_chars = int(arguments.get("max_chars", 12000) or 12000)
    target = _existing_file(path)
    if not target:
        return {"path": _normalize_path(path), "exists": False, "content": ""}
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return {"path": _normalize_path(path), "exists": True, "content": text}


def _related_candidates(path: str) -> list[str]:
    normalized = _normalize_path(path)
    target = _existing_file(normalized)
    if not target:
        return []
    parent = target.parent
    stem = target.stem.lower()
    suffix = target.suffix.lower()
    candidates: list[str] = []

    for sibling in sorted(parent.iterdir()):
        if sibling.is_file() and sibling.name != target.name:
            candidates.append(str(sibling.relative_to(REPO_ROOT)).replace("\\", "/"))

    text = target.read_text(encoding="utf-8", errors="replace")
    patterns = [
        re.compile(r'from\s+([A-Za-z0-9_./]+)\s+import'),
        re.compile(r'import\s+([A-Za-z0-9_./]+)'),
        re.compile(r'require\(["\'](.+?)["\']\)'),
    ]
    imports = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            raw = match.group(1).replace(".", "/")
            imports.add(raw)
    for raw in imports:
        for ext in [".py", ".java", ".md", ".yml", ".yaml", ".json", ".toml", ""]:
            candidate = _existing_file(raw + ext)
            if candidate:
                candidates.append(str(candidate.relative_to(REPO_ROOT)).replace("\\", "/"))

    for root in [REPO_ROOT / "docs", REPO_ROOT / "runtime", REPO_ROOT / "docker_ctp", REPO_ROOT / ".github" / "workflows"]:
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel == normalized:
                continue
            name = item.stem.lower()
            if stem and (stem in name or name in stem):
                candidates.append(rel)
            elif suffix == ".py" and item.suffix.lower() == ".py" and item.parent.name == parent.name:
                candidates.append(rel)

    seen = []
    for rel in candidates:
        if rel != normalized and rel not in seen:
            seen.append(rel)
    return seen


def tool_get_related_files(arguments: dict) -> dict:
    paths = [_normalize_path(item) for item in arguments.get("paths", []) if str(item).strip()]
    limit = int(arguments.get("limit", env_int("AI_REVIEW_MCP_RELATED_FILE_LIMIT", 12)) or 12)
    related: list[str] = []
    for path in paths:
        for candidate in _related_candidates(path):
            if candidate not in related:
                related.append(candidate)
            if len(related) >= limit:
                break
        if len(related) >= limit:
            break
    return {"paths": paths, "related_files": related[:limit]}


def tool_get_symbol_references(arguments: dict) -> dict:
    symbol = str(arguments.get("symbol", "")).strip()
    if not symbol:
        return {"symbol": "", "matches": []}
    result = run_command(["rg", "--json", "-n", "-S", symbol, str(REPO_ROOT)], check=False)
    matches = []
    for line in result.stdout.splitlines():
        if len(matches) >= 50:
            break
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_text = str(data.get("path", {}).get("text", ""))
        line_no = data.get("line_number")
        preview = str(data.get("lines", {}).get("text", "")).strip()
        rel = _make_relative(path_text)
        matches.append(f"{rel}:{line_no}:{preview}")
    return {"symbol": symbol, "matches": matches}


def tool_get_import_dependents(arguments: dict) -> dict:
    path = _normalize_path(str(arguments.get("path", "")).strip())
    stem = Path(path).stem
    tokens = [stem, path.replace("/", ".")]
    matches: list[str] = []
    for token in tokens:
        if not token:
            continue
        result = run_command(["rg", "--json", "-n", "-S", token, str(REPO_ROOT)], check=False)
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            rel = str(event.get("data", {}).get("path", {}).get("text", ""))
            rel = _make_relative(rel)
            if rel != path and rel not in matches:
                matches.append(rel)
    return {"path": path, "dependents": matches[:30]}


def tool_get_config_neighbors(arguments: dict) -> dict:
    paths = [_normalize_path(item) for item in arguments.get("paths", []) if str(item).strip()]
    neighbors: list[str] = []
    for path in paths:
        path_obj = Path(path)
        patterns = [path_obj.parent, REPO_ROOT / ".github" / "workflows", REPO_ROOT / "docs"]
        for folder in patterns:
            folder = folder if folder.is_absolute() else REPO_ROOT / folder
            if not folder.exists():
                continue
            for item in folder.rglob("*"):
                if not item.is_file():
                    continue
                if item.suffix.lower() not in {".yml", ".yaml", ".json", ".toml", ".env", ".md", ".sh", ".properties"}:
                    continue
                rel = str(item.relative_to(REPO_ROOT)).replace("\\", "/")
                if rel.startswith((".ai/", "java_ctp_md/target/", "docker_ctp/dashboard/target/")):
                    continue
                if rel not in neighbors and rel not in paths:
                    neighbors.append(rel)
    return {"paths": paths, "neighbors": neighbors[:30]}


def tool_get_file_history(arguments: dict) -> dict:
    path = _normalize_path(str(arguments.get("path", "")).strip())
    limit = int(arguments.get("limit", 10) or 10)
    if not path:
        return {"path": "", "history": []}
    output = run_git("log", f"-n{limit}", "--pretty=format:%h %ad %an %s", "--date=short", "--", path, check=False)
    return {"path": path, "history": [line.strip() for line in output.splitlines() if line.strip()]}


def tool_get_recent_commits(arguments: dict) -> dict:
    limit = int(arguments.get("limit", 20) or 20)
    output = run_git("log", f"-n{limit}", "--pretty=format:%h %ad %an %s", "--date=short", check=False)
    return {"commits": [line.strip() for line in output.splitlines() if line.strip()]}


def tool_get_blame_summary(arguments: dict) -> dict:
    path = _normalize_path(str(arguments.get("path", "")).strip())
    target = _existing_file(path)
    if not target:
        return {"path": path, "summary": []}
    result = run_command(["git", "blame", "--line-porcelain", path], cwd=REPO_ROOT, check=False)
    authors: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if line.startswith("author "):
            author = line[7:].strip()
            authors[author] = authors.get(author, 0) + 1
    summary = [{"author": name, "lines": count} for name, count in sorted(authors.items(), key=lambda item: item[1], reverse=True)[:10]]
    return {"path": path, "summary": summary}


def tool_get_related_commit_messages(arguments: dict) -> dict:
    paths = [_normalize_path(item) for item in arguments.get("paths", []) if str(item).strip()]
    limit = int(arguments.get("limit", 20) or 20)
    messages: list[str] = []
    for path in paths:
        output = run_git("log", f"-n{limit}", "--pretty=format:%h %s", "--", path, check=False)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped and stripped not in messages:
                messages.append(stripped)
    return {"paths": paths, "messages": messages[:limit]}


def tool_get_recent_repo_issues(arguments: dict) -> dict:
    days = int(arguments.get("days", env_int("AI_REVIEW_MCP_ISSUE_LOOKBACK_DAYS", 30)) or 30)
    labels = arguments.get("labels") or ["ai-review", "ai-audit", "bug", "incident", "security"]
    issues = list_repo_issues(state="all", labels=labels[:5], per_page=50)
    return {
        "issues": [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
                "updated_at": item.get("updated_at"),
                "labels": [label.get("name") for label in item.get("labels", []) if isinstance(label, dict)],
            }
            for item in issues[:days]
        ]
    }


def tool_get_recent_related_issues(arguments: dict) -> dict:
    paths = [_normalize_path(item) for item in arguments.get("paths", []) if str(item).strip()]
    days = int(arguments.get("days", env_int("AI_REVIEW_MCP_ISSUE_LOOKBACK_DAYS", 30)) or 30)
    labels = ["ai-review", "ai-audit", "bug", "incident", "security"]
    issues = list_repo_issues(state="all", per_page=100)
    keywords = []
    for path in paths:
        keywords.extend(_module_keywords(path))
    related = []
    for item in issues:
        title = str(item.get("title", "")).lower()
        body = str(item.get("body", "")).lower()
        issue_labels = [label.get("name", "").lower() for label in item.get("labels", []) if isinstance(label, dict)]
        if not any(label in issue_labels for label in labels):
            continue
        if any(path.lower() in body for path in paths) or any(keyword and (keyword in title or keyword in body) for keyword in keywords):
            related.append(
                {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "state": item.get("state"),
                    "updated_at": item.get("updated_at"),
                    "labels": issue_labels,
                }
            )
    return {"paths": paths, "issues": related[:days]}


def tool_get_recent_repo_prs(arguments: dict) -> dict:
    limit = int(arguments.get("limit", env_int("AI_REVIEW_MCP_PR_LOOKBACK_DAYS", 30)) or 30)
    pulls = list_repo_pulls(state="all", per_page=50)
    return {
        "pulls": [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
                "updated_at": item.get("updated_at"),
                "head": item.get("head", {}).get("ref"),
                "base": item.get("base", {}).get("ref"),
            }
            for item in pulls[:limit]
        ]
    }


def tool_get_commit_checks(arguments: dict) -> dict:
    ref = str(arguments.get("ref", "")).strip() or "HEAD"
    runs = list_commit_check_runs(ref)
    return {
        "ref": ref,
        "checks": [
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "started_at": item.get("started_at"),
                "completed_at": item.get("completed_at"),
            }
            for item in runs
        ],
    }


def tool_get_recent_failed_runs(arguments: dict) -> dict:
    limit = int(arguments.get("limit", 20) or 20)
    runs = list_workflow_runs(per_page=50)
    failed = []
    for item in runs:
        if item.get("conclusion") not in {"failure", "timed_out", "cancelled", "action_required"}:
            continue
        failed.append(
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "head_branch": item.get("head_branch"),
                "event": item.get("event"),
                "created_at": item.get("created_at"),
                "html_url": item.get("html_url"),
            }
        )
        if len(failed) >= limit:
            break
    return {"runs": failed}


TOOLS = {
    "get_changed_files": tool_get_changed_files,
    "get_diff_patch": tool_get_diff_patch,
    "get_file_content": tool_get_file_content,
    "get_related_files": tool_get_related_files,
    "get_symbol_references": tool_get_symbol_references,
    "get_import_dependents": tool_get_import_dependents,
    "get_config_neighbors": tool_get_config_neighbors,
    "get_file_history": tool_get_file_history,
    "get_recent_commits": tool_get_recent_commits,
    "get_blame_summary": tool_get_blame_summary,
    "get_related_commit_messages": tool_get_related_commit_messages,
    "get_recent_repo_issues": tool_get_recent_repo_issues,
    "get_recent_related_issues": tool_get_recent_related_issues,
    "get_recent_repo_prs": tool_get_recent_repo_prs,
    "get_commit_checks": tool_get_commit_checks,
    "get_recent_failed_runs": tool_get_recent_failed_runs,
}


TOOL_DESCRIPTIONS = [
    _tool("get_changed_files", "List changed files between two refs.", {"type": "object", "properties": {"base_sha": {"type": "string"}, "head_sha": {"type": "string"}}}),
    _tool("get_diff_patch", "Return a diff patch for paths.", {"type": "object", "properties": {"base_sha": {"type": "string"}, "head_sha": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}}}),
    _tool("get_file_content", "Read one file.", {"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}}}),
    _tool("get_related_files", "Find nearby and dependency-related files.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}}),
    _tool("get_symbol_references", "Search references for a symbol.", {"type": "object", "properties": {"symbol": {"type": "string"}}}),
    _tool("get_import_dependents", "Find files importing or mentioning a module.", {"type": "object", "properties": {"path": {"type": "string"}}}),
    _tool("get_config_neighbors", "Find nearby docs/config/workflow files.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}}}),
    _tool("get_file_history", "Get recent git history for a file.", {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}}),
    _tool("get_recent_commits", "Get recent commits.", {"type": "object", "properties": {"limit": {"type": "integer"}}}),
    _tool("get_blame_summary", "Get git blame author summary for a file.", {"type": "object", "properties": {"path": {"type": "string"}}}),
    _tool("get_related_commit_messages", "Get recent commit messages for files.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}}),
    _tool("get_recent_repo_issues", "List repository issues.", {"type": "object", "properties": {"days": {"type": "integer"}, "labels": {"type": "array", "items": {"type": "string"}}}}),
    _tool("get_recent_related_issues", "Find issues related to changed files.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "days": {"type": "integer"}}}),
    _tool("get_recent_repo_prs", "List recent pull requests.", {"type": "object", "properties": {"limit": {"type": "integer"}}}),
    _tool("get_commit_checks", "List check runs for a commit.", {"type": "object", "properties": {"ref": {"type": "string"}}}),
    _tool("get_recent_failed_runs", "List failed workflow runs.", {"type": "object", "properties": {"limit": {"type": "integer"}}}),
]


def _handle(request: dict) -> dict | None:
    method = request.get("method")
    msg_id = request.get("id")
    if method == "initialize":
        return _response(msg_id, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "ctp-aicr-mcp", "version": "1.0.0"}, "capabilities": {"tools": {}}})
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _response(msg_id, {"tools": TOOL_DESCRIPTIONS})
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOLS.get(str(name))
        if not handler:
            return _error(msg_id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(arguments)
            return _response(msg_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result})
        except Exception as exc:
            return _error(msg_id, -32000, short_exc(exc))
    return _error(msg_id, -32601, f"Unknown method: {method}")


def main() -> None:
    while True:
        request = _read_message()
        if request is None:
            break
        response = _handle(request)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
