#!/usr/bin/env python3
"""Minimal MCP stdio client for AICR context collection."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass


def _write_message(stdin, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stdin.write(header)
    stdin.write(body)
    stdin.flush()


def _read_message(stdout) -> dict:
    headers: dict[str, str] = {}
    while True:
        line = stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout.")
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or "0")
    if length <= 0:
        raise RuntimeError("Invalid MCP content-length.")
    body = stdout.read(length)
    if not body:
        raise RuntimeError("MCP server returned empty body.")
    return json.loads(body.decode("utf-8"))


@dataclass
class ToolCallRecord:
    server: str
    tool: str
    ok: bool
    detail: str = ""


class McpClient:
    def __init__(self, command: list[str], server_name: str, extra_env: dict[str, str] | None = None) -> None:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        self.server_name = server_name
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError(f"Failed to start MCP server: {server_name}")
        self._id = 0
        self._initialize()

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        _write_message(self.process.stdin, payload)
        response = _read_message(self.process.stdout)
        error = response.get("error")
        if error:
            raise RuntimeError(str(error.get("message", "Unknown MCP error")))
        return response.get("result") or {}

    def _notify(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        _write_message(self.process.stdin, payload)

    def _initialize(self) -> None:
        self._request("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "ctp-aicr", "version": "1.0.0"}, "capabilities": {}})
        self._notify("notifications/initialized")

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list")
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content") or []
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "{}")
                return json.loads(text)
        return {}

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.terminate()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


def default_repo_mcp_command() -> list[str]:
    return [sys.executable, "-m", "tools.ai_review.mcp_server"]


def minimax_mcp_command() -> list[str]:
    raw = os.getenv("AI_REVIEW_MINIMAX_MCP_CMD", "").strip()
    if raw:
        return shlex.split(raw)
    return ["uvx", "minimax-coding-plan-mcp"]
