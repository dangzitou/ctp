#!/usr/bin/env python3
from __future__ import annotations

import textwrap


REVIEWER_SYSTEM = (
    "You are a senior software reviewer. Be concise, high-signal, and concrete. "
    "Never invent facts that are not present in the supplied repository snapshot."
)


def build_reviewer_prompt(role: str, payload: dict) -> str:
    files = "\n".join(f"- {path}" for path in payload.get("included_files", []))
    skipped = payload.get("skipped_files", 0)
    role_focus = {
        "code": "Focus on logic bugs, regressions, data flow, and missing verification.",
        "security": "Focus on secrets, dangerous defaults, auth, network exposure, shell risks, and workflow abuse.",
        "docs-runtime": "Focus on docs drift, operational runbooks, deployment consistency, and runtime observability gaps.",
        "operations": "Focus on deployability, HA behavior, runtime health, and incident risk.",
        "code-health": "Focus on maintainability, correctness, duplication, and testing gaps.",
        "workflow-release": "Focus on CI/CD correctness, automation safety, release drift, and secret handling.",
    }.get(role, "Focus on the most important engineering risks.")

    return textwrap.dedent(
        f"""
        Repository: {payload.get('repository')}
        Base commit: {payload.get('base_sha')}
        Head commit: {payload.get('head_sha')}
        Reviewer role: {role}

        {role_focus}

        Included files:
        {files or "- none"}

        Skipped files due to limits: {skipped}

        Return Markdown using exactly:
        ## Verdict
        One short paragraph.

        ## Findings
        - Use bullets in the format:
          [severity] path - problem, impact, suggested fix
        - If there are no meaningful issues, write exactly:
          - No major issues detected in the reviewed material.

        ## Test Gaps
        - Mention the most important missing verification, or say:
          - No critical additional tests identified from this review.

        Reviewed material:
        {payload.get('review_material', '')}
        """
    ).strip()


def build_coordinate_prompt(kind: str, payload: dict, reviewer_results: list[dict]) -> str:
    sections = []
    for result in reviewer_results:
        role = result.get("role", "unknown")
        if result.get("ok"):
            sections.append(f"### Reviewer: {role}\n{result.get('content', '')}")
        else:
            sections.append(f"### Reviewer: {role}\nFAILED: {result.get('error', 'unknown error')}")

    label = "AI Code Review" if kind == "review" else "AI Repo Audit"
    joined = "\n\n".join(sections)
    return textwrap.dedent(
        f"""
        You are the coordinator for {label}.
        Merge the reviewer outputs into one concise final report.
        Preserve high-signal findings, deduplicate overlaps, and explicitly mention reviewer failures.

        Return Markdown using exactly:
        ## Verdict
        One short paragraph.

        ## Findings
        - Consolidated findings, ordered by severity.
        - If there are no meaningful issues, write exactly:
          - No major issues detected in the reviewed material.

        ## Test Gaps
        - Mention the most important missing verification, or say:
          - No critical additional tests identified from this review.

        ## Agent Breakdown
        - One bullet per reviewer role with either `ok` or `failed: <reason>`.

        Context:
        Repository: {payload.get('repository')}
        Head commit: {payload.get('head_sha')}

        Reviewer outputs:
        {joined}
        """
    ).strip()
