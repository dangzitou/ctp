# Java CTP 期货行情客户端

直接从 SimNow 获取全量 279 个期货合约的实时行情，纯 Java 标准库，无需任何外部 JAR 依赖。

## 架构

```
SimNow CTP (tcp://182.254.243.31:40011)
        ↓ 原始 TCP
md_server.py (Python 独立进程)
        ↓ TCP JSON (端口 19842)
MdServerClient.jar (Java TCP 客户端)  ← 你运行的
```

## 前置条件

**Step 1: 启动行情服务**（必须先运行）

```bash
# Windows
cd E:\Develop\projects\ctp\runtime\md_simnow
python md_server.py 19842

# 或 Linux/Mac
cd E:/Develop/projects/ctp/runtime/md_simnow
python md_server.py 19842
```

看到以下输出表示成功：
```
[CTP] Login OK. TradingDay=20xxxxx
[CTP] Subscribed 279 instruments
```

**Step 2: 运行 Java 客户端**

```bash
cd E:\Develop\projects\ctp\java_ctp_md
java -jar target\MdServerClient.jar
```

## 运行效果

```
==========================================
  CTP Market Data Client (Java TCP)
==========================================
  Connecting to: 127.0.0.1:19842
  Filter: ALL
==========================================

[Java] Connected to md_server
[Java] Receiving tick data...

[10:30:15.123] cu2605     | Last: 95650.00000 | Vol: 88508      | Bid: 95640.00000 | Ask: 95650.00000
[10:30:15.234] al2605     | Last: 24750.00000 | Vol: 290762     | Bid: 24750.00000 | Ask: 24755.00000
[10:30:15.456] rb2605     | Last: 3110.00000  | Vol: 574367     | Bid: 3109.00000  | Ask: 3110.00000
[10:30:15.789] sc2605     | Last: 701.10000   | Vol: 33009      | Bid: 701.00000   | Ask: 702.00000
...
```

## 参数说明

| 参数 | 说明 |
|------|------|
| 无参数 | 打印全量 279 合约的 tick |
| `cu` | 只打印包含 "cu" 的合约（如 cu2605, cu2606...） |

```bash
# 只看铜相关合约
java -jar target\MdServerClient.jar cu
```

## 编译

```bash
cd E:\Develop\projects\ctp\java_ctp_md
javac -d target/classes src/main/java/com/ctp/market/MdServerClient.java
jar -cfe target/MdServerClient.jar com.ctp.market.MdServerClient -C target/classes com
```

或用 Maven：
```bash
mvn package
```

## 覆盖的交易所和合约

| 交易所 | 合约数 |
|--------|--------|
| SHFE (上海期货) | ~50 |
| DCE (大连商品) | ~45 |
| CZCE (郑州商品) | 44 |
| CFFEX (金融期货) | 19 |
| INE (能源中心) | 8 |
| **合计** | **279** |

## 行情字段说明

| 字段 | 说明 |
|------|------|
| Last | 最新价 |
| Vol | 成交量 |
| Bid | 买价 |
| Ask | 卖价 |

另有 `openInterest`（持仓量）、`change`（涨跌额）、`changePct`（涨跌幅）可通过修改代码获取。
