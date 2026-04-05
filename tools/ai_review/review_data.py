#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from .common import env_int, run_git
from .policy import should_auto_fix_path, should_review_path


TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js", ".json",
    ".md", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt",
    ".xml", ".yaml", ".yml",
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
    ".class", ".con", ".dll", ".dylib", ".exe", ".gif", ".jar", ".jpeg", ".jpg",
    ".pdf", ".png", ".pyd", ".so", ".zip",
)


def should_review(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not normalized:
        return False
    if not should_review_path(normalized):
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
        return normalized.endswith((".yml", ".yaml", ".json", ".toml"))
    return Path(normalized).suffix.lower() in TEXT_EXTENSIONS


def should_auto_fix(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not should_review(normalized):
        return False
    return should_auto_fix_path(normalized)


def collect_changed_files(base_sha: str, head_sha: str) -> list[str]:
    output = run_git("diff", "--name-only", base_sha, head_sha)
    files = [line.strip() for line in output.splitlines() if line.strip()]
    return [path for path in files if should_review(path)]


def collect_diff(base_sha: str, head_sha: str, files: list[str]) -> tuple[str, list[str], int]:
    max_files = env_int("AI_REVIEW_MAX_FILES", 12)
    max_patch_chars = env_int("AI_REVIEW_MAX_PATCH_CHARS", 60000)
    included: list[str] = []
    patches: list[str] = []
    skipped = 0
    current_size = 0

    for path in files:
        if len(included) >= max_files:
            skipped += 1
            continue
        patch = run_git("diff", "--unified=3", "--no-color", base_sha, head_sha, "--", path)
        if not patch:
            continue
        patch_block = f"\n### {path}\n```diff\n{patch}\n```\n"
        if current_size + len(patch_block) > max_patch_chars:
            skipped += 1
            continue
        included.append(path)
        patches.append(patch_block)
        current_size += len(patch_block)

    return "".join(patches).strip(), included, skipped


def read_file_excerpt(path: str, max_chars: int = 7000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(max_chars + 1)
    except OSError:
        return ""
    if len(content) > max_chars:
        return content[:max_chars] + "\n...[truncated]"
    return content


def collect_repo_snapshot() -> dict:
    interesting = [
        ".github/workflows/ai-code-review.yml",
        ".github/workflows/ai-repo-audit.yml",
        "README.md",
        "docs/AI_REVIEW_WORKFLOW.md",
        "docs/HA_DEPLOYMENT.md",
        "docker_ctp/docker-compose.yml",
        "docker_ctp/docker-compose.ha.yml",
        "docker_ctp/seed/ctp_seed.py",
        "docker_ctp/seed/ha_seed.py",
        "docker_ctp/worker/worker.py",
        "docker_ctp/admin/app.py",
        "runtime/dashboard/app.py",
        "runtime/md_simnow/md_server.py",
        "java_ctp_md/pom.xml",
        "tools/ai_review/review_push.py",
        "tools/ai_review/audit_repo.py",
    ]
    files = []
    for path in interesting:
        text = read_file_excerpt(path)
        if text:
            files.append({"path": path, "content": text})

    return {
        "repository": run_git("config", "--get", "remote.origin.url", check=False),
        "head_sha": run_git("rev-parse", "HEAD"),
        "recent_commits": run_git("log", "--oneline", "-n", "10", check=False),
        "status_short": run_git("status", "--short", check=False),
        "files": files,
    }
