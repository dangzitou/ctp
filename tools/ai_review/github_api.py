#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .common import write_summary


COMMENT_MARKER = "<!-- ai-commit-review -->"
ISSUE_MARKER = "<!-- ai-repo-audit -->"


def github_request(method: str, url: str, payload: dict | None = None) -> dict | list:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("`GITHUB_TOKEN` is missing.")

    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ctp-ai-automation",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset)
        return json.loads(body) if body else {}


def repo_api_url(path: str) -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repo:
        raise RuntimeError("`GITHUB_REPOSITORY` is missing.")
    return f"{api_base}/repos/{repo}{path}"


def upsert_commit_comment(review_body: str, head_sha: str) -> None:
    comments_url = repo_api_url(f"/commits/{head_sha}/comments")
    body = f"{COMMENT_MARKER}\n# AI Code Review\n\n{review_body}"

    try:
        existing = github_request("GET", comments_url)
        if isinstance(existing, list):
            for comment in existing:
                if COMMENT_MARKER in comment.get("body", "") and comment.get("url"):
                    github_request("PATCH", comment["url"], {"body": body})
                    return
        github_request("POST", comments_url, {"body": body})
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        write_summary(f"Commit comment publish failed: HTTP {exc.code}\n\n```\n{details}\n```")


def ensure_label(name: str, color: str, description: str) -> None:
    try:
        github_request("POST", repo_api_url("/labels"), {"name": name, "color": color, "description": description})
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise


def upsert_audit_issue(title: str, body_content: str, labels: list[str]) -> None:
    body = f"{ISSUE_MARKER}\n# {title}\n\n{body_content}"
    issues_url = repo_api_url("/issues?state=open&per_page=100")
    issues = github_request("GET", issues_url)
    if isinstance(issues, list):
        for issue in issues:
            current = issue.get("body", "")
            issue_labels = [label.get("name") for label in issue.get("labels", [])]
            if ISSUE_MARKER in current or (issue.get("title") == title and all(label in issue_labels for label in labels)):
                github_request("PATCH", issue["url"], {"title": title, "body": body, "labels": labels})
                return
    github_request("POST", repo_api_url("/issues"), {"title": title, "body": body, "labels": labels})
