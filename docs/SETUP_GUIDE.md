# CTP 期货数据抓取系统 - Mac 部署指南

## 环境要求

| 软件 | 版本 | 说明 |
|------|------|------|
| Docker Desktop | 4.0+ | Mac 安装 https://www.docker.com/products/docker-desktop |
| Java | 17+ | Mac: `brew install openjdk@17` |
| Maven | 3.8+ | Mac: `brew install maven` |
| Python | 3.8+ | Mac 内置，或 `brew install python@3.11` |

## 一、安装依赖

```bash
# 1. 安装 Docker Desktop
# 下载: https://www.docker.com/products/docker-desktop/
# 安装后启动 Docker Desktop

# 2. 验证 Docker
docker --version
# Docker version 26.0.0, build xxx

# 3. 安装 Java 17
brew install openjdk@17
java -version
# openjdk version "17.0.x"

# 4. 安装 Maven
brew install maven
mvn --version
# Apache Maven 3.9.x

# 5. 安装 Python 依赖
pip3 install kafka-python flask
```

## 二、克隆项目

```bash
git clone https://github.com/dangzitou/ctp.git
cd ctp
```

## 三、启动 Docker 基础服务

```bash
cd docker_ctp

# 启动 Kafka + MySQL + Redis
docker-compose up -d kafka mysql redis

# 等待服务启动（约 30 秒）
sleep 30

# 验证服务状态
docker ps --filter "name=ctp-"
```

**预期输出：**
```
CONTAINER ID   IMAGE            STATUS
xxxx           apache/kafka     Up xx seconds
xxxx           mysql:8.0        Up xx seconds (healthy)
xxxx           redis:7-alpine   Up xx seconds (healthy)
```

**常见问题：**
- 端口被占用（3306/6379/9092）：
  ```bash
  # Mac 上修改 docker-compose.yml 端口映射
  # 找到 mysql 的 ports: "3307:3306"（改为其他端口如 3308）
  # 找到 redis 的 ports: "6380:6379"（改为其他端口如 6381）
  # 修改后重新启动
  docker-compose down
  docker-compose up -d
  ```

## 四、构建 Dashboard

```bash
cd ctp/docker_ctp/dashboard

# 构建 JAR
mvn clean package -DskipTests

# 验证 JAR 存在
ls -la target/*.jar
```

## 五、启动 Dashboard

```bash
# 在 ctp/docker_ctp/dashboard 目录执行
java -jar target/ctp-dashboard.jar \
  --spring.kafka.bootstrap-servers=localhost:9092 \
  --spring.data.redis.host=localhost \
  --spring.data.redis.port=6379 \
  --spring.datasource.url=jdbc:mysql://localhost:3306/ctp_futures \
  --spring.datasource.username=ctpuser \
  --spring.datasource.password=ctp123456
```

**注意：** Mac 上 Docker Desktop 的端口映射直接用 3306/6379（不是 Windows 的 3307/6380）

**验证启动成功：**
```bash
# 等待 15 秒后测试
curl http://localhost:8080/api/stats
# 预期: {"instruments":0,"websocket_clients":0}
```

## 六、启动 Seed（接收 CTP 数据）

```bash
cd ctp/docker_ctp/seed

# 运行
python3 ctp_seed.py
```

**预期输出：**
```
============================================================
CTP Seed -> Kafka Publisher
  CTP Front: tcp://182.254.243.31:40011
  Kafka: localhost:9092
  Topic: ctp-ticks
============================================================
[CTP] API loaded: x.x.x
[Kafka] kafka-python loaded
[Kafka] Connected to localhost:9092, topic=ctp-ticks
[CTP] Connected
[CTP] Login OK. TradingDay=20260404
[CTP] Subscribed 137 instruments
```

## 七、验证数据流

```bash
# 1. 检查 Kafka 收到数据
docker exec ctp-kafka bash -c '/opt/kafka/bin/kafka-console-consumer.sh --topic ctp-ticks --from-beginning --bootstrap-server localhost:9092 --timeout-ms 3000' | head -5

# 2. 检查 Dashboard 接收
curl http://localhost:8080/api/stats
# 预期: {"instruments":137,"websocket_clients":0}

# 3. 检查 Redis
docker exec ctp-redis redis-cli DBSIZE

# 4. 检查 MySQL
docker exec ctp-mysql mysql -uctpuser -pctp123456 -e "SELECT COUNT(*) FROM ctp_futures.ticks;"
```

## 八、访问 Dashboard

```
浏览器打开: http://localhost:8080/dashboard
```

## 九、完整停止

```bash
# 停止 Seed (Ctrl+C)

# 停止 Dashboard
pkill -f ctp-dashboard.jar

# 停止 Docker 服务
cd ctp/docker_ctp
docker-compose down
```

## 端口说明

| 服务 | Docker 内部端口 | Mac 访问端口 | 说明 |
|------|----------------|--------------|------|
| Kafka | 9092 | 9092 | Kafka broker |
| MySQL | 3306 | 3306 | MySQL 数据库 |
| Redis | 6379 | 6379 | Redis 缓存 |
| Dashboard | 8080 | 8080 | Web 服务 |

## 快速重启（第二次及以后）

```bash
# 1. 启动 Docker
cd ctp/docker_ctp
docker-compose up -d kafka mysql redis
sleep 20

# 2. 启动 Dashboard
cd ctp/docker_ctp/dashboard
java -jar target/ctp-dashboard.jar \
  --spring.kafka.bootstrap-servers=localhost:9092 \
  --spring.data.redis.host=localhost \
  --spring.data.redis.port=6379 \
  --spring.datasource.url=jdbc:mysql://localhost:3306/ctp_futures \
  --spring.datasource.username=ctpuser \
  --spring.datasource.password=ctp123456 &

# 3. 启动 Seed
cd ctp/docker_ctp/seed
python3 ctp_seed.py
```

## 故障排查

### 1. Dashboard 启动报错 "Redis connection refused"
```bash
# 确认 Redis 端口映射
docker ps | grep redis
# 应该显示: 0.0.0.0:6379->6379/tcp

# 如果端口不同，修改启动命令
--spring.data.redis.port=6379  # 改成实际端口
```

### 2. Dashboard 启动报错 "MySQL connection refused"
```bash
# 确认 MySQL 端口映射
docker ps | grep mysql
# 应该显示: 0.0.0.0:3306->3306/tcp

# 如果端口不同（如 3307），修改
--spring.datasource.url=jdbc:mysql://localhost:3307/ctp_futures
```

### 3. Kafka 报错 "Unknown topic"
```bash
# 创建 topic
docker exec ctp-kafka bash -c '/opt/kafka/bin/kafka-topics.sh --create --topic ctp-ticks --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1'
```

### 4. Seed 连接 CTP 超时
- 检查网络：SimNow 服务器可能维护中
- 尝试其他时段：交易时间 9:00-15:00, 21:00-23:00

### 5. Java 内存不足
```bash
# 增加 JVM 内存
java -Xmx2g -jar target/ctp-dashboard.jar ...
```
