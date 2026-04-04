# CTP 期货数据抓取系统

全量期货实时行情数据抓取系统，支持 SimNow CTP 协议。

**支持交易所:** SHFE | DCE | CZCE | CFFEX | INE (共 137+ 合约)

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
