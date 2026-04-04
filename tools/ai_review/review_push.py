#!/usr/bin/env python3
"""Review push diffs with OpenAI and publish a commit comment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from openai import OpenAI


EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
COMMENT_MARKER = "<!-- ai-commit-review -->"
MAX_FILES = int(os.getenv("AI_REVIEW_MAX_FILES", "12") or "12")
MAX_PATCH_CHARS = int(os.getenv("AI_REVIEW_MAX_PATCH_CHARS", "60000") or "60000")
MODEL = os.getenv("OPENAI_MODEL", "").strip() or "gpt-5-mini"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = os.getenv("GITHUB_STEP_SUMMARY", "")

TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
EXCLUDED_PREFIXES = (
    "openctp/",
    "ctpapi_python_6.7.11/",
    "tts_6.7.11/",
    "tap_6.7.2/",
    "docker_ctp/dashboard/target/",
    "java_ctp_md/target/",
)
EXCLUDED_SUFFIXES = (
    ".class",
    ".con",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyd",
    ".so",
    ".zip",
)


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_summary(text: str) -> None:
    if not SUMMARY_PATH:
        return
    with open(SUMMARY_PATH, "a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


def fail(message: str) -> None:
    write_summary(f"## AI code review\n\n{message}")
    raise SystemExit(message)


def load_event() -> dict:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
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


def should_review(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if any(normalized.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    name = Path(normalized).name
    if normalized.startswith(".github/"):
        return True
    if name == "README.md":
        return True
    if name.startswith("."):
        return normalized.endswith((".yml", ".yaml", ".json"))
    return Path(normalized).suffix.lower() in TEXT_EXTENSIONS


def collect_changed_files(base_sha: str, head_sha: str) -> list[str]:
    output = run_git("diff", "--name-only", base_sha, head_sha)
    files = [line.strip() for line in output.splitlines() if line.strip()]
    return [path for path in files if should_review(path)]


def collect_diff(base_sha: str, head_sha: str, files: list[str]) -> tuple[str, list[str], int]:
    included: list[str] = []
    patches: list[str] = []
    skipped = 0
    current_size = 0

    for path in files:
        if len(included) >= MAX_FILES:
            skipped += 1
            continue
        patch = run_git("diff", "--unified=3", "--no-color", base_sha, head_sha, "--", path)
        if not patch:
            continue
        patch_block = f"\n### {path}\n```diff\n{patch}\n```\n"
        if current_size + len(patch_block) > MAX_PATCH_CHARS:
            skipped += 1
            continue
        included.append(path)
        patches.append(patch_block)
        current_size += len(patch_block)

    return "".join(patches).strip(), included, skipped


def build_prompt(base_sha: str, head_sha: str, included_files: list[str], skipped_files: int, diff_text: str) -> str:
    file_list = "\n".join(f"- {path}" for path in included_files)
    skipped_note = ""
    if skipped_files:
        skipped_note = f"\nAdditional changed files skipped because of size limits: {skipped_files}\n"

    return textwrap.dedent(
        f"""
        Repository: {os.getenv("GITHUB_REPOSITORY", "unknown")}
        Base commit: {base_sha}
        Head commit: {head_sha}

        You are reviewing a push in a mixed Python/Java/CTP integration repository.
        Focus on bugs, regressions, data-flow breakage, security issues, flaky runtime assumptions, and missing tests.
        Use a pragmatic code-review style inspired by PR-Agent: findings first, ordered by severity, with concrete fixes.
        Ignore cosmetic nits unless they hide a real risk.

        Files included in this review:
        {file_list or "- none"}{skipped_note}

        Return Markdown in this exact shape:
        ## Verdict
        One short paragraph.

        ## Findings
        - If there are issues, use bullets in the format:
          [severity] path - problem, impact, suggested fix
        - If there are no meaningful issues, write exactly:
          - No major issues detected in the reviewed diff.

        ## Test Gaps
        - Mention the most important missing verification, or say:
          - No critical additional tests identified from this diff.

        Diff:
        {diff_text}
        """
    ).strip()


def request_review(prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        fail("`OPENAI_API_KEY` is missing. Add it as a repository secret before using this workflow.")

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=MODEL,
        reasoning={"effort": "medium"},
        input=[
            {
                "role": "system",
                "content": (
                    "You are a senior code reviewer. Be concise, accurate, and actionable. "
                    "Do not invent issues. Prefer high-signal findings."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    review = (response.output_text or "").strip()
    if not review:
        fail("The OpenAI review response was empty.")
    return review


def github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ctp-ai-review-workflow",
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


def upsert_commit_comment(review_body: str, head_sha: str) -> None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        write_summary("GitHub comment publishing skipped because `GITHUB_TOKEN` or `GITHUB_REPOSITORY` is missing.")
        return

    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    comments_url = f"{api_base}/repos/{repo}/commits/{head_sha}/comments"
    body = f"{COMMENT_MARKER}\n# AI Code Review\n\n{review_body}"

    try:
        existing = github_request("GET", comments_url, token)
        if isinstance(existing, list):
            for comment in existing:
                comment_body = comment.get("body", "")
                if COMMENT_MARKER in comment_body:
                    comment_url = comment.get("url")
                    if comment_url:
                        github_request("PATCH", comment_url, token, {"body": body})
                        return
        github_request("POST", comments_url, token, {"body": body})
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        write_summary(f"GitHub comment publish failed: HTTP {exc.code}\n\n```\n{details}\n```")


def main() -> None:
    head_sha = os.getenv("GITHUB_SHA", "").strip() or run_git("rev-parse", "HEAD")
    event = load_event()
    base_sha = resolve_base_sha(event, head_sha)

    files = collect_changed_files(base_sha, head_sha)
    if not files:
        message = "No reviewable source or documentation changes were detected in this push."
        write_summary(f"## AI code review\n\n{message}")
        print(message)
        return

    diff_text, included_files, skipped_files = collect_diff(base_sha, head_sha, files)
    if not diff_text:
        message = "Reviewable files changed, but the diff payload was empty after size filtering."
        write_summary(f"## AI code review\n\n{message}")
        print(message)
        return

    prompt = build_prompt(base_sha, head_sha, included_files, skipped_files, diff_text)
    review = request_review(prompt)
    write_summary(f"## AI code review\n\nReviewed model: `{MODEL}`\n\n{review}")
    upsert_commit_comment(review, head_sha)
    print(review)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - GitHub Actions entry point
        write_summary(f"## AI code review\n\nWorkflow failed: `{exc}`")
        raise
