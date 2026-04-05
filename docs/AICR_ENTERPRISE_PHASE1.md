# CTP AICR 企业级第一阶段说明

这份文档专门解释本次“企业级第一阶段升级”落地了什么，方便你在公司环境做复现、验收和后续扩展。

## 1. 升级目标

本阶段的核心不是“无脑自动修”，而是“企业可控自动化”：

- 多 agent 并行审查继续保留
- 低风险目录允许 auto-fix
- 只有低风险且通过门禁的修复允许 auto-merge
- 高风险目录只审查，不自动改
- 每次运行生成结构化审计日志，方便统计和追责
- 结果继续写到固定 GitHub Issue，避免邮件轰炸

## 2. 关键文件

- [ai-code-review.yml](../.github/workflows/ai-code-review.yml)
- [ai-repo-audit.yml](../.github/workflows/ai-repo-audit.yml)
- [policy.json](../tools/ai_review/policy.json)
- [policy.py](../tools/ai_review/policy.py)
- [review_push.py](../tools/ai_review/review_push.py)
- [auto_fix.py](../tools/ai_review/auto_fix.py)
- [validate_auto_fix.py](../tools/ai_review/validate_auto_fix.py)
- [build_audit_artifact.py](../tools/ai_review/build_audit_artifact.py)
- [publish_review_issue.py](../tools/ai_review/publish_review_issue.py)

## 3. 当前策略

策略定义在 [policy.json](../tools/ai_review/policy.json)。

当前默认规则：

- `low_risk`
  - `docs/**`
  - `README.md`
  - Markdown 与常规低风险配置
  - 允许 auto-fix
  - 允许 auto-merge
- `medium_risk`
  - `tools/ai_review/**`
  - 常规 Python / Java / Docker 代码
  - 不允许 auto-fix
  - 不允许 auto-merge
- `high_risk`
  - `.github/workflows/**`
  - `runtime/front_config.py`
  - 真实行情接入脚本
  - 核心 docker compose / start 脚本
  - 不允许 auto-fix
  - 不允许 auto-merge

注意：

- 高风险规则优先于低风险规则
- 未命中规则时默认按 `medium_risk`
- 只要一个变更集里混入高风险文件，整个 auto-merge 自动关闭

## 4. Push 审查链路

`AI Code Review` 的 job 顺序：

1. `prepare-diff`
2. `review-code`
3. `review-security`
4. `review-docs-runtime`
5. `review-coordinator`
6. `validate-auto-fix`
7. `auto-fix`
8. `publish-review-issue`

结果输出到：

- Actions Summary
- commit comment
- 固定 Issue：`AI Code Review Inbox`
- 审计 artifact：`review-audit.json`

## 5. 验证门禁

门禁统一由 [validate_auto_fix.py](../tools/ai_review/validate_auto_fix.py) 执行。

当前门禁包括：

- `python_compile`
- `java_compile`
- `docker_compose_config`
- `markdown_links`

执行逻辑：

- Python：编译 `tools/ai_review` 和本次修改的 `.py`
- Java：至少验证 `pom.xml` 可读；如果 runner 有 Maven，再执行最小编译
- Docker：优先 `docker compose config`，没有 Docker 时退化为 YAML 结构校验
- Markdown：校验相对链接不失效

## 6. Auto-Fix 与 Auto-Merge 决策

auto-fix 的前提：

- coordinator 成功产出 review 报告
- 模型给出可落地的文件修改
- 修改文件全部落在 `auto_fix_allowed=true` 的路径内

auto-merge 的前提：

- `AI_REVIEW_ENABLE_AUTO_MERGE` 未关闭
- 本次修复文件全部属于 `auto_merge_allowed=true` 的低风险范围
- 所有 required gate 都通过

阻断时会在这些地方看到原因：

- `AI Code Review Inbox`
- Actions Summary
- `review-audit.json`
- `auto-fix-validation.json`

## 7. 定时巡查

`AI Repo Audit` 当前是每天一次：

- cron: `0 0 * * *`

它固定对 `main` 做巡查，避免手动触发时跑偏分支。

输出：

- 固定 Issue：`AI Repo Audit`
- 审计 artifact：`repo-audit.json`

## 8. 验收建议

建议做三组验收：

1. 低风险样本
   - 改一个 `docs/**` 里的 markdown 链接错误
   - 看是否触发 reviewer、生成审计 JSON、自动开 PR，并在门禁通过后自动合并
2. 高风险样本
   - 改 `.github/workflows/**` 或 `runtime/front_config.py`
   - 看是否正常审查，但 auto-fix 被阻断
3. 巡查样本
   - 手动触发 `AI Repo Audit`
   - 看固定 Issue 是否被更新，`repo-audit.json` 是否生成

## 9. 扩展建议

如果后面要继续升级成真正企业级第二阶段，建议优先做这几件事：

- 加一层 allowlist 规则，让 auto-fix 只修“规则命中的已知问题类型”
- 增加 PR 分支保护和 required checks 联动
- 将审计 JSON 汇总到外部存储或 BI
- 把 repo audit 扩展到依赖、许可证和 SBOM
- 引入自愈前的 dry-run / compare 审批开关
