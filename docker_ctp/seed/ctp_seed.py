"""
CTP Seed - Connects to SimNow CTP, publishes tick data to Kafka.
This runs on Windows (the host) because the CTP DLL is Windows-only.

Usage (on Windows):
    pip install -r requirements.txt
    python ctp_seed.py

The Kafka topic 'ctp-ticks' will be consumed by the dashboard Docker container.
"""
import sys
import os
import time
import json
import threading
from datetime import datetime
from collections import defaultdict

# Try to import CTP (Windows-only)
CTP_AVAILABLE = False
try:
    sys.path.insert(0, r"E:\Develop\projects\ctp\runtime\md_simnow")
    import thostmduserapi as mdapi
    CTP_AVAILABLE = True
    print(f"[CTP] API loaded: {mdapi.CThostFtdcMdApi.GetApiVersion()}")
except ImportError:
    print("[WARN] CTP API not available, using simulated data")

# Try Kafka
KAFKA_AVAILABLE = False
try:
    from kafka import KafkaProducer
    KAFKA_AVAILABLE = True
    print("[Kafka] kafka-python loaded")
except ImportError:
    print("[WARN] kafka-python not available")

# Config
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "ctp-ticks")
CTP_FRONT = os.environ.get("CTP_FRONT", "tcp://182.254.243.31:40011")


# Build instrument list (same as scan_contracts.py)
def build_instrument_list():
    all_instruments = set()
    shfe = [
        "cu2605","cu2606","cu2607","cu2608","cu2609","cu2610","cu2611","cu2612",
        "al2605","al2606","al2607","al2608","al2609","al2610","al2611","al2612",
        "zn2605","zn2606","zn2607","zn2608","zn2609","zn2610","zn2611","zn2612",
        "pb2605","pb2606","pb2607","pb2608","pb2609","pb2610","pb2611","pb2612",
        "ni2605","ni2606","ni2607","ni2608","ni2609","ni2610","ni2611","ni2612",
        "sn2605","sn2606","sn2607","sn2608","sn2609","sn2610","sn2611","sn2612",
        "ss2605","ss2606","ss2607","ss2608","ss2609","ss2610","ss2611","ss2612",
        "au2604","au2606","au2608","au2610","au2612",
        "ag2604","ag2606","ag2608","ag2610","ag2612",
        "ru2605","ru2606","ru2607","ru2608","ru2609","ru2610","ru2611","ru2612",
        "bu2605","bu2606","bu2607","bu2608","bu2609","bu2610","bu2611","bu2612",
        "rb2605","rb2606","rb2607","rb2608","rb2609","rb2610","rb2611","rb2612",
        "hc2605","hc2606","hc2607","hc2608","hc2609","hc2610","hc2611","hc2612",
        "i2605","i2606","i2607","i2608","i2609","i2610","i2611","i2612",
        "j2605","j2606","j2607","j2608","j2609","j2610","j2611","j2612",
        "jm2605","jm2606","jm2607","jm2608","jm2609","jm2610","jm2611","jm2612",
    ]
    all_instruments.update(shfe)
    dce = [
        "m2605","m2607","m2608","m2609","m2611","m2612",
        "y2605","y2607","y2608","y2609","y2611","y2612",
        "c2605","c2607","c2609","c2611","c2612",
        "cs2605","cs2607","cs2609","cs2611","cs2612",
        "p2605","p2607","p2608","p2609","p2610","p2611",
        "a2605","a2607","a2609","a2611",
        "b2605","b2607","b2609","b2611",
        "l2605","l2607","l2608","l2609","l2611","l2612",
        "pp2605","pp2606","pp2607","pp2608","pp2609","pp2610","pp2611","pp2612",
        "v2605","v2607","v2608","v2609","v2611","v2612",
        "eb2605","eb2606","eb2607","eb2608","eb2609","eb2610","eb2611","eb2612",
        "eg2605","eg2606","eg2607","eg2608","eg2609","eg2610","eg2611","eg2612",
        "pg2605","pg2606","pg2607","pg2608","pg2609","pg2610","pg2611","pg2612",
    ]
    all_instruments.update(dce)
    czce = [
        "ma2605","ma2607","ma2609","ma2611",
        "ta2605","ta2607","ta2609","ta2611",
        "fg2605","fg2607","fg2609","fg2611",
        "pf2605","pf2607","pf2609","pf2611",
        "rm2605","rm2607","rm2609","rm2611",
        "sr2605","sr2607","sr2609","sr2611",
        "cf2605","cf2607","cf2609","cf2611",
        "cy2605","cy2607","cy2609","cy2611",
        "oi2605","oi2607","oi2609","oi2611",
        "wh2605","wh2607","wh2609","wh2611",
        "pm2605","pm2607","pm2609","pm2611",
    ]
    all_instruments.update(czce)
    cffex = [
        "if2604","if2605","if2606","if2609",
        "ih2604","ih2605","ih2606","ih2609",
        "ic2604","ic2605","ic2606","ic2609",
        "im2604","im2605","im2606","im2609",
        "tf2606","tf2609","tf2612",
        "ts2606","ts2609","ts2612",
        "t2606","t2609","t2612",
    ]
    all_instruments.update(cffex)
    ine = [
        "sc2605","sc2606","sc2607","sc2608","sc2609","sc2610","sc2611","sc2612",
    ]
    all_instruments.update(ine)
    return list(all_instruments)


EXCHANGE_SUFFIXES = {
    "SHFE": ["cu","al","zn","pb","ni","sn","ss","au","ag","ru","bu","rb","hc","i","j","jm"],
    "DCE": ["m","y","c","cs","p","a","b","l","pp","v","eb","eg","pg"],
    "CZCE": ["ma","ta","fg","pf","rm","sr","cf","cy","oi","wh","pm"],
    "CFFEX": ["if","ih","ic","im","tf","ts","t"],
    "INE": ["sc","bc"],
}

def get_exchange(instrument_id):
    suffix = "".join(c for c in instrument_id if c.isalpha()).lower()
    for ex, prefixes in EXCHANGE_SUFFIXES.items():
        if suffix in prefixes:
            return ex
    return "UNKNOWN"


class CTPToKafka:
    """Connect to SimNow CTP, publish ticks to Kafka."""

    def __init__(self):
        self.base_prices = {}
        self.kafka = None
        self.tick_count = 0
        self.running = False

    def connect_kafka(self):
        if not KAFKA_AVAILABLE:
            print("[Kafka] Not available, skipping")
            return
        try:
            self.kafka = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=3,
                retry_backoff_ms=500,
            )
            print(f"[Kafka] Connected to {KAFKA_BOOTSTRAP}, topic={KAFKA_TOPIC}")
        except Exception as e:
            print(f"[Kafka] Connection failed: {e}, will retry...")
            self.kafka = None

    def publish(self, tick):
        if self.kafka is None:
            # Try reconnect
            self.connect_kafka()
            if self.kafka is None:
                return
        try:
            future = self.kafka.send(KAFKA_TOPIC, tick)
            future.get(timeout=1)
            self.tick_count += 1
            if self.tick_count % 100 == 0:
                print(f"[Kafka] Published {self.tick_count} ticks")
        except Exception as e:
            print(f"[Kafka] Send error: {e}")
            self.kafka = None

    def run_ctp(self):
        class Spi(mdapi.CThostFtdcMdSpi):
            def __init__(s):
                super().__init__()

            def OnFrontConnected(s):
                print("[CTP] Connected")
                req = mdapi.CThostFtdcReqUserLoginField()
                s.api.ReqUserLogin(req, 0)

            def OnFrontDisconnected(s, n):
                print(f"[CTP] Disconnected n={n}")

            def OnRspUserLogin(s, p, info, req, last):
                if info and info.ErrorID != 0:
                    print(f"[CTP] Login failed: {info.ErrorID} {info.ErrorMsg}")
                    return
                print(f"[CTP] Login OK. TradingDay={p.TradingDay}")
                codes = [c.encode() for c in build_instrument_list()]
                s.api.SubscribeMarketData(codes, len(codes))
                print(f"[CTP] Subscribed {len(codes)} instruments")

            def OnRtnDepthMarketData(s, p):
                iid = p.InstrumentID
                price = float(p.LastPrice) if p.LastPrice else 0
                vol = int(p.Volume) if p.Volume else 0
                bid = float(p.BidPrice1) if p.BidPrice1 else 0
                ask = float(p.AskPrice1) if p.AskPrice1 else 0
                oi = int(p.OpenInterest) if p.OpenInterest else 0
                ts = time.time()

                if iid not in self.base_prices:
                    self.base_prices[iid] = price
                base = self.base_prices[iid]
                change = price - base
                change_pct = (change / base * 100) if base else 0

                tick = {
                    "type": "tick",
                    "instrument_id": iid,
                    "exchange": get_exchange(iid),
                    "price": price,
                    "volume": vol,
                    "bid": bid,
                    "ask": ask,
                    "open_interest": oi,
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "timestamp": ts,
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trading_day": datetime.now().strftime("%Y-%m-%d"),
                }
                self.publish(tick)

        api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
        spi = Spi()
        spi.api = api
        api.RegisterFront(CTP_FRONT)
        api.RegisterSpi(spi)
        api.Init()
        print(f"[CTP] API started, front={CTP_FRONT}")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[CTP] Interrupted")
        finally:
            api.Release()
            if self.kafka:
                self.kafka.flush()
                self.kafka.close()

    def start(self):
        self.running = True
        self.connect_kafka()
        if CTP_AVAILABLE:
            self.run_ctp()
        else:
            print("[Seed] CTP not available, nothing to do")


if __name__ == "__main__":
    print("=" * 60)
    print("CTP Seed -> Kafka Publisher")
    print(f"  CTP Front: {CTP_FRONT}")
    print(f"  Kafka: {KAFKA_BOOTSTRAP}")
    print(f"  Topic: {KAFKA_TOPIC}")
    print("=" * 60)

    seed = CTPToKafka()
    try:
        seed.start()
    except KeyboardInterrupt:
        print("\n[Seed] Shutting down...")
        seed.running = False
