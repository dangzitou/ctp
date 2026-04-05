#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .common import write_summary


COMMENT_MARKER = "<!-- ai-commit-review -->"
ISSUE_MARKER = "<!-- ai-repo-audit -->"
FIX_PR_MARKER = "<!-- ai-auto-fix-pr -->"


class GitHubApiError(RuntimeError):
    def __init__(self, code: int, message: str, body: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.body = body


def _http_error_details(exc: urllib.error.HTTPError) -> GitHubApiError:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    accepted = exc.headers.get("x-accepted-github-permissions", "").strip()
    api_message = ""
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        api_message = str(payload.get("message", "")).strip()

    parts = [f"GitHub API request failed with HTTP {exc.code}: {exc.reason}."]
    if api_message:
        parts.append(api_message)
    elif body:
        parts.append(f"Response: {body}")
    if accepted:
        parts.append(f"Required permissions: `{accepted}`.")
    if exc.code == 403 and api_message == "Resource not accessible by personal access token":
        parts.append(
            "The current token cannot create pull requests. "
            "Configure repository secret `AI_REVIEW_GH_TOKEN` with `Pull requests: Read and write`, "
            "or enable GitHub Actions to create pull requests for `GITHUB_TOKEN`."
        )
    return GitHubApiError(exc.code, " ".join(parts), body)


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
    try:
        with urllib.request.urlopen(request) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset)
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise _http_error_details(exc) from exc


def github_graphql_request(query: str, variables: dict | None = None) -> dict:
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    graphql_url = f"{api_base}/graphql"
    response = github_request("POST", graphql_url, {"query": query, "variables": variables or {}})
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected GitHub GraphQL response type.")
    errors = response.get("errors") or []
    if errors:
        messages = [str(item.get("message", "unknown GraphQL error")) for item in errors if isinstance(item, dict)]
        raise RuntimeError("; ".join(messages) or "GitHub GraphQL request failed.")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("GitHub GraphQL response missing `data`.")
    return data


def repo_api_url(path: str) -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repo:
        raise RuntimeError("`GITHUB_REPOSITORY` is missing.")
    return f"{api_base}/repos/{repo}{path}"


def repo_html_url(path: str = "") -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if not repo:
        raise RuntimeError("`GITHUB_REPOSITORY` is missing.")
    return f"{server_url}/{repo}{path}"


def compare_url(base: str, head: str) -> str:
    return repo_html_url(f"/compare/{base}...{head}?expand=1")


def pr_url(pr_number: int) -> str:
    return repo_html_url(f"/pull/{pr_number}")


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
    except GitHubApiError as exc:
        detail = f"\n\n```\n{exc.body}\n```" if exc.body else ""
        write_summary(f"Commit comment publish failed.\n\n```\n{exc}\n```{detail}")


def ensure_label(name: str, color: str, description: str) -> None:
    try:
        github_request("POST", repo_api_url("/labels"), {"name": name, "color": color, "description": description})
    except GitHubApiError as exc:
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


def upsert_pull_request(title: str, body_content: str, head: str, base: str, labels: list[str] | None = None) -> dict:
    pulls_url = repo_api_url("/pulls?state=open&per_page=100")
    body = f"{FIX_PR_MARKER}\n{body_content}"
    pulls = github_request("GET", pulls_url)
    if isinstance(pulls, list):
        for pr in pulls:
            if pr.get("head", {}).get("ref") == head and pr.get("base", {}).get("ref") == base:
                updated = github_request("PATCH", pr["url"], {"title": title, "body": body, "base": base})
                if labels:
                    github_request("PATCH", repo_api_url(f"/issues/{pr['number']}"), {"labels": labels})
                return updated
    created = github_request("POST", repo_api_url("/pulls"), {"title": title, "body": body, "head": head, "base": base})
    if labels and created.get("number"):
        github_request("PATCH", repo_api_url(f"/issues/{created['number']}"), {"labels": labels})
    return created


def merge_pull_request(pr_number: int, merge_method: str = "squash") -> dict:
    return github_request("PUT", repo_api_url(f"/pulls/{pr_number}/merge"), {"merge_method": merge_method})


def enable_pull_request_auto_merge(pr_node_id: str, merge_method: str = "SQUASH") -> dict:
    query = """
    mutation EnableAutoMerge($pullRequestId: ID!, $mergeMethod: PullRequestMergeMethod!) {
      enablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId, mergeMethod: $mergeMethod}) {
        pullRequest {
          number
          autoMergeRequest {
            enabledAt
          }
        }
      }
    }
    """
    return github_graphql_request(query, {"pullRequestId": pr_node_id, "mergeMethod": merge_method})
