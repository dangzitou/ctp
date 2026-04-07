# CTP 期货数据抓取系统

全量期货实时行情数据抓取系统，支持 SimNow CTP 协议。

**支持交易所:** SHFE | DCE | CZCE | CFFEX | INE (共 137+ 合约)

## Quick Docs

Recommended entrypoints:

- Cross-platform Docker full-contract mode: `docker_ctp/.env.ha.akshare`
- Windows Docker real-data relay: `docker_ctp/start-real.ps1`
- HA deployment guide: `docs/HA_DEPLOYMENT.md`
- Mac operator guide: `docs/MAC_DOCKER_DEPLOYMENT.md`
- Market-data switching guide: `docs/DATA_INTERFACE_SWITCHING.md`

Recommended startup choices:

1. If you want the same Docker flow on Mac, Linux, and Windows, use `akshare` mode.
2. If you need a Windows-host real-data relay, use `start-real.ps1`.
3. If you are testing the HA stack first, start from `docs/HA_DEPLOYMENT.md`.

## 后人先看

如果你是第一次接手这个项目，建议按下面顺序理解：

1. 先确认你要的是哪种数据源：
   - `akshare` 模式：跨平台、全 Docker、Mac/Linux/Windows 都能跑。
   - `tcp` / Windows relay 模式：Windows 宿主机接真实 CTP 行情，实时性更接近流式。
2. 再确认你要看的入口：
   - 渲染好的 K 线页面：`http://localhost:18080/dashboard`
   - Kafka UI：`http://localhost:18082`
   - 原始 K 线接口：`http://localhost:18080/api/kline/AL2604`
3. 最后再去看扩展文档：
   - `docs/HA_DEPLOYMENT.md`
   - `docs/MAC_DOCKER_DEPLOYMENT.md`
   - `docs/DATA_INTERFACE_SWITCHING.md`

项目当前最推荐的默认启动方式是 `akshare + docker-compose.ha.yml`，因为这条路径最容易复现，也最适合后人接手。

## 推荐启动方式

### 方案 A：跨平台默认方案

适用场景：

- 想在 Mac / Linux / Windows 上用同一套 Docker 流程启动
- 想直接拉全量合约并在页面、Kafka、Redis、MySQL 中看数据
- 不依赖 Windows 本地 CTP DLL

启动命令：

```bash
cd docker_ctp
cp .env.ha.akshare .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

启动后重点访问：

- Dashboard: `http://localhost:18080`
- K 线图页面: `http://localhost:18080/dashboard`
- Kafka UI: `http://localhost:18082`

### 方案 B：Windows 真实 CTP relay

适用场景：

- 你在 Windows 上
- 你已经有可用的 CTP 柜台账号、密码、AppID、AuthCode
- 你需要比 AkShare 轮询更接近实时的行情流

启动命令：

```powershell
cd docker_ctp
.\start-real.ps1
```

启动前如果需要鉴权，先设置：

```powershell
$env:CTP_FRONT="tcp://your-front:port"
$env:CTP_BROKER_ID="your_broker"
$env:CTP_USER_ID="your_user"
$env:CTP_PASSWORD="your_password"
$env:CTP_APP_ID="your_app_id"
$env:CTP_AUTH_CODE="your_auth_code"
.\start-real.ps1
```

## 启动后验证清单

建议后人每次启动后都按这个顺序验证，不要只看容器是 `Up` 就认为成功：

1. 看容器状态

```bash
docker compose -f docker_ctp/docker-compose.ha.yml --env-file docker_ctp/.env.ha.local ps
```

2. 看页面入口

- K 线图页面：`http://localhost:18080/dashboard`
- Kafka UI：`http://localhost:18082`

3. 看接口是否出数

```bash
curl http://localhost:18080/api/kline/AL2604
curl http://localhost:18080/api/kline/CU2605
curl http://localhost:18080/api/stats
```

4. 看数据是否真的进了 MySQL

```bash
docker exec docker_ctp-mysql-1 mysql -uctpuser -pctp123456 -D ctp_futures -e "SELECT COUNT(*) AS cnt FROM klines_1min;"
```

5. 看 Kafka 是否真的有消息

直接打开 `http://localhost:18082` 查看 `ctp-ticks` topic。

## 真实数据说明

这里最容易被误解，单独写清楚：

- `akshare` 模式拿到的不是“模拟假数据”，而是真实市场快照数据。
- 但它不是交易所级别的逐笔推送，更接近轮询式、近实时行情。
- Windows relay / `tcp` 模式更接近真实流式 tick。
- 页面里的 K 线来自系统内部按 tick / 快照聚合后的 1 分钟线，并已落到 MySQL `klines_1min`。

## 页面和数据入口

推荐后人优先用下面这些入口排查，不要先翻代码：

- 渲染好的 K 线页面：`http://localhost:18080/dashboard`
- Dashboard 根页：`http://localhost:18080/`
- Kafka UI：`http://localhost:18082`
- 所有合约最新行情：`http://localhost:18080/api/instruments`
- 单合约 tick：`http://localhost:18080/api/tick/{instrumentId}`
- 单合约 K 线：`http://localhost:18080/api/kline/{instrumentId}`

已验证过的合约示例：

- 沪铝：`AL2604`
- 沪铜：`CU2605`

## 常见问题

### 1. 页面打开了，但一开始没有合约列表或 tick

这不一定是故障。

- 某些启动阶段下，`/api/instruments` 和 `/api/tick/*` 可能会比 `/api/kline/*` 更晚热起来。
- 当前页面已经做了兜底：即使列表暂时没热，也会优先展示 `AL2604` 和 `CU2605` 的 K 线。
- 判断系统是否真的有数据，请优先看 `/api/kline/*`、Kafka UI 和 MySQL 表，而不是只盯着首页第一秒的列表状态。

### 2. Docker 都启动了，但 `/dashboard` 是 404

这通常说明 Dashboard 静态资源没有被正确打进 jar。

当前版本已经把页面放到了 Spring Boot 标准静态目录：

- `docker_ctp/dashboard/src/main/resources/static/dashboard.html`

如果后人又改了前端目录结构，先检查这个问题。

### 3. 为什么看到 K 线，但 `/api/tick/{instrumentId}` 偶尔是 `not found`

这通常是缓存热身和消费时序问题，不一定代表整条链路坏了。

排查顺序：

1. 先看 `/api/kline/{instrumentId}` 是否有数据
2. 再看 `http://localhost:18082` 的 `ctp-ticks` topic 是否有消息
3. 最后看 Dashboard 日志

### 4. Mac / Linux 能不能直接跑

可以，优先用 `akshare` 模式。  
不要指望 Windows CTP DLL 方案能直接跨平台。

### 5. 页面里的 K 线是什么粒度

后端原始接口当前提供的是 1 分钟 K 线。  
页面上的 `5M / 15M / 30M / 1H / 1D` 是前端基于 1 分钟线聚合出来的展示周期。

## 系统架构

```
SimNow CTP → Seed → Kafka → Dashboard → Redis + MySQL → 浏览器
```

## 快速启动 (Mac/Linux)

### 1. 克隆项目

```bash
git clone https://github.com/dangzitou/ctp.git
cd ctp
```

### 2. 一键启动

```bash
cd docker_ctp

# 启动 Docker 服务
docker-compose up -d

# 等待 30 秒
sleep 30

# 编译并启动 Dashboard
cd dashboard
mvn clean package -DskipTests
java -jar target/ctp-dashboard.jar &

# 返回上级目录
cd ..
```

### 3. 启动 Seed (接收行情)

```bash
cd docker_ctp/seed
pip3 install kafka-python
python3 ctp_seed.py
```

### 4. 访问

- Dashboard: http://localhost:8080/dashboard
- API: http://localhost:8080/api/stats

## Mac/Linux 详细安装步骤

### 安装依赖

```bash
# Docker Desktop
# https://www.docker.com/products/docker-desktop

# Java 17
brew install openjdk@17

# Maven
brew install maven

# Python 依赖
pip3 install kafka-python flask
```

### 启动顺序

```bash
# 1. 启动 Docker 服务
cd docker_ctp
docker-compose up -d

# 2. 等待服务就绪
sleep 30

# 3. 编译 Dashboard
cd dashboard
mvn clean package -DskipTests

# 4. 启动 Dashboard (后台)
java -jar target/ctp-dashboard.jar &

# 5. 启动 Seed
cd ../seed
python3 ctp_seed.py
```

## Windows 启动

```bash
cd docker_ctp

# Windows 端口配置 (已自动选择)
docker-compose up -d

# 启动 Dashboard
cd dashboard
java -jar target/ctp-dashboard.jar ^
  --spring.kafka.bootstrap-servers=localhost:9094 ^
  --spring.data.redis.host=localhost ^
  --spring.data.redis.port=6380 ^
  --spring.datasource.url=jdbc:mysql://localhost:3307/ctp_futures ^
  --spring.datasource.username=ctpuser ^
  --spring.datasource.password=ctp123456

# 启动 Seed
cd ../seed
python ctp_seed.py
```

## Windows Docker 真数据启动

如果你要在 Windows 上通过 Docker 直接看真实 CTP 行情，推荐走 HA 栈 + host relay：

```powershell
cd docker_ctp
.\start-real.ps1
```

这个脚本会做两件事：

1. 复制 Windows 专用 `docker_ctp/.env.ha.windows` 到 `docker_ctp/.env.ha.local`
2. 在宿主机启动 `runtime\md_tts\md_server.py`，并让 Docker 中的 `seed` 容器通过 `host.docker.internal:19842` 接入真实 tick

访问地址：

- Dashboard: `http://localhost:18080`
- Admin: `http://localhost:18081`
- Kafka UI: `http://localhost:18082`
- K 线图页面: `http://localhost:18080/dashboard` 或 `http://localhost:18080/dashboard.html`

如果你的 CTP 柜台需要账号、密码、AppID、AuthCode，请在启动前先设置环境变量，或写入 Redis 控制面：

```powershell
$env:CTP_FRONT="tcp://your-front:port"
$env:CTP_BROKER_ID="your_broker"
$env:CTP_USER_ID="your_user"
$env:CTP_PASSWORD="your_password"
$env:CTP_APP_ID="your_app_id"
$env:CTP_AUTH_CODE="your_auth_code"
.\start-real.ps1
```

## Docker 中用 AkShare 拉全合约

如果你要在 Docker 里直接拉取当前全部可交易期货合约，并且希望 Mac/Linux 也能跑，推荐使用 `akshare` 模式：

```bash
cd docker_ctp
cp .env.ha.akshare .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

这个模式的特点：

- `akshare` 在 `seed` 容器内部运行，不依赖 Windows DLL
- 适合 Mac/Linux 直接部署
- 默认强制使用 `linux/amd64` 镜像平台，兼容 Intel Mac、Apple Silicon Mac、Windows Docker Desktop，以及常见 x86_64 Linux
- 会按品种抓取当前全部可交易合约，再推送到 Kafka / Redis / Dashboard

默认参数在 `docker_ctp/.env.ha.akshare`：

- `DOCKER_PLATFORM=linux/amd64`
- `SEED_MODE=akshare`
- `AKSHARE_REFRESH_SEC=30`
- `AKSHARE_INCLUDE_CONTINUOUS=0`
- `AKSHARE_SYMBOL_LIMIT=0`

访问地址：

- Dashboard: `http://localhost:18080`
- Admin: `http://localhost:18081`
- Kafka UI: `http://localhost:18082`
- K 线图页面: `http://localhost:18080/dashboard` 或 `http://localhost:18080/dashboard.html`

如果你在 ARM Linux 主机上运行，并且本机没有配置 `amd64` 仿真支持，可以把 `DOCKER_PLATFORM` 改成宿主机支持的平台后再测试；当前仓库优先保证 Docker Desktop 场景可直接启动。

## 端口配置

| 服务 | Mac/Linux | Windows | 说明 |
|------|-----------|---------|------|
| Kafka | 9092 | 9094 | Kafka broker |
| MySQL | 3306 | 3307 | MySQL 数据库 |
| Redis | 6379 | 6380 | Redis 缓存 |
| Dashboard | 8080 | 8080 | Web 服务 |

**Mac/Linux 用户**: 使用 `.env.maclinux` 配置
```bash
cp .env.maclinux .env
docker-compose up -d
```

## API 接口

| 接口 | 说明 |
|------|------|
| `GET /api/instruments` | 所有合约最新行情 |
| `GET /api/tick/{instrumentId}` | 单个合约 tick |
| `GET /api/kline/{instrumentId}` | K 线数据（1 分钟） |
| `GET /api/stats` | 系统状态 |

## 停止服务

```bash
# 停止 Dashboard
pkill -f ctp-dashboard

# 停止 Docker
docker-compose down
```

## 目录结构

```
ctp/
├── docker_ctp/
│   ├── docker-compose.yml   # Docker 编排
│   ├── .env                 # 端口配置
│   ├── .env.maclinux       # Mac/Linux 配置
│   ├── .env.windows        # Windows 配置
│   ├── start.sh            # Mac/Linux 启动脚本
│   ├── sql/init.sql        # MySQL 初始化
│   ├── seed/               # Python Seed
│   └── dashboard/           # Spring Boot Dashboard
├── runtime/                # Python 版本
└── docs/
    └── SETUP_GUIDE.md      # 详细部署指南
```

## 技术栈

- **Kafka**: apache/kafka:latest (KRaft 模式)
- **Redis**: redis:7-alpine
- **MySQL**: mysql:8.0
- **Dashboard**: Spring Boot 3.2.3 + Java 17
- **Seed**: Python 3.8 + kafka-python

## SimNow 说明

本系统使用 SimNow 仿真交易系统（免费，无需注册）：

| 参数 | 值 |
|------|------|
| 行情服务器 | `tcp://182.254.243.31:40011` |
| 交易服务器 | `tcp://182.254.243.31:40001` |
| BrokerID | `9999` |

**注意**: 这是仿真环境，不是真实交易。

## 故障排查

### Dashboard 连接 Redis 失败
```bash
# 检查 Redis 端口
docker ps | grep redis
# Mac: 0.0.0.0:6379->6379/tcp
# Windows: 0.0.0.0:6380->6379/tcp
```

### Dashboard 连接 MySQL 失败
```bash
# 检查 MySQL 端口
docker ps | grep mysql
# Mac: 0.0.0.0:3306->3306/tcp
# Windows: 0.0.0.0:3307->3306/tcp
```

### Kafka Topic 不存在
```bash
docker exec ctp-kafka bash -c '/opt/kafka/bin/kafka-topics.sh --create --topic ctp-ticks --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1'
```
