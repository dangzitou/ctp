#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .common import write_summary


COMMENT_MARKER = "<!-- ai-commit-review -->"
ISSUE_MARKER = "<!-- ai-repo-audit -->"
REVIEW_ISSUE_MARKER = "<!-- ai-review-inbox -->"
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
        parts.append(f"Required permissions: `\`{accepted}\`\`.")
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


def _fetch_all_open_issues(url_template: str, per_page: int = 100) -> list:
    """Fetch all open issues with pagination support."""
    all_issues = []
    page = 1
    while True:
        url = f"{url_template}&page={page}&per_page={per_page}"
        issues = github_request("GET", url)
        if not isinstance(issues, list) or not issues:
            break
        all_issues.extend(issues)
        if len(issues) < per_page:
            break
        page += 1
    return all_issues


def _fetch_paginated(url_template: str, per_page: int = 100, page_limit: int = 5) -> list:
    items = []
    page = 1
    while page <= page_limit:
        separator = "&" if "?" in url_template else "?"
        url = f"{url_template}{separator}page={page}&per_page={per_page}"
        payload = github_request("GET", url)
        if not isinstance(payload, list) or not payload:
            break
        items.extend(payload)
        if len(payload) < per_page:
            break
        page += 1
    return items


def upsert_audit_issue(title: str, body_content: str, labels: list[str]) -> None:
    body = f"{ISSUE_MARKER}\n# {title}\n\n{body_content}"
    issues_url = repo_api_url("/issues?state=open")
    issues = _fetch_all_open_issues(issues_url)
    if isinstance(issues, list):
        for issue in issues:
            current = issue.get("body", "")
            issue_labels = [label.get("name") for label in issue.get("labels", [])]
            if ISSUE_MARKER in current or (issue.get("title") == title and all(label in issue_labels for label in labels)):
                github_request("PATCH", issue["url"], {"title": title, "body": body, "labels": labels})
                return
    github_request("POST", repo_api_url("/issues"), {"title": title, "body": body, "labels": labels})


def upsert_review_issue(title: str, body_content: str, labels: list[str]) -> None:
    body = f"{REVIEW_ISSUE_MARKER}\n# {title}\n\n{body_content}"
    issues_url = repo_api_url("/issues?state=open")
    issues = _fetch_all_open_issues(issues_url)
    if isinstance(issues, list):
        for issue in issues:
            current = issue.get("body", "")
            issue_labels = [label.get("name") for label in issue.get("labels", [])]
            if REVIEW_ISSUE_MARKER in current or (issue.get("title") == title and all(label in issue_labels for label in labels)):
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
    data = github_graphql_request(query, {"pullRequestId": pr_node_id, "mergeMethod": merge_method})
    mutation_result = data.get("enablePullRequestAutoMerge")
    if not mutation_result:
        raise RuntimeError("GitHub GraphQL enablePullRequestAutoMerge response missing data.")
    pull_request = mutation_result.get("pullRequest")
    if not pull_request:
        raise RuntimeError("GitHub GraphQL enablePullRequestAutoMerge response missing pullRequest.")
    return mutation_result


def list_repo_issues(state: str = "all", labels: list[str] | None = None, since: str | None = None, per_page: int = 50) -> list[dict]:
    query = [f"state={state}"]
    if labels:
        query.append("labels=" + ",".join(labels))
    if since:
        query.append(f"since={since}")
    issues = _fetch_paginated(repo_api_url("/issues?" + "&".join(query)), per_page=per_page)
    return [item for item in issues if "pull_request" not in item]


def list_repo_pulls(state: str = "all", per_page: int = 50) -> list[dict]:
    return _fetch_paginated(repo_api_url(f"/pulls?state={state}"), per_page=per_page)


def list_commit_check_runs(ref: str) -> list[dict]:
    response = github_request("GET", repo_api_url(f"/commits/{ref}/check-runs"))
    if not isinstance(response, dict):
        return []
    runs = response.get("check_runs")
    return runs if isinstance(runs, list) else []


def list_workflow_runs(status: str | None = None, per_page: int = 30) -> list[dict]:
    url = repo_api_url("/actions/runs")
    if status:
        url += f"?status={status}"
    response = github_request("GET", f"{url}{'&' if '?' in url else '?'}per_page={per_page}")
    if not isinstance(response, dict):
        return []
    runs = response.get("workflow_runs")
    return runs if isinstance(runs, list) else []
