# CTP 公司项目复现手册

这份文档是给后续在公司环境复现整套方案用的总入口。

覆盖范围：

1. 仓库代码拉取与基础准备
2. Mac 上的 Docker 高可用部署
3. Windows 真实 CTP 行情中继
4. Redis 驱动的数据接口切换与认证解耦
5. GitHub 多 Agent 审查、自动修复、定时巡查、邮件通知
6. 验收方法与故障排查

建议先通读本页，再按章节执行。

## 1. 最终目标

复现后的系统应具备这些能力：

- `seed / worker / admin / dashboard` 高可用运行
- Mac 上可通过 Docker 启动业务栈
- 可接模拟数据，也可接 Windows 真实 CTP 中继
- 可通过 Redis 随时切换公司 front 地址
- 可将账号、密码、`app_id`、`auth_code` 与线路解耦
- 每次 `push` 自动触发中文 AI 代码审查
- AI 审查发现明确问题后自动生成修复 PR
- 每 6 小时自动做一次仓库巡查
- 审查结果可写 commit comment、Issue、中文邮件

## 2. 仓库内关键文件

部署与运行：

- [docker-compose.ha.yml](/e:/Develop/projects/ctp/docker_ctp/docker-compose.ha.yml)
- [.env.ha](/e:/Develop/projects/ctp/docker_ctp/.env.ha)
- [ha_seed.py](/e:/Develop/projects/ctp/docker_ctp/seed/ha_seed.py)
- [ctp_seed.py](/e:/Develop/projects/ctp/docker_ctp/seed/ctp_seed.py)
- [app.py](/e:/Develop/projects/ctp/docker_ctp/admin/app.py)

真实行情与接口切换：

- [md_server.py](/e:/Develop/projects/ctp/runtime/md_simnow/md_server.py)
- [live_md_demo.py](/e:/Develop/projects/ctp/runtime/md_simnow/live_md_demo.py)
- [scan_contracts.py](/e:/Develop/projects/ctp/runtime/md_simnow/scan_contracts.py)
- [ctp_bridge.py](/e:/Develop/projects/ctp/runtime/dashboard/ctp_bridge.py)
- [front_config.py](/e:/Develop/projects/ctp/runtime/front_config.py)

AI 自动化：

- [ai-code-review.yml](/e:/Develop/projects/ctp/.github/workflows/ai-code-review.yml)
- [ai-repo-audit.yml](/e:/Develop/projects/ctp/.github/workflows/ai-repo-audit.yml)
- [review_push.py](/e:/Develop/projects/ctp/tools/ai_review/review_push.py)
- [audit_repo.py](/e:/Develop/projects/ctp/tools/ai_review/audit_repo.py)
- [auto_fix.py](/e:/Develop/projects/ctp/tools/ai_review/auto_fix.py)
- [send_email.py](/e:/Develop/projects/ctp/tools/ai_review/send_email.py)

已有专项文档：

- [MAC_DOCKER_DEPLOYMENT.md](/e:/Develop/projects/ctp/docs/MAC_DOCKER_DEPLOYMENT.md)
- [HA_DEPLOYMENT.md](/e:/Develop/projects/ctp/docs/HA_DEPLOYMENT.md)
- [DATA_INTERFACE_SWITCHING.md](/e:/Develop/projects/ctp/docs/DATA_INTERFACE_SWITCHING.md)
- [AI_REVIEW_WORKFLOW.md](/e:/Develop/projects/ctp/docs/AI_REVIEW_WORKFLOW.md)

## 3. 环境准备

### 3.1 Mac 侧

建议环境：

- macOS
- Docker Desktop
- Git

最小要求：

- 能 clone 仓库
- 能运行 Docker Compose
- 能访问 GitHub

### 3.2 Windows 侧

如果要接真实 CTP 行情，建议准备一台 Windows 机器，原因是当前 CTP Python/DLL 运行链更偏向 Windows。

Windows 机器需要：

- Python
- 可运行 `runtime/md_simnow` 下的 CTP 接口脚本
- 能访问公司 front 或 SimNow front
- 能被 Mac 机器网络访问

### 3.3 GitHub 侧

需要有仓库管理权限，至少能配置：

- Secrets
- Variables
- Actions

## 4. Mac 上启动高可用业务栈

```bash
git clone https://github.com/dangzitou/ctp.git
cd ctp/docker_ctp
cp .env.ha .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

默认启动后应有：

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

- 管理面：`http://localhost:18081`
- Dashboard：`http://localhost:18080`

## 5. 两种数据模式

### 5.1 模拟数据

适合先把整套系统跑起来。

特点：

- 不依赖 Windows CTP DLL
- 适合验收 Kafka / Redis / MySQL / Dashboard / HA

使用方式：

```env
SEED_MODE=sim
```

### 5.2 真实数据

适合接公司线路或 SimNow 真实 front。

方式是：

1. Windows 上跑 `md_server.py`
2. Mac Docker 栈里的 `seed` 用 TCP 连接该中继

Windows：

```powershell
cd E:\Develop\projects\ctp
python runtime\md_simnow\md_server.py 19842
```

Mac：

```env
SEED_MODE=tcp
MD_SERVER_HOST=<windows-ip>
MD_SERVER_PORT=19842
```

重启：

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

## 6. 如何切换公司数据接口

系统已经支持把“线路”和“认证”分开管理。

### 6.1 线路集合

Redis key：

- `ctp_collect_url`

例子：

```bash
redis-cli SADD ctp_collect_url tcp://101.230.178.179:53313
redis-cli SADD ctp_collect_url tcp://101.230.178.178:53313
redis-cli SMEMBERS ctp_collect_url
```

### 6.2 认证集合

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

### 6.3 解析优先级

front 解析顺序：

1. `CTP_FRONT` / `CTP_FRONTS`
2. Redis `ctp_collect_url`
3. 代码默认值

认证解析顺序：

1. `CTP_BROKER_ID` / `CTP_USER_ID` / `CTP_PASSWORD` / `CTP_APP_ID` / `CTP_AUTH_CODE`
2. Redis `ctp_collect_auth`
3. 代码默认值

### 6.4 切换后的动作

更新 Redis 后，相关进程不会热切换，必须重启。

常见重启对象：

- Windows `md_server.py`
- `docker_ctp/seed/ctp_seed.py`
- Docker 里的 `seed`

Mac Docker 重启：

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local restart seed
```

## 7. 公司认证解耦方案

这部分是这次专门补的。

目标是：

- 换 front 时不改代码
- 换账号时不改线路配置
- 公司如果要求 `app_id + auth_code`，也不把逻辑写死在业务代码里

现在已经做到：

- `front` 由 [front_config.py](/e:/Develop/projects/ctp/runtime/front_config.py) 统一解析
- Python 真实入口都会读取同一套 front/auth 配置
- Java 示例客户端也支持环境变量覆盖

如果公司后面切到另一套接口，只需要：

1. 改 Redis 里的 `ctp_collect_url`
2. 按需改 `ctp_collect_auth`
3. 重启中继或 seed

## 8. GitHub 多 Agent 自动化

### 8.1 Push 代码审查

workflow：

- [ai-code-review.yml](/e:/Develop/projects/ctp/.github/workflows/ai-code-review.yml)

链路：

1. `prepare-diff`
2. `review-code`
3. `review-security`
4. `review-docs-runtime`
5. `review-coordinator`
6. `auto-fix`
7. `notify-email`

结果：

- 中文 Actions Summary
- 中文 commit comment
- 自动修复 PR
- 中文邮件

### 8.2 定时巡查

workflow：

- [ai-repo-audit.yml](/e:/Develop/projects/ctp/.github/workflows/ai-repo-audit.yml)

链路：

1. `prepare-snapshot`
2. `audit-operations`
3. `audit-code-health`
4. `audit-workflow-release`
5. `audit-coordinator`

触发：

- 每 6 小时一次
- 也可以手动 `workflow_dispatch`

结果：

- 中文 Actions Summary
- 一个复用的巡查 Issue

## 9. 如何让审查 Agent 不只是报告

现在已经不是只报告。

当前行为：

1. 多个 reviewer 先出中文审查结论
2. coordinator 汇总中文结果
3. `auto-fix` job 读取最终报告
4. 如果报告里存在“证据明确、可安全修”的问题，AI 会尝试修复
5. 自动创建修复 PR，而不是直接改主分支

这样做的原因：

- 真正具备“自修复”能力
- 但不直接污染主分支
- 便于公司环境走审查流和验收流

## 10. GitHub 需要配置的 Secrets 和 Variables

### 10.1 必填 Secrets

- `MINIMAX_API_KEY`

如果你要中文邮件通知，还需要：

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`

### 10.2 推荐 Variables

- `AI_REVIEW_MODEL`
- `AI_AUDIT_MODEL`
- `AI_REVIEW_MAX_FILES`
- `AI_REVIEW_MAX_PATCH_CHARS`
- `AI_REVIEW_MAIL_TO`
- `AI_REVIEW_MAIL_FROM`
- `SMTP_USE_TLS`

### 10.3 推荐默认值

可以参考：

- `AI_REVIEW_MODEL=MiniMax-M2.5`
- `AI_AUDIT_MODEL=MiniMax-M2.5`
- `AI_REVIEW_MAX_FILES=12`
- `AI_REVIEW_MAX_PATCH_CHARS=60000`

## 11. 邮件通知如何验收

补齐 SMTP 配置后，`push` 一次代码即可。

验收标准：

1. `AI Code Review` workflow 成功
2. `notify-email` job 跑起来
3. 收件箱收到中文邮件
4. 邮件正文包含：
   - 仓库
   - 分支
   - commit
   - workflow 链接
   - 中文审查结果
   - 自动修复状态

## 12. 如何确认代码审查、自修复、定时巡查都跑通

### 12.1 审查跑通

看 GitHub Actions：

- `AI Code Review`

验收：

- workflow 为绿色成功
- reviewer 并行 job 都跑过
- coordinator 跑过
- commit 页面出现中文审查 comment

### 12.2 自修复跑通

看 GitHub Actions：

- `auto-fix`

验收：

- job 执行过
- 仓库里出现自动修复 PR
- PR 标题带 `AI 自动修复`

### 12.3 定时巡查跑通

看 GitHub Actions：

- `AI Repo Audit`

验收：

- workflow 为绿色成功
- 巡查 issue 被创建或更新
- issue 内容为中文巡查结果

## 13. 建议的公司复现顺序

推荐按这个顺序走，最稳：

1. 在 Mac 上跑 `sim` 模式，先验证 Docker 栈
2. 打开 `admin` 和 `dashboard`，确认有数据流
3. 在 GitHub 上确认 `AI Code Review` 和 `AI Repo Audit` 可用
4. 补齐 SMTP，确认中文邮件可收
5. Windows 上跑 `md_server.py`
6. Mac 上切换到 `SEED_MODE=tcp`
7. Redis 写入公司 `ctp_collect_url`
8. Redis 写入公司 `ctp_collect_auth`
9. 重启中继和 seed
10. 看 Dashboard 是否出现真实数据
11. 推一个小提交，确认中文审查 + 自动修复 PR + 邮件都触发

## 14. 常见问题

### 14.1 没有真实数据

优先检查：

- Windows 中继是否已启动
- Mac 是否能访问 Windows IP 和端口
- `SEED_MODE` 是否为 `tcp`
- Redis 中是否写入了正确 front
- 认证信息是否正确

### 14.2 审查 workflow 跑了但没邮件

检查：

- `AI_REVIEW_MAIL_TO` 是否已设置
- `SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD` 是否已设置
- SMTP 是否允许当前发信账号登录

### 14.3 自动修复没有出 PR

可能原因：

- 审查报告里没有明确可修的问题
- 生成了空变更
- 当前修改不适合自动修

### 14.4 公司 front 要求特殊认证

先优先尝试：

- `broker_id`
- `user_id`
- `password`
- `app_id`
- `auth_code`
- `user_product_info`

如果未来还要扩展更多字段，就继续在 [front_config.py](/e:/Develop/projects/ctp/runtime/front_config.py) 里往统一配置层加，不要散落到各入口脚本。

## 15. 最后建议

在公司环境里，不要把任何真实密钥、邮箱密码、交易认证信息提交进仓库。

推荐原则：

- GitHub 的审查密钥只放 Secrets
- CTP front 和认证优先放 Redis
- 需要临时覆盖时再用环境变量
- AI 自动修复只走 PR，不要直接自动合并主分支

如果后续继续扩展，这份文档就作为总入口维护，其他文档继续保留做专项说明。
