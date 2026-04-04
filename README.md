# CTP Futures Data Capture System

全量期货实时行情数据抓取系统，支持 SimNow CTP 协议。

## 系统架构

```
SimNow CTP → Seed → Kafka → Dashboard (Spring Boot) → Redis + MySQL → 浏览器
                     ↓
              md_server.py (TCP中间件)
```

## 核心组件

| 组件 | 目录 | 说明 |
|------|------|------|
| **Docker 完整系统** | `docker_ctp/` | Kafka + Redis + MySQL + Dashboard |
| **Python Seed** | `docker_ctp/seed/` | 连接 SimNow CTP，推送到 Kafka |
| **Java Dashboard** | `docker_ctp/dashboard/` | Spring Boot + Kafka Consumer + WebSocket |
| **Python md_server** | `runtime/` | CTP TCP 中间件（Flask + 纯 TCP） |
| **Java CTP 客户端** | `java_ctp_md/` | Maven 项目连接 md_server |
| **Java Standalone** | `java_ctp_md_standalone/` | 可执行 JAR 版本 |

## 快速启动

### 1. 启动 Docker 基础服务

```bash
cd docker_ctp
docker-compose up -d kafka mysql redis
```

### 2. 启动 Dashboard

```bash
cd docker_ctp/dashboard
mvn package -DskipTests
java -jar target/ctp-dashboard.jar \
  --spring.kafka.bootstrap-servers=localhost:9094 \
  --spring.data.redis.host=localhost \
  --spring.data.redis.port=6380 \
  --spring.datasource.url=jdbc:mysql://localhost:3307/ctp_futures
```

### 3. 启动 Seed（Windows）

```bash
cd docker_ctp/seed
pip install kafka-python
python ctp_seed.py
```

### 4. 访问 Dashboard

- Dashboard: http://localhost:8080/dashboard
- WebSocket: ws://localhost:8080/ws/ticks
- API: http://localhost:8080/api/instruments

## API 接口

| 接口 | 说明 |
|------|------|
| `GET /api/instruments` | 所有合约最新行情 |
| `GET /api/tick/{instrumentId}` | 单个合约 tick |
| `GET /api/kline/{instrumentId}` | K 线数据（1 分钟） |
| `GET /api/stats` | 系统状态 |

## 数据流向

1. **SimNow CTP** (`tcp://182.254.243.31:40011`) - 免费 SimNow 行情
2. **ctp_seed.py** - 连接 SimNow，订阅全部合约，推送 JSON 到 Kafka
3. **Kafka** (`ctp-ticks` topic) - 消息队列
4. **Dashboard** - 消费 Kafka，存储 Redis + MySQL，WebSocket 推送
5. **浏览器** - WebSocket 接收实时数据，ECharts 渲染 K 线

## 支持交易所

- **SHFE** (上海期货) - cu, al, zn, pb, ni, sn, ss, au, ag, ru, bu, rb, hc, i, j, jm
- **DCE** (大连商品) - m, y, c, cs, p, a, b, l, pp, v, eb, eg, pg
- **CZCE** (郑州商品) - ma, ta, fg, pf, rm, sr, cf, cy, oi, wh, pm
- **CFFEX** (中金所) - if, ih, ic, im, tf, ts, t
- **INE** (上期能源) - sc, bc

## 技术栈

- **Kafka**: apache/kafka:latest (KRaft 模式)
- **Redis**: redis:7-alpine
- **MySQL**: mysql:8.0
- **Dashboard**: Spring Boot 3.2.3 + Java 21
- **Seed**: Python 3.8 + kafka-python

## 目录结构

```
ctp/
├── docker_ctp/
│   ├── docker-compose.yml      # Docker 编排
│   ├── sql/init.sql            # MySQL 初始化
│   ├── seed/                   # Python Seed
│   │   ├── ctp_seed.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── dashboard/              # Spring Boot Dashboard
│       ├── pom.xml
│       └── src/
├── runtime/
│   ├── dashboard/              # Flask Web Dashboard
│   ├── md_server.py            # TCP 中间件
│   └── md_simnow/              # CTP Python API
├── java_ctp_md/                # Java Maven 项目
└── java_ctp_md_standalone/     # Java 可执行版本
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CTP_FRONT` | tcp://182.254.243.31:40011 | SimNow 行情服务器 |
| `KAFKA_BOOTSTRAP_SERVERS` | localhost:9094 | Kafka 地址 |
| `KAFKA_TOPIC` | ctp-ticks | Kafka Topic |

## License

MIT
