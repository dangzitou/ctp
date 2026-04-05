#!/usr/bin/env python3
"""Build MCP-backed context bundles for review and repo audit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .common import env_bool, env_int, ensure_parent, main_cli_error, read_json, write_json
from .mcp_client import McpClient, ToolCallRecord, default_repo_mcp_command, minimax_mcp_command
from .policy import assess_paths


def _bundle_base(kind: str, payload: dict) -> dict:
    return {
        "type": kind,
        "repository": payload.get("repository", os.getenv("GITHUB_REPOSITORY", "unknown")),
        "base_sha": payload.get("base_sha", ""),
        "head_sha": payload.get("head_sha", ""),
        "mcp_enabled": env_bool("AI_REVIEW_ENABLE_MCP", True),
        "mcp_mode": os.getenv("AI_REVIEW_MCP_MODE", "prefetch").strip() or "prefetch",
        "mcp_sources": [],
        "mcp_tool_calls": [],
        "context_bundle_size": 0,
        "external_search_used": False,
        "degraded": False,
        "degraded_reasons": [],
    }


def _record(calls: list[dict], record: ToolCallRecord) -> None:
    calls.append({"server": record.server, "tool": record.tool, "ok": record.ok, "detail": record.detail})


def _safe_call(client: McpClient, server_name: str, tool_name: str, arguments: dict, calls: list[dict], default: dict | None = None) -> dict:
    try:
        result = client.call_tool(tool_name, arguments)
        _record(calls, ToolCallRecord(server_name, tool_name, True))
        return result
    except Exception as exc:
        _record(calls, ToolCallRecord(server_name, tool_name, False, str(exc)))
        return default or {}


def _finalize_degraded(bundle: dict) -> None:
    failures = [item for item in bundle.get("mcp_tool_calls", []) if not item.get("ok")]
    if failures:
        bundle["degraded"] = True
        details = [f"{item.get('server')}:{item.get('tool')} -> {item.get('detail', '')}".strip() for item in failures[:10]]
        bundle["degraded_reasons"] = list(dict.fromkeys(bundle.get("degraded_reasons", []) + details))


def _search_queries(paths: list[str]) -> list[str]:
    queries = []
    for path in paths[:3]:
        stem = Path(path).stem
        if stem:
            queries.append(f"{stem} github actions runtime issue")
    if not queries:
        queries.append("github actions code review runtime issue")
    return queries[:2]


def _prepare_push_context(payload: dict) -> dict:
    bundle = _bundle_base("push_review_context", payload)
    changed_files = list(payload.get("included_files", []))
    assessment = assess_paths(changed_files)
    calls = bundle["mcp_tool_calls"]
    limit = env_int("AI_REVIEW_MCP_RELATED_FILE_LIMIT", 12)
    issue_days = env_int("AI_REVIEW_MCP_ISSUE_LOOKBACK_DAYS", 30)
    pr_limit = env_int("AI_REVIEW_MCP_PR_LOOKBACK_DAYS", 30)

    repo_token = os.getenv("AI_REVIEW_GH_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
    repo_client = McpClient(default_repo_mcp_command(), "repo-local", {"GITHUB_TOKEN": repo_token})
    try:
        bundle["mcp_sources"].append("repo-local")
        related = _safe_call(repo_client, "repo-local", "get_related_files", {"paths": changed_files, "limit": limit}, calls, {"related_files": []})
        neighbors = _safe_call(repo_client, "repo-local", "get_config_neighbors", {"paths": changed_files}, calls, {"neighbors": []})
        file_histories = [
            _safe_call(repo_client, "repo-local", "get_file_history", {"path": path, "limit": 8}, calls, {"path": path, "history": []})
            for path in changed_files[:5]
        ]
        related_commits = _safe_call(repo_client, "repo-local", "get_related_commit_messages", {"paths": changed_files, "limit": 20}, calls, {"messages": []})
        checks = _safe_call(repo_client, "repo-local", "get_commit_checks", {"ref": payload.get("head_sha", "HEAD")}, calls, {"checks": []})
        failed_runs = _safe_call(repo_client, "repo-local", "get_recent_failed_runs", {"limit": 10}, calls, {"runs": []})
        related_issues = _safe_call(repo_client, "repo-local", "get_recent_related_issues", {"paths": changed_files, "days": issue_days}, calls, {"issues": []})
        related_prs = _safe_call(repo_client, "repo-local", "get_recent_repo_prs", {"limit": pr_limit}, calls, {"pulls": []})
        symbol_refs = []
        import_dependents = []
        for path in changed_files[:4]:
            stem = Path(path).stem
            if stem:
                symbol_refs.append(_safe_call(repo_client, "repo-local", "get_symbol_references", {"symbol": stem}, calls, {"symbol": stem, "matches": []}))
            import_dependents.append(_safe_call(repo_client, "repo-local", "get_import_dependents", {"path": path}, calls, {"path": path, "dependents": []}))
    finally:
        repo_client.close()

    external_search = []
    if env_bool("AI_REVIEW_MCP_ENABLE_WEB_SEARCH", True):
        try:
            minimax_client = McpClient(minimax_mcp_command(), "minimax-mcp", {"MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""), "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "")})
            try:
                bundle["mcp_sources"].append("minimax-mcp")
                for query in _search_queries(changed_files):
                    result = _safe_call(minimax_client, "minimax-mcp", "web_search", {"query": query}, calls, {"results": []})
                    if result:
                        bundle["external_search_used"] = True
                        external_search.append({"query": query, "result": result})
            finally:
                minimax_client.close()
        except Exception as exc:
            bundle["degraded"] = True
            bundle["degraded_reasons"].append(f"minimax-mcp unavailable: {exc}")

    bundle.update(
        {
            "changed_files": changed_files,
            "impacted_files": list(dict.fromkeys((related.get("related_files") or []) + [item for obj in import_dependents for item in obj.get("dependents", [])]))[:limit],
            "related_files": related.get("related_files", []),
            "related_configs": neighbors.get("neighbors", []),
            "related_histories": file_histories,
            "related_commit_messages": related_commits.get("messages", []),
            "related_issues": related_issues.get("issues", []),
            "related_prs": related_prs.get("pulls", []),
            "recent_failed_runs": failed_runs.get("runs", []),
            "commit_checks": checks.get("checks", []),
            "symbol_references": symbol_refs,
            "import_dependents": import_dependents,
            "external_search": external_search,
            "policy_assessment": assessment,
        }
    )
    _finalize_degraded(bundle)
    bundle["context_bundle_size"] = len(json.dumps(bundle, ensure_ascii=False))
    return bundle


def _prepare_audit_context(payload: dict) -> dict:
    bundle = _bundle_base("repo_audit_context", payload)
    included_files = list(payload.get("included_files", []))
    calls = bundle["mcp_tool_calls"]
    issue_days = env_int("AI_REVIEW_MCP_ISSUE_LOOKBACK_DAYS", 30)
    pr_limit = env_int("AI_REVIEW_MCP_PR_LOOKBACK_DAYS", 30)

    repo_token = os.getenv("AI_REVIEW_GH_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
    repo_client = McpClient(default_repo_mcp_command(), "repo-local", {"GITHUB_TOKEN": repo_token})
    try:
        bundle["mcp_sources"].append("repo-local")
        commits = _safe_call(repo_client, "repo-local", "get_recent_commits", {"limit": 20}, calls, {"commits": []})
        issues = _safe_call(repo_client, "repo-local", "get_recent_repo_issues", {"days": issue_days}, calls, {"issues": []})
        prs = _safe_call(repo_client, "repo-local", "get_recent_repo_prs", {"limit": pr_limit}, calls, {"pulls": []})
        failed_runs = _safe_call(repo_client, "repo-local", "get_recent_failed_runs", {"limit": 10}, calls, {"runs": []})
        config_neighbors = _safe_call(repo_client, "repo-local", "get_config_neighbors", {"paths": included_files[:8]}, calls, {"neighbors": []})
        file_histories = [
            _safe_call(repo_client, "repo-local", "get_file_history", {"path": path, "limit": 5}, calls, {"path": path, "history": []})
            for path in included_files[:8]
        ]
    finally:
        repo_client.close()

    external_search = []
    if env_bool("AI_REVIEW_MCP_ENABLE_WEB_SEARCH", True):
        try:
            minimax_client = McpClient(minimax_mcp_command(), "minimax-mcp", {"MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""), "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "")})
            try:
                bundle["mcp_sources"].append("minimax-mcp")
                result = _safe_call(minimax_client, "minimax-mcp", "web_search", {"query": "GitHub Actions code review audit workflow best practices"}, calls, {"results": []})
                if result:
                    bundle["external_search_used"] = True
                    external_search.append(result)
            finally:
                minimax_client.close()
        except Exception as exc:
            bundle["degraded"] = True
            bundle["degraded_reasons"].append(f"minimax-mcp unavailable: {exc}")

    bundle.update(
        {
            "recent_commits": commits.get("commits", []),
            "recent_issues": issues.get("issues", []),
            "related_prs": prs.get("pulls", []),
            "recent_failed_runs": failed_runs.get("runs", []),
            "related_configs": config_neighbors.get("neighbors", []),
            "related_histories": file_histories,
            "external_search": external_search,
            "included_files": included_files,
        }
    )
    _finalize_degraded(bundle)
    bundle["context_bundle_size"] = len(json.dumps(bundle, ensure_ascii=False))
    return bundle


def build_context(kind: str, input_path: str, output_path: str) -> None:
    payload = read_json(input_path)
    enabled = env_bool("AI_REVIEW_ENABLE_MCP", True)
    if not enabled:
        bundle = _bundle_base(kind, payload)
        bundle["degraded"] = True
        bundle["degraded_reasons"].append("AI_REVIEW_ENABLE_MCP disabled MCP collection.")
    elif kind == "review":
        bundle = _prepare_push_context(payload)
    else:
        bundle = _prepare_audit_context(payload)
    ensure_parent(output_path)
    write_json(output_path, bundle)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    review = sub.add_parser("review")
    review.add_argument("--input", required=True)
    review.add_argument("--output", required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("--input", required=True)
    audit.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.cmd == "review":
        build_context("review", args.input, args.output)
    else:
        build_context("audit", args.input, args.output)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
