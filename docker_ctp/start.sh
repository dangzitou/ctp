#!/bin/bash
# CTP 期货数据抓取系统 - Mac/Linux 一键启动
# 使用方法: ./start.sh

set -e

echo "=========================================="
echo "CTP 期货数据抓取系统"
echo "=========================================="

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检测操作系统
OS="$(uname -s)"
echo "检测到系统: $OS"

# 根据系统选择配置
if [ "$OS" = "Darwin" ] || [ "$OS" = "Linux" ]; then
    # Mac/Linux 使用标准端口
    if [ -f ".env.maclinux" ]; then
        cp .env.maclinux .env
        echo "使用 Mac/Linux 标准端口配置"
    fi
else
    # Windows 或其他 - 尝试标准端口，失败则用替代端口
    echo "检测到非 Mac/Linux 系统，使用默认配置"
fi

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装"
    echo "请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
fi

if ! docker ps &> /dev/null; then
    echo "❌ Docker 未运行"
    echo "请启动 Docker Desktop"
    exit 1
fi

echo "✅ Docker 已就绪"

# 启动 Docker 服务
echo ""
echo "📦 启动 Docker 服务..."
docker-compose up -d

echo "⏳ 等待服务启动 (30秒)..."
sleep 30

# 检查服务状态
echo ""
echo "🔍 检查服务状态..."
docker ps --filter "name=ctp-" --format "table {{.Names}}\t{{.Status}}" | grep ctp-

# 构建 Dashboard (如果还没有)
echo ""
echo "🔨 构建 Dashboard..."
cd dashboard
if [ ! -f "target/ctp-dashboard.jar" ]; then
    echo "编译 Dashboard..."
    mvn clean package -DskipTests -q
fi
cd ..

# 启动 Dashboard
echo ""
echo "🚀 启动 Dashboard..."
cd dashboard

# Mac/Linux 直接运行
java -jar target/ctp-dashboard.jar &
DASHBOARD_PID=$!
cd ..

# 等待 Dashboard 启动
echo "⏳ 等待 Dashboard 启动..."
for i in {1..15}; do
    if curl -s http://localhost:8080/api/stats > /dev/null 2>&1; then
        echo "✅ Dashboard 启动成功: http://localhost:8080/dashboard"
        break
    fi
    sleep 1
done

echo ""
echo "=========================================="
echo "✅ 服务已全部启动！"
echo ""
echo "Dashboard: http://localhost:8080/dashboard"
echo "API:       http://localhost:8080/api/stats"
echo ""
echo "Seed (CTP 数据源) 请在新终端运行:"
echo "  cd $SCRIPT_DIR/seed && python3 ctp_seed.py"
echo ""
echo "停止所有服务:"
echo "  pkill -f ctp-dashboard"
echo "  cd $SCRIPT_DIR && docker-compose down"
echo "=========================================="
