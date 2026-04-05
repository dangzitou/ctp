# CTP 公司项目复现手册

这是一份面向公司落地环境的总手册，目标不是只告诉你“怎么启动”，而是尽量把本次实施过程中已经遇到过的问题、限制、排查方法、替代方案、验收标准全部记录下来。

适用场景：

- 你回到公司后，需要在 Mac 上复现这套系统
- 你需要让同事按文档把系统重新搭起来
- 你需要把真实公司 CTP 接口接进来
- 你需要启用 GitHub 上的 AI 审查、自修复、定时巡查、Issue 通知
- 你需要知道“哪些点已经成功验证过，哪些点还要结合公司真实环境验证”

## 1. 本次已经完成的能力

当前仓库已经具备这些能力：

- `seed / worker / admin / dashboard` 高可用部署结构
- Mac 上 Docker 化运行主业务栈
- Windows 上运行真实 CTP 行情中继
- Mac Docker 栈通过 TCP 接入 Windows 真实行情中继
- Redis 驱动的 front 地址切换
- Redis 驱动的认证信息解耦
- GitHub 多 Agent 中文代码审查
- 审查完成后尝试自动修复并提交 PR
- GitHub 每天定时巡查一次
- 审查结果写回 commit comment
- 巡查结果写回固定 Issue
- 审查结果支持中文 Issue 汇总

## 2. 这次实施过程中已经确认成功的结果

已确认：

- MiniMax 多 Agent 代码审查 workflow 已部署到仓库并跑通过
- MiniMax 定时巡查 workflow 已部署到仓库并跑通过
- `main` 分支已经包含自动修复 PR 逻辑
- `main` 分支已经包含中文审查 Issue 汇总逻辑
- `main` 分支已经包含 front/auth 解耦逻辑
- 相关文档已经全部写入仓库

已推送的关键提交：

1. `a96516d` 多 Agent 审查与巡查 workflow
2. `6d4823b` Mac Docker 部署说明与 dashboard HA
3. `945505a` 可切换 CTP front 与认证解耦
4. `e3d1c57` 中文通知链路
5. `e013692` 自动修复 PR
6. `aa096a2` 复现手册初版

## 3. 哪些事项已经实现，哪些事项还需要公司环境验证

### 3.1 已实现

- 代码结构和 workflow 逻辑
- Redis front/auth 控制面
- 中文审查输出
- 自动修复 PR 生成与自动合并机制
- 定时巡查机制
- 审查结果写入 Issue 的 workflow 接线

### 3.2 必须到公司环境再验证

- 公司 CTP front 是否要求额外认证参数
- 公司账号是否允许当前认证链路登录
- 公司 SMTP 是否允许 GitHub Actions 发信
- 公司网络是否允许 Mac 访问 Windows 中继
- 公司网络是否允许 Windows 访问对应 CTP front
- 真实行情是否能稳定进入 Kafka / Redis / Dashboard

## 4. 仓库内关键文件清单

### 4.1 部署与高可用

- [docker-compose.ha.yml](/e:/Develop/projects/ctp/docker_ctp/docker-compose.ha.yml)
- [.env.ha](/e:/Develop/projects/ctp/docker_ctp/.env.ha)
- [ha_seed.py](/e:/Develop/projects/ctp/docker_ctp/seed/ha_seed.py)
- [ctp_seed.py](/e:/Develop/projects/ctp/docker_ctp/seed/ctp_seed.py)
- [worker.py](/e:/Develop/projects/ctp/docker_ctp/worker/worker.py)
- [app.py](/e:/Develop/projects/ctp/docker_ctp/admin/app.py)

### 4.2 真实行情与中继

- [md_server.py](/e:/Develop/projects/ctp/runtime/md_simnow/md_server.py)
- [live_md_demo.py](/e:/Develop/projects/ctp/runtime/md_simnow/live_md_demo.py)
- [scan_contracts.py](/e:/Develop/projects/ctp/runtime/md_simnow/scan_contracts.py)
- [ctp_bridge.py](/e:/Develop/projects/ctp/runtime/dashboard/ctp_bridge.py)
- [front_config.py](/e:/Develop/projects/ctp/runtime/front_config.py)

### 4.3 AI 自动化

- [ai-code-review.yml](/e:/Develop/projects/ctp/.github/workflows/ai-code-review.yml)
- [ai-repo-audit.yml](/e:/Develop/projects/ctp/.github/workflows/ai-repo-audit.yml)
- [review_push.py](/e:/Develop/projects/ctp/tools/ai_review/review_push.py)
- [audit_repo.py](/e:/Develop/projects/ctp/tools/ai_review/audit_repo.py)
- [auto_fix.py](/e:/Develop/projects/ctp/tools/ai_review/auto_fix.py)
- [send_email.py](/e:/Develop/projects/ctp/tools/ai_review/send_email.py)
- [prompts.py](/e:/Develop/projects/ctp/tools/ai_review/prompts.py)
- [github_api.py](/e:/Develop/projects/ctp/tools/ai_review/github_api.py)

### 4.4 现有专项文档

- [MAC_DOCKER_DEPLOYMENT.md](/e:/Develop/projects/ctp/docs/MAC_DOCKER_DEPLOYMENT.md)
- [HA_DEPLOYMENT.md](/e:/Develop/projects/ctp/docs/HA_DEPLOYMENT.md)
- [DATA_INTERFACE_SWITCHING.md](/e:/Develop/projects/ctp/docs/DATA_INTERFACE_SWITCHING.md)
- [AI_REVIEW_WORKFLOW.md](/e:/Develop/projects/ctp/docs/AI_REVIEW_WORKFLOW.md)

## 5. 推荐的复现顺序

这部分很重要，不建议跳步骤。

推荐顺序：

1. 先在 Mac 上跑 `sim` 模式，确认 Docker 栈健康
2. 再确认 GitHub 的代码审查和巡查 workflow 可运行
3. 再确认 GitHub Issue 输出正常
4. 再接入 Windows 真实中继
5. 再接入公司 front 和公司认证
6. 最后再验收真实数据流

原因：

- 这样能把“平台问题”和“行情问题”分离
- 如果一上来就接公司接口，排查会混在一起
- 先跑 `sim` 模式可以证明 Kafka、Redis、MySQL、Dashboard、HA 没问题

## 6. Mac 环境准备

Mac 侧建议准备：

- macOS
- Docker Desktop
- Git

建议但不是必须：

- 可以访问 GitHub
- 能通过浏览器访问本地 `localhost:18080`、`localhost:18081`

不要求本地安装：

- MySQL
- Redis
- Kafka
- Java
- Maven

原因是这条路径优先走 Docker。

## 7. Windows 环境准备

如果要接真实 CTP 数据，建议有一台 Windows 机器。

Windows 侧建议准备：

- Python
- 能运行 `runtime/md_simnow` 下脚本
- 能访问公司 front
- 能被 Mac 访问到中继端口

为什么不建议直接在 Mac/Linux 容器里跑真实 CTP：

- 当前 CTP DLL 与 Python binding 实际运行链路更偏 Windows
- Mac/Linux 容器里要兼容真实 DLL，维护成本和不确定性更高
- 当前方案已经把“真实行情采集”与“Docker 业务栈”解耦成中继模式

## 8. GitHub 环境准备

至少需要仓库管理员可以配置：

- Secrets
- Variables
- Actions

必须知道的结论：

- GitHub Secret 放在公共仓库里，不会因为仓库是 public 就自动明文暴露
- 但如果你把 key 提交进代码、日志、文档、Issue、评论，那就算泄露
- 用户曾在对话里明文给过 MiniMax key，因此上线前应视为已暴露并轮换

## 9. Mac 上启动高可用业务栈

```bash
git clone https://github.com/dangzitou/ctp.git
cd ctp/docker_ctp
cp .env.ha .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

正常情况下应看到这些服务：

- `kafka`
- `redis`
- `mysql`
- `seed`
- `worker`
- `admin`
- `dashboard`
- `admin-lb`
- `dashboard-lb`

访问地址：

- Admin: `http://localhost:18081`
- Dashboard: `http://localhost:18080`

## 10. 高可用拓扑说明

### 10.1 seed

- 负责生产 tick
- 通过 Redis leader key 做主备
- 多实例时只有一个活跃 leader

### 10.2 worker

- 负责消费 Kafka
- 可水平扩容
- 多实例通过 consumer group 分担

### 10.3 admin

- 管理面服务
- 可多实例
- 通过 `admin-lb` 暴露

### 10.4 dashboard

- Java 服务
- 可多实例
- 通过 `dashboard-lb` 暴露

## 11. 两种数据模式

### 11.1 模拟数据模式

使用：

```env
SEED_MODE=sim
```

适合：

- 先跑通部署
- 先确认数据流
- 先验证 UI
- 不依赖公司 front

### 11.2 真实数据模式

方式：

1. Windows 跑 `md_server.py`
2. Mac Docker 的 `seed` 通过 TCP 连接该中继

Windows：

```powershell
cd E:\Develop\projects\ctp
python runtime\md_simnow\md_server.py 19842
```

Mac：

```env
SEED_MODE=tcp
MD_SERVER_HOST=<windows-ip-or-hostname>
MD_SERVER_PORT=19842
```

## 12. Redis 驱动的数据接口切换

### 12.1 front 集合

Redis key：

- `ctp_collect_url`

例子：

```bash
redis-cli SADD ctp_collect_url tcp://101.230.178.179:53313
redis-cli SADD ctp_collect_url tcp://101.230.178.178:53313
redis-cli SMEMBERS ctp_collect_url
```

### 12.2 认证 hash

Redis key：

- `ctp_collect_auth`

支持字段：

- `broker_id`
- `user_id`
- `password`
- `app_id`
- `auth_code`
- `user_product_info`

例子：

```bash
redis-cli HSET ctp_collect_auth broker_id your_broker_id
redis-cli HSET ctp_collect_auth user_id your_user_id
redis-cli HSET ctp_collect_auth password 'your_password'
redis-cli HSET ctp_collect_auth app_id your_app_id
redis-cli HSET ctp_collect_auth auth_code 'your_auth_code'
redis-cli HSET ctp_collect_auth user_product_info 'company-md'
redis-cli HGETALL ctp_collect_auth
```

### 12.3 解析优先级

front 优先级：

1. `CTP_FRONT` 或 `CTP_FRONTS`
2. Redis `ctp_collect_url`
3. 代码默认值

认证优先级：

1. `CTP_BROKER_ID` / `CTP_USER_ID` / `CTP_PASSWORD` / `CTP_APP_ID` / `CTP_AUTH_CODE`
2. Redis `ctp_collect_auth`
3. 代码默认值

### 12.4 多个 front 时的行为

默认行为：

- 多个 front 存在时，按排序后取第一个

可选覆盖：

- `CTP_FRONT_PICK=random`
- `CTP_FRONT_INDEX=1`

注意：

- 当前是“启动时解析”
- 不是运行中热切换
- 修改 Redis 后必须重启相关进程

## 13. 当前已经接入统一配置层的入口

已接入：

- [md_server.py](/e:/Develop/projects/ctp/runtime/md_simnow/md_server.py)
- [live_md_demo.py](/e:/Develop/projects/ctp/runtime/md_simnow/live_md_demo.py)
- [scan_contracts.py](/e:/Develop/projects/ctp/runtime/md_simnow/scan_contracts.py)
- [ctp_bridge.py](/e:/Develop/projects/ctp/runtime/dashboard/ctp_bridge.py)
- [ctp_seed.py](/e:/Develop/projects/ctp/docker_ctp/seed/ctp_seed.py)
- [MarketDataClient.java](/e:/Develop/projects/ctp/java_ctp_md/src/main/java/com/ctp/market/MarketDataClient.java)

## 14. 公司认证解耦说明

这部分是为了应对“公司接口可能需要账号认证、AppID、AuthCode”的情况专门补的。

现在的思路是：

- 线路是线路
- 账号是账号
- App 认证是 App 认证

三者不再写死在同一份代码里。

这样做的好处：

- 换线路不改代码
- 换账号不改线路
- 公司认证变化时只改 Redis 或环境变量

## 15. GitHub 多 Agent 代码审查说明

workflow：

- [ai-code-review.yml](/e:/Develop/projects/ctp/.github/workflows/ai-code-review.yml)

当前结构：

1. `prepare-diff`
2. `review-code`
3. `review-security`
4. `review-docs-runtime`
5. `review-coordinator`
6. `auto-fix`
7. `publish-review-issue`

输出：

- 中文 Actions Summary
- 中文 commit comment
- 固定复用的中文 Review Issue
- 自动修复 PR 与自动合并

## 16. GitHub 定时巡查说明

workflow：

- [ai-repo-audit.yml](/e:/Develop/projects/ctp/.github/workflows/ai-repo-audit.yml)

当前结构：

1. `prepare-snapshot`
2. `audit-operations`
3. `audit-code-health`
4. `audit-workflow-release`
5. `audit-coordinator`

触发：

- 每天一次
- 或手动触发

输出：

- 中文 Actions Summary
- 固定复用的巡查 Issue

## 17. 自动修复不是“只报告”

当前已经不是只报告。

完整链路：

1. reviewer 并行输出中文审查结果
2. coordinator 汇总中文报告
3. `auto-fix` 读取最终报告
4. 如果报告中存在“证据充分、边界清晰、可控”的问题，AI 生成修复
5. workflow 自动创建修复 PR

为什么不直接推主分支：

- 风险太高
- 便于人工验收
- 适合公司流程

## 18. GitHub 需要配置的 Secrets 和 Variables

### 18.1 必填 Secrets

- `MINIMAX_API_KEY`

### 18.2 推荐 Variables

- `AI_REVIEW_MODEL`
- `AI_AUDIT_MODEL`
- `AI_REVIEW_MAX_FILES`
- `AI_REVIEW_MAX_PATCH_CHARS`
### 18.3 推荐默认值

- `AI_REVIEW_MODEL=MiniMax-M2.5`
- `AI_AUDIT_MODEL=MiniMax-M2.5`
- `AI_REVIEW_MAX_FILES=12`
- `AI_REVIEW_MAX_PATCH_CHARS=60000`

## 19. 验收步骤

### 19.1 部署验收

检查：

- `docker compose ... ps`
- `http://localhost:18081`
- `http://localhost:18080`

### 19.2 模拟数据验收

检查：

- Dashboard 有数据
- Redis 有最新 tick
- worker 正在消费 Kafka

### 19.3 真实数据验收

检查：

- Windows 中继已连接 front
- Mac seed 已连接 Windows 中继
- Kafka 有真实 tick
- Dashboard 能看到真实数据变化

### 19.4 代码审查验收

检查：

- `AI Code Review` workflow 绿色成功
- commit 页面出现中文评论
- 固定 Review Issue 被创建或更新

### 19.5 自动修复验收

检查：

- `auto-fix` job 执行
- 出现自动修复 PR，或直接被 workflow 自动合并
- PR 内有真实代码变更，或目标分支出现自动修复提交

### 19.6 定时巡查验收

检查：

- `AI Repo Audit` workflow 成功
- 固定巡查 Issue 被创建或更新

## 20. 本次实施中遇到的真实问题与解决方案

这一节最关键，记录的是这次真实落地时已经遇到的问题。

### 20.1 用户提供的 MiniMax key 曾在对话中明文出现

问题：

- 一旦 key 在对话、日志、截图、代码中明文出现，就应视为已暴露

解决方案：

- 不把该 key 写入仓库
- 只写入 GitHub Secret `MINIMAX_API_KEY`
- 建议上线前在 MiniMax 平台重新轮换 key

### 20.2 GitHub public 仓库的 Secret 是否会自动暴露

问题：

- 用户担心 public 仓库会把 Secret 暴露给公网

结论：

- GitHub Secret 不会因为仓库是 public 就自动明文暴露
- 但如果 workflow、代码、日志主动打印，依然会泄露

解决方案：

- 不在代码、workflow、文档里明文写 key
- 不输出请求头、完整 env、完整 prompt

### 20.3 Docker 在当前 Windows 机器上不稳定

问题：

- 本地 Docker 引擎曾出现超时、不可用或状态不稳定

影响：

- 本机无法稳定完成全量容器验证

解决方案：

- 设计上把最终运行环境转到 Mac Docker
- Windows 主要负责真实 CTP 中继
- 验收分为“GitHub workflow 成功”和“Mac Docker 业务栈成功”

### 20.4 真实 CTP DLL 更偏 Windows

问题：

- 真实 CTP Python/DLL 在 Mac/Linux 容器里不一定稳定

解决方案：

- 不强行把 DLL 塞进 Mac 容器
- 采用 Windows 中继 + Mac TCP 接入

### 20.5 公司接口可能需要账号认证和 App 认证

问题：

- 不能只写死 front 地址

解决方案：

- front 放在 `ctp_collect_url`
- 认证放在 `ctp_collect_auth`
- 统一由 `runtime/front_config.py` 解析

### 20.6 工作区里存在无关未跟踪文件

问题：

- `runtime/CTP_期货行情接口综合报告.md` 是无关文件，不应误提交

解决方案：

- 提交时显式挑选文件
- 不把该文件纳入 commit

### 20.7 PowerShell 不支持 `&&`

问题：

- 在 PowerShell 环境里，直接写 `cmd1 && cmd2` 可能报错

解决方案：

- 改为分两次执行
- 或使用 PowerShell 风格命令组合

### 20.8 文档/终端中文显示乱码

问题：

- 在某些 Windows PowerShell 编码环境下，UTF-8 中文显示会乱码

影响：

- 终端里看文档可能乱码
- 文件本身未必损坏

解决方案：

- 文件仍统一用 UTF-8
- 如果本地显示乱码，优先用编辑器打开而不是直接依赖终端输出
- 如有必要，调整 PowerShell 代码页或终端编码

### 20.9 CRLF 与 LF 提示

问题：

- Git 提示 `LF will be replaced by CRLF`

影响：

- 一般不影响逻辑
- 只是换行风格提醒

解决方案：

- 不把它当功能错误
- 只在团队明确要求统一换行时再处理

### 20.10 GitHub Actions 审查结果默认改为写入 Issue

问题：

- 邮件通知会把审查结果打散到邮箱里，后续检索和协作都不方便

解决方案：

- 审查 workflow 现在会把结果写到固定 Review Issue
- 同时保留 commit comment，方便在提交页快速查看

### 20.11 自动修复不能无边界乱改

问题：

- 如果让 AI 自动修复直接改主分支，风险不可接受

解决方案：

- 只对已审查文本文件做有边界的改动
- 只生成 PR，不直接改主分支

### 20.12 审查输出要求中文

问题：

- 默认 reviewer prompt 是英文

解决方案：

- 统一改 reviewer/coordinator prompt
- Summary、comment、issue 都走中文

## 21. 最常见故障排查

### 21.1 Dashboard 启动了但没有数据

按顺序检查：

1. `seed` 是否有日志输出
2. `worker` 是否在消费
3. Kafka 是否存在 `ctp-ticks`
4. Redis 是否有最新 tick
5. `SEED_MODE` 是否正确

### 21.2 真实数据模式完全没数据

按顺序检查：

1. Windows `md_server.py` 是否成功登录
2. Windows 是否能访问公司 front
3. Mac 是否能访问 Windows 中继端口
4. `MD_SERVER_HOST`、`MD_SERVER_PORT` 是否正确
5. 认证字段是否正确

### 21.3 审查 workflow 成功但没 Review Issue

检查：

1. `GITHUB_TOKEN` 是否具备 `issues: write`
2. `publish-review-issue` job 是否执行成功
3. 仓库 Issue 是否被过滤或折叠

### 21.4 自动修复没有创建 PR

可能原因：

1. 报告里没有明确可修复问题
2. AI 生成了空修改
3. 改动不在允许的文件集合里
4. PR 创建权限不足

### 21.5 巡查 workflow 跑了但没有 Issue

检查：

1. `GITHUB_TOKEN` 是否具有 `issues: write`
2. coordinator 是否执行成功
3. 仓库 Issue 是否被过滤

## 22. 公司环境推荐落地顺序

最终推荐顺序：

1. 先跑 `sim` 模式
2. 再确认 Docker 栈稳定
3. 再确认 GitHub 审查 workflow 绿色
4. 再补 SMTP
5. 再接 Windows 中继
6. 再写 Redis front/auth
7. 再接真实公司接口
8. 再做一次 push 验收审查、自修复、Issue 汇总

## 23. 最终上线建议

建议遵守这些原则：

- 所有密钥只进 GitHub Secrets 或公司安全系统
- front 和认证优先放 Redis
- AI 自动修复默认先开 PR，再尝试自动合并；如果仓库策略不允许，会退回为保留 PR 等待人工确认
- 定时巡查先作为告警与发现机制，不要直接自动改生产分支
- 真实行情接入前，先在非生产账号或测试线路上验证

## 24. 结论

如果你回到公司要复现，最稳妥的路径是：

1. Mac 上先跑 `sim`
2. GitHub 上确认审查、自修复、巡查都正常
3. 确认固定 Review Issue 能正常更新
4. Windows 侧跑真实行情中继
5. Redis 写入公司 front 与认证
6. 重启中继和 seed
7. 验收真实数据流

这份文档后续应作为总入口维护，其他文档继续作为专项补充。
