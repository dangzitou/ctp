# AI Review And Audit Workflows

This repository uses MiniMax through the OpenAI-compatible API for two GitHub Actions workflows:

- `.github/workflows/ai-code-review.yml`
- `.github/workflows/ai-repo-audit.yml`

## Setup

Configure these GitHub secrets:

- `MINIMAX_API_KEY`
- `AI_REVIEW_GH_TOKEN` optional but recommended for auto-fix PR creation when the default `GITHUB_TOKEN` cannot open pull requests
- `AI_AUTOFIX_GITHUB_TOKEN` optional but recommended for auto-fix PR creation when the default `GITHUB_TOKEN` cannot open pull requests

Optional GitHub repository variables:

- `AI_REVIEW_MODEL`: defaults to `MiniMax-M2.5`
- `AI_AUDIT_MODEL`: defaults to `MiniMax-M2.5`
- `AI_REVIEW_MAX_FILES`: defaults to `12`
- `AI_REVIEW_MAX_PATCH_CHARS`: defaults to `60000`
The workflows set:

- `OPENAI_API_KEY=${{ secrets.MINIMAX_API_KEY }}`
- `OPENAI_BASE_URL=https://api.minimaxi.com/v1`

No API key is stored in code, repo files, or logs.

## Push Review Workflow

`ai-code-review.yml` runs on:

- every `push`
- manual `workflow_dispatch`

It uses a multi-agent pattern:

1. `prepare-diff`
2. `review-code`
3. `review-security`
4. `review-docs-runtime`
5. `review-coordinator`
6. `auto-fix`
7. `publish-review-issue`

Outputs:

- GitHub Actions summary
- upserted commit comment on the pushed SHA
- one reusable GitHub issue titled `AI Code Review Inbox`
- best-effort AI auto-fix pull request when the report contains actionable issues
- automatic merge of the auto-fix PR when the token and branch policy allow it

Auto-fix PR token selection order:

1. `AI_REVIEW_GH_TOKEN`
2. `AI_AUTOFIX_GITHUB_TOKEN`
3. workflow `GITHUB_TOKEN`

## Scheduled Audit Workflow

`ai-repo-audit.yml` runs on:

- `schedule` once per day
- manual `workflow_dispatch`

It uses a second multi-agent pattern:

1. `prepare-snapshot`
2. `audit-operations`
3. `audit-code-health`
4. `audit-workflow-release`
5. `audit-coordinator`

Outputs:

- GitHub Actions summary
- one reusable GitHub issue titled `AI Repo Audit`

Labels used:

- `ai-audit`
- `automation`
- `triage`

## What Gets Reviewed

The push review prioritizes maintained code and documentation:

- `runtime/**`
- `docker_ctp/**`
- `java_ctp_md/**`
- `docs/**`
- root workflow and source files

It skips vendor and generated material such as:

- `openctp/**`
- packaged SDK folders
- `target/**`
- `.dll`, `.pyd`, `.jar`, `.class`, `.zip`

The scheduled audit reads a curated repository snapshot focused on:

- workflow files
- deployment/config files
- AI automation scripts
- key runtime and docker entrypoints

## Failure Behavior

- Missing `MINIMAX_API_KEY` causes reviewer jobs to fail clearly.
- Coordinator jobs still generate a degraded summary when reviewer jobs fail.
- Push review keeps commit comments idempotent with a fixed marker.
- Scheduled audit keeps a single reusable issue instead of opening duplicates.
- Auto-fix only attempts bounded changes in already-reviewed text files and submits them through a PR instead of pushing directly to the target branch.
- When PR creation succeeds, the workflow tries to squash-merge the auto-fix PR immediately; if GitHub blocks immediate merge, it falls back to enabling auto-merge.
- Pushes produced by the auto-fix merge commit are ignored by the review workflow to avoid self-trigger loops.
- If auto-fix can push a branch but cannot open a PR, configure `AI_REVIEW_GH_TOKEN` or `AI_AUTOFIX_GITHUB_TOKEN`, or enable the repository setting that allows GitHub Actions to create pull requests.
- A token that returns `403 Resource not accessible by personal access token` is missing `Pull requests: Read and write`.

## Language And Issue Output

- Reviewer and coordinator prompts require Simplified Chinese output.
- The same Chinese report is used for:
  - Actions summary
  - commit comment
  - reusable review issue body
- When auto-fix succeeds, the workflow also tries to open a Chinese PR containing the proposed repair.

## Local Notes

- The workflows run on GitHub-hosted runners, not on your local machine.
- Local dry-run is possible only at script level.
- Full behavior like commit comments, review issues, auto-fix PRs, and audit issues requires GitHub Actions context.
