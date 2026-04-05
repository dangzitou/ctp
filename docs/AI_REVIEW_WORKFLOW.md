# AI Review And Audit Workflows

本仓库当前的 AICR 已升级为 **MCP 增强型多 agent 审查**，目标是解决“只看 diff 的形式主义”问题。

当前链路分成两层 MCP：

- 官方 MiniMax Coding Plan MCP：用于外部搜索等增强上下文
- 仓库内 repo-local MCP server：用于代码库、Git、GitHub 上下文采集

GitHub Actions 不直接让 reviewer 自由调用工具，而是先走 **MCP 预采集模式**：

1. workflow 生成基础 payload
2. MCP context orchestrator 采集上下文
3. 输出 `review-context.json` 或 `repo-audit-context.json`
4. reviewer / coordinator 读取 context bundle 做审查

这样做的好处是：

- 云端稳定
- 输入可复现
- 审计可留痕
- 不依赖模型是否稳定触发 tool call

## Setup

GitHub Secrets：

- `MINIMAX_API_KEY`
- `AI_REVIEW_GH_TOKEN`
- `AI_AUTOFIX_GITHUB_TOKEN`

GitHub Variables：

- `AI_REVIEW_MODEL`
- `AI_AUDIT_MODEL`
- `AI_REVIEW_MAX_FILES`
- `AI_REVIEW_MAX_PATCH_CHARS`
- `AI_REVIEW_ENABLE_AUTO_MERGE`
- `AI_REVIEW_AUDIT_ARTIFACT`
- `AI_REVIEW_ENABLE_MCP`
- `AI_REVIEW_MCP_MODE`
- `AI_REVIEW_MCP_CONTEXT_BUDGET`
- `AI_REVIEW_MCP_RELATED_FILE_LIMIT`
- `AI_REVIEW_MCP_ISSUE_LOOKBACK_DAYS`
- `AI_REVIEW_MCP_PR_LOOKBACK_DAYS`
- `AI_REVIEW_MCP_ENABLE_WEB_SEARCH`
- `AI_REVIEW_MINIMAX_MCP_CMD` 可选，用于覆盖官方 MiniMax MCP 启动命令

workflow 里会注入：

- `OPENAI_API_KEY=${{ secrets.MINIMAX_API_KEY }}`
- `MINIMAX_API_KEY=${{ secrets.MINIMAX_API_KEY }}`
- `OPENAI_BASE_URL=https://api.minimaxi.com/v1`

## Push Review Workflow

[ai-code-review.yml](../.github/workflows/ai-code-review.yml) 的 job 顺序：

1. `prepare-diff`
2. `prepare-mcp-context`
3. `review-code`
4. `review-security`
5. `review-docs-runtime`
6. `review-coordinator`
7. `validate-auto-fix`
8. `auto-fix`
9. `publish-review-issue`

`prepare-mcp-context` 会生成 `review-context.json` 这一类上下文包，内容包括：

- 原始 diff 元数据
- changed files
- impacted files
- related files / configs / docs / workflows
- recent related commit messages
- related issues / PRs
- commit checks / failed runs
- external web search 摘要
- policy assessment
- MCP tool call 记录

三个 reviewer 都消费同一个 context bundle，但关注点不同：

- `code reviewer`
- `security reviewer`
- `docs/runtime reviewer`

输出：

- Actions Summary
- commit comment
- 固定 Issue：`AI Code Review Inbox`
- `review-context.json`
- `review-audit.json`

## Repo Audit Workflow

[ai-repo-audit.yml](../.github/workflows/ai-repo-audit.yml) 当前每 6 小时一次：

- cron: `0 */6 * * *`

job 顺序：

1. `prepare-snapshot`
2. `prepare-mcp-context`
3. `audit-operations`
4. `audit-code-health`
5. `audit-workflow-release`
6. `audit-coordinator`

`prepare-mcp-context` 会生成 `repo-audit-context.json`，重点包含：

- 默认分支最近提交
- recent issues / PRs
- recent failed workflow runs
- 关键 workflow/config/runtime/docker/java 文件邻域
- MCP 调用轨迹与降级信息

输出：

- Actions Summary
- 固定 Issue：`AI Repo Audit`
- `repo-audit-context.json`
- `repo-audit.json`

## Repo-Local MCP Server

仓库内 MCP server 在 [mcp_server.py](../tools/ai_review/mcp_server.py)。

当前暴露的核心工具：

- `get_changed_files`
- `get_diff_patch`
- `get_file_content`
- `get_related_files`
- `get_symbol_references`
- `get_import_dependents`
- `get_config_neighbors`
- `get_file_history`
- `get_recent_commits`
- `get_blame_summary`
- `get_related_commit_messages`
- `get_recent_repo_issues`
- `get_recent_related_issues`
- `get_recent_repo_prs`
- `get_commit_checks`
- `get_recent_failed_runs`

MCP client 在 [mcp_client.py](../tools/ai_review/mcp_client.py)，context orchestrator 在 [mcp_context.py](../tools/ai_review/mcp_context.py)。

## Auto-Fix

MCP 接入后，auto-fix 会拿到更多上下文，但不会放宽权限边界。

仍然遵守：

- 只修低风险且策略允许的文件
- 只在已审查文件集合内修改
- 只要 context bundle 显示涉及高风险链路，就关闭 auto-merge

auto-fix 结果现在显式带出：

- `root_cause_guess`
- `evidence_sources`
- `changed_files`
- `risk_level`
- `auto_fix_allowed`
- `auto_merge_allowed`
- `blocked_reason`
- `gates`

## Audit Fields

push/repo audit 的 JSON artifact 现在新增：

- `mcp_enabled`
- `mcp_sources`
- `mcp_tool_calls`
- `context_bundle_size`
- `related_files`
- `related_issues`
- `related_prs`
- `recent_failed_runs`
- `external_search_used`

## How To Verify

你要确认它不是“只看 diff”，至少看这几项：

- `prepare-mcp-context` job 是否真的运行
- 是否生成 `review-context.json` 或 `repo-audit-context.json`
- `review-audit.json` / `repo-audit.json` 里是否有 `mcp_tool_calls`
- Issue 里是否能看到 MCP 摘要
- reviewer 结论是否引用了 impacted files / related issues / failed runs，而不只是 patch

## Degradation Behavior

如果 MiniMax MCP 不可用，链路不会静默假装成功，而是：

- context bundle 标记 `degraded=true`
- 写出 `degraded_reasons`
- `mcp_tool_calls` 里会有失败记录
- reviewer 仍使用已采集到的 repo-local MCP 数据继续审查

如果 repo-local MCP 或 GitHub token 权限不足，同样会在 context bundle 和审计 artifact 里留下失败信息。
