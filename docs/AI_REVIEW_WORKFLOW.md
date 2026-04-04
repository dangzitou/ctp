# AI Code Review Workflow

This repository now includes a GitHub Actions workflow at `.github/workflows/ai-code-review.yml`.

It is inspired by PR-Agent's "review the change, publish concrete findings" loop, but adapted to this repo's commit-driven workflow:

- Trigger: every `push` to a branch, plus manual `workflow_dispatch`
- Input: the diff between the previous pushed commit and the new commit
- Output:
  - a GitHub Actions run summary
  - a commit comment attached to the pushed SHA

## Setup

Add this repository secret:

- `OPENAI_API_KEY`: API key used by the workflow

Optional repository variables:

- `AI_REVIEW_MODEL`: defaults to `gpt-5-mini`
- `AI_REVIEW_MAX_FILES`: defaults to `12`
- `AI_REVIEW_MAX_PATCH_CHARS`: defaults to `60000`

## What Gets Reviewed

The review script prioritizes the code you are actively maintaining:

- `runtime/**`
- `docker_ctp/**`
- `java_ctp_md/**`
- `docs/**`
- root-level source files and workflow files

It skips vendor and generated content such as:

- `openctp/**`
- packaged SDK folders
- `target/**`
- `.dll`, `.pyd`, `.jar`, `.class`, `.zip`

## Review Style

The workflow asks the model to focus on:

- bugs and behavioral regressions
- data-flow breakage
- security issues
- unsafe runtime assumptions
- missing high-value verification

The output is intentionally terse and findings-first so it behaves more like a code reviewer than a generic summarizer.
