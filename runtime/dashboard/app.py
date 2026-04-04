"""
Flask + SocketIO server for futures dashboard.
Receives real-time ticks from md_server.py via TCP, broadcasts via SocketIO.

To use real CTP data:
1. Start md_server.py: python md_server.py
2. Start this app: python app.py

Demo mode runs without md_server.py.
"""

import os
import sys
import json
import time
import random
import socket
import threading
from datetime import datetime
from collections import defaultdict

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import pandas as pd

app = Flask(__name__)
app.config["SECRET_KEY"] = "ctp-dashboard-secret-2024"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global state
instruments = {}  # instrument_id -> data
kline_data = defaultdict(lambda: defaultdict(list))  # instrument_id -> period -> [(ts, o, h, l, c, v)]
tick_cache = {}
demo_mode = True
running = True
connected_clients = set()

# MDServer connection (receives ticks from real CTP)
MD_SERVER_HOST = "127.0.0.1"
MD_SERVER_PORT = 19842


def get_exchange(instrument_id):
    """Determine exchange from instrument ID."""
    suffix = "".join([c for c in instrument_id if c.isalpha()]).lower()
    EXCHANGE_SUFFIXES = {
        "SHFE": ["cu","al","zn","pb","ni","sn","ss","au","ag","ru","bu","rb","hc","i","j","jm"],
        "DCE": ["m","y","c","cs","p","a","b","l","pp","v","eb","eg","pg"],
        "CZCE": ["ma","ta","fg","pf","rm","sr","cf","cy","oi","wh","pm"],
        "CFFEX": ["if","ih","ic","im","tf","ts","t"],
        "INE": ["sc","bc"],
    }
    for ex, prefixes in EXCHANGE_SUFFIXES.items():
        if suffix in prefixes:
            return ex
    return "UNKNOWN"


# All known instruments - imported from scan_contracts.py (verified 279 contracts)
# Used to pre-populate the instruments dict so CZCE/CFFEX show even when market is closed
ALL_KNOWN_INSTRUMENTS = [
    'rb2605','rb2606','rb2607','rb2608','rb2609','rb2610','rb2611','rb2612',
    'hc2605','hc2606','hc2607','hc2608','hc2609','hc2610','hc2611','hc2612',
    'i2605','i2606','i2607','i2608','i2609','i2610','i2611','i2612',
    'j2605','j2606','j2607','j2608','j2609','j2610','j2611','j2612',
    'jm2605','jm2606','jm2607','jm2608','jm2609','jm2610','jm2611','jm2612',
    'cu2605','cu2606','cu2607','cu2608','cu2609','cu2610','cu2611','cu2612',
    'al2605','al2606','al2607','al2608','al2609','al2610','al2611','al2612',
    'zn2605','zn2606','zn2607','zn2608','zn2609','zn2610','zn2611','zn2612',
    'pb2605','pb2606','pb2607','pb2608','pb2609','pb2610','pb2611','pb2612',
    'ni2605','ni2606','ni2607','ni2608','ni2609','ni2610','ni2611','ni2612',
    'sn2605','sn2606','sn2607','sn2608','sn2609','sn2610','sn2611','sn2612',
    'ss2605','ss2606','ss2607','ss2608','ss2609','ss2610','ss2611','ss2612',
    'au2604','au2606','au2608','au2610','au2612',
    'ag2604','ag2606','ag2608','ag2610','ag2612',
    'sc2605','sc2606','sc2607','sc2608','sc2609','sc2610','sc2611','sc2612',
    'ru2605','ru2606','ru2607','ru2608','ru2609','ru2610','ru2611','ru2612',
    'bu2605','bu2606','bu2607','bu2608','bu2609','bu2610','bu2611','bu2612',
    'pg2605','pg2606','pg2607','pg2608','pg2609','pg2610','pg2611','pg2612',
    'eb2605','eb2606','eb2607','eb2608','eb2609','eb2610','eb2611','eb2612',
    'eg2605','eg2606','eg2607','eg2608','eg2609','eg2610','eg2611','eg2612',
    'ma2605','ma2607','ma2609','ma2611',
    'ta2605','ta2607','ta2609','ta2611',
    'fg2605','fg2607','fg2609','fg2611',
    'pf2605','pf2607','pf2609','pf2611',
    'rm2605','rm2607','rm2609','rm2611',
    'sr2605','sr2607','sr2609','sr2611',
    'cf2605','cf2607','cf2609','cf2611',
    'cy2605','cy2607','cy2609','cy2611',
    'oi2605','oi2607','oi2609','oi2611',
    'wh2605','wh2607','wh2609','wh2611',
    'pm2605','pm2607','pm2609','pm2611',
    'm2605','m2607','m2608','m2609','m2611','m2612',
    'y2605','y2607','y2608','y2609','y2611','y2612',
    'c2605','c2607','c2609','c2611','c2612',
    'cs2605','cs2607','cs2609','cs2611','cs2612',
    'p2605','p2607','p2608','p2609','p2610','p2611',
    'a2605','a2607','a2609','a2611',
    'b2605','b2607','b2609','b2611',
    'l2605','l2607','l2608','l2609','l2611','l2612',
    'pp2605','pp2606','pp2607','pp2608','pp2609','pp2610','pp2611','pp2612',
    'v2605','v2607','v2608','v2609','v2611','v2612',
    'if2604','if2605','if2606','if2609',
    'ih2604','ih2605','ih2606','ih2609',
    'ic2604','ic2605','ic2606','ic2609',
    'im2604','im2605','im2606','im2609',
    'tf2606','tf2609','tf2612',
    'ts2606','ts2609','ts2612',
    't2606','t2609','t2612',
]


def _init_all_instruments():
    """Pre-populate instruments dict with all 279 known instruments so CZCE/CFFEX
    show in the list even when market is closed (no ticks at night)."""
    for iid in ALL_KNOWN_INSTRUMENTS:
        if iid not in instruments:
            instruments[iid] = {
                "name": iid,
                "exchange": get_exchange(iid),
                "last_price": 0.0,
                "open_price": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "volume": 0,
                "open_interest": 0,
                "bid_price1": 0.0,
                "ask_price1": 0.0,
                "update_time": "",
            }


# Initialize all known instruments immediately at module load
_init_all_instruments()


def get_instruments_list():
    result = []
    for iid, info in instruments.items():
        result.append({
            "instrument_id": iid,
            "name": info.get("name", iid),
            "exchange": info.get("exchange", ""),
            "last_price": info.get("last_price", 0.0),
            "change": info.get("change", 0.0),
            "change_pct": info.get("change_pct", 0.0),
            "volume": info.get("volume", 0),
            "open_interest": info.get("open_interest", 0),
            "bid_price1": info.get("bid_price1", 0.0),
            "ask_price1": info.get("ask_price1", 0.0),
            "update_time": info.get("update_time", ""),
        })
    return result


def update_kline_from_tick(instrument_id, price, volume, timestamp):
    if not price or price <= 0:
        return
    ts_minute = int(timestamp // 60) * 60
    periods = {
        "1min": 60, "5min": 300, "15min": 900,
        "30min": 1800, "1hour": 3600, "1day": 86400,
    }
    for period_name, period_seconds in periods.items():
        period_ts = int(ts_minute // period_seconds) * period_seconds
        klines = kline_data[instrument_id][period_name]
        if not klines or klines[-1][0] < period_ts:
            klines.append([period_ts, price, price, price, price, volume])
        else:
            k = klines[-1]
            k[2] = max(k[2], price)
            k[3] = min(k[3], price)
            k[4] = price
            k[5] += volume


def process_tick(instrument_id, price, volume, bid, ask, oi=0, change=0, change_pct=0):
    ts = time.time()
    exchange = get_exchange(instrument_id)
    now = datetime.now().strftime("%H:%M:%S")

    if instrument_id not in instruments:
        instruments[instrument_id] = {
            "name": instrument_id,
            "exchange": exchange,
            "last_price": price,
            "open_price": price,
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "open_interest": oi,
            "bid_price1": bid,
            "ask_price1": ask,
            "update_time": now,
        }
    else:
        open_price = instruments[instrument_id].get("open_price", price)
        instruments[instrument_id].update({
            "last_price": price,
            "change": price - open_price,
            "change_pct": ((price - open_price) / open_price * 100) if open_price else 0,
            "volume": volume,
            "open_interest": oi,
            "bid_price1": bid,
            "ask_price1": ask,
            "update_time": now,
        })

    update_kline_from_tick(instrument_id, price, volume, ts)

    tick_cache[instrument_id] = {
        "instrument_id": instrument_id,
        "price": price,
        "volume": volume,
        "bid": bid,
        "ask": ask,
        "timestamp": ts,
    }

    socketio.emit("tick", {
        "instrument_id": instrument_id,
        "price": price,
        "volume": volume,
        "bid": bid,
        "ask": ask,
        "change": round(price - instruments[instrument_id].get("open_price", price), 2),
        "change_pct": round(((price - instruments[instrument_id].get("open_price", price)) / instruments[instrument_id].get("open_price", price) * 100) if instruments[instrument_id].get("open_price", price) else 0, 2),
        "timestamp": ts,
        "update_time": now,
    })


def get_kline(instrument_id, period="1min", from_ts=None, limit=500):
    klines = kline_data[instrument_id][period]
    if from_ts:
        klines = [k for k in klines if k[0] >= from_ts]
    return klines[-limit:]


# ============== Demo Data Generator ==============
class DemoDataGenerator:
    """Simulated market data - used when md_server is unavailable."""

    def __init__(self):
        self.running = True
        self.prices = {}
        self._init_prices()

    def _init_prices(self):
        base_prices = {
            # SHFE
            "cu2605": 72500,"cu2606": 72300,"cu2607": 72100,"cu2608": 71900,"cu2609": 71700,"cu2610": 71500,"cu2611": 71300,"cu2612": 71100,
            "al2605": 18200,"al2606": 18180,"al2607": 18160,"al2608": 18140,"al2609": 18120,"al2610": 18100,"al2611": 18080,"al2612": 18060,
            "zn2605": 21500,"zn2606": 21450,"zn2607": 21400,"zn2608": 21350,"zn2609": 21300,"zn2610": 21250,"zn2611": 21200,"zn2612": 21150,
            "pb2605": 16500,"pb2606": 16480,"pb2607": 16460,"pb2608": 16440,"pb2609": 16420,"pb2610": 16400,"pb2611": 16380,"pb2612": 16360,
            "ni2605": 128000,"ni2606": 127500,"ni2607": 127000,"ni2608": 126500,"ni2609": 126000,"ni2610": 125500,"ni2611": 125000,"ni2612": 124500,
            "sn2605": 178000,"sn2606": 177500,"sn2607": 177000,"sn2608": 176500,"sn2609": 176000,"sn2610": 175500,"sn2611": 175000,"sn2612": 174500,
            "ss2605": 13500,"ss2606": 13480,"ss2607": 13460,"ss2608": 13440,"ss2609": 13420,"ss2610": 13400,"ss2611": 13380,"ss2612": 13360,
            "au2604": 540,"au2606": 542,"au2608": 544,"au2610": 546,"au2612": 548,
            "ag2604": 6800,"ag2606": 6820,"ag2608": 6840,"ag2610": 6860,"ag2612": 6880,
            "ru2605": 12500,"ru2606": 12480,"ru2607": 12460,"ru2608": 12440,"ru2609": 12420,"ru2610": 12400,"ru2611": 12380,"ru2612": 12360,
            "bu2605": 3800,"bu2606": 3780,"bu2607": 3760,"bu2608": 3740,"bu2609": 3720,"bu2610": 3700,"bu2611": 3680,"bu2612": 3660,
            "rb2605": 3600,"rb2606": 3590,"rb2607": 3580,"rb2608": 3570,"rb2609": 3560,"rb2610": 3550,"rb2611": 3540,"rb2612": 3530,
            "hc2605": 3700,"hc2606": 3690,"hc2607": 3680,"hc2608": 3670,"hc2609": 3660,"hc2610": 3650,"hc2611": 3640,"hc2612": 3630,
            "i2605": 820,"i2606": 815,"i2607": 810,"i2608": 805,"i2609": 800,"i2610": 795,"i2611": 790,"i2612": 785,
            "j2605": 1950,"j2606": 1945,"j2607": 1940,"j2608": 1935,"j2609": 1930,"j2610": 1925,"j2611": 1920,"j2612": 1915,
            "jm2605": 1550,"jm2606": 1545,"jm2607": 1540,"jm2608": 1535,"jm2609": 1530,"jm2610": 1525,"jm2611": 1520,"jm2612": 1515,
            # DCE
            "m2605": 3200,"m2607": 3180,"m2608": 3160,"m2609": 3140,"m2611": 3120,"m2612": 3100,
            "y2605": 7200,"y2607": 7180,"y2608": 7140,"y2609": 7120,"y2611": 7100,"y2612": 7080,
            "c2605": 2450,"c2607": 2440,"c2609": 2430,"c2611": 2420,"c2612": 2410,
            "cs2605": 2650,"cs2607": 2640,"cs2609": 2630,"cs2611": 2620,"cs2612": 2610,
            "p2605": 6800,"p2607": 6760,"p2608": 6740,"p2609": 6720,"p2610": 6700,"p2611": 6680,
            "a2605": 4200,"a2607": 4180,"a2609": 4160,"a2611": 4140,"a2612": 4120,
            "b2605": 3800,"b2607": 3790,"b2609": 3780,"b2611": 3770,"b2612": 3760,
            "l2605": 8100,"l2607": 8060,"l2608": 8040,"l2609": 8020,"l2611": 8000,"l2612": 7980,
            "pp2605": 7500,"pp2606": 7480,"pp2607": 7460,"pp2608": 7440,"pp2609": 7420,"pp2610": 7400,"pp2611": 7380,"pp2612": 7360,
            "v2605": 5800,"v2607": 5760,"v2608": 5740,"v2609": 5720,"v2611": 5700,"v2612": 5680,
            "eb2605": 8200,"eb2606": 8180,"eb2607": 8160,"eb2608": 8140,"eb2609": 8120,"eb2610": 8100,"eb2611": 8080,"eb2612": 8060,
            "eg2605": 4100,"eg2606": 4080,"eg2607": 4060,"eg2608": 4040,"eg2609": 4020,"eg2610": 4000,"eg2611": 3980,"eg2612": 3960,
            "pg2605": 4800,"pg2606": 4780,"pg2607": 4760,"pg2608": 4740,"pg2609": 4720,"pg2610": 4700,"pg2611": 4680,"pg2612": 4660,
            # CZCE
            "ma2605": 2500,"ma2607": 2480,"ma2609": 2460,"ma2611": 2440,
            "ta2605": 5800,"ta2607": 5750,"ta2609": 5700,"ta2611": 5650,
            "fg2605": 1400,"fg2607": 1390,"fg2609": 1380,"fg2611": 1370,
            "pf2605": 7200,"pf2607": 7150,"pf2609": 7100,"pf2611": 7050,
            "rm2605": 2800,"rm2607": 2780,"rm2609": 2760,"rm2611": 2740,
            "sr2605": 6400,"sr2607": 6350,"sr2609": 6300,"sr2611": 6250,
            "cf2605": 16500,"cf2607": 16400,"cf2609": 16300,"cf2611": 16200,
            "cy2605": 21000,"cy2607": 20900,"cy2609": 20800,"cy2611": 20700,
            "oi2605": 8200,"oi2607": 8150,"oi2609": 8100,"oi2611": 8050,
            "wh2605": 2800,"wh2607": 2780,"wh2609": 2760,"wh2611": 2740,
            "pm2605": 2600,"pm2607": 2580,"pm2609": 2560,"pm2611": 2540,
            # CFFEX
            "if2604": 3600,"if2605": 3610,"if2606": 3620,"if2609": 3630,
            "ih2604": 2450,"ih2605": 2460,"ih2606": 2470,"ih2609": 2480,
            "ic2604": 5200,"ic2605": 5220,"ic2606": 5240,"ic2609": 5260,
            "im2604": 5800,"im2605": 5820,"im2606": 5840,"im2609": 5860,
            "tf2606": 102,"tf2609": 101.5,"tf2612": 101,
            "ts2606": 102.5,"ts2609": 102,"ts2612": 101.5,
            "t2606": 101,"t2609": 100.5,"t2612": 100,
            # INE
            "sc2605": 580,"sc2606": 582,"sc2607": 584,"sc2608": 586,"sc2609": 588,"sc2610": 590,"sc2611": 592,"sc2612": 594,
        }
        self.prices = base_prices

    def generate_tick(self, instrument_id):
        if instrument_id not in self.prices:
            self.prices[instrument_id] = random.uniform(1000, 10000)
        base = self.prices[instrument_id]
        change = random.uniform(-0.002, 0.002) * base
        price = base + change
        self.prices[instrument_id] = price
        spread = price * 0.0001
        return price, price - spread, price + spread

    def start(self):
        def run():
            instruments_list = list(self.prices.keys())
            while self.running:
                for _ in range(random.randint(1, 8)):
                    iid = random.choice(instruments_list)
                    price, bid, ask = self.generate_tick(iid)
                    volume = random.randint(1, 100)
                    process_tick(iid, price, volume, bid, ask)
                time.sleep(random.uniform(0.1, 0.3))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()


demo_generator = None


# ============== MDServer TCP Client ==============
class MDServerClient:
    """Connect to md_server.py TCP port, receive ticks."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[MDClient] Connecting to md_server at {self.host}:{self.port}")

    def _run(self):
        while self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10.0)
                self.sock.connect((self.host, self.port))
                print("[MDClient] Connected to md_server")
                self.sock.settimeout(30.0)
                buffer = ""
                while self.running:
                    try:
                        data = self.sock.recv(8192)
                        if not data:
                            break
                        buffer += data.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line.startswith("TICK:"):
                                tick = json.loads(line[5:])
                                self._handle_tick(tick)
                    except socket.timeout:
                        continue
            except Exception as e:
                print(f"[MDClient] Connection error: {e}")
                if self.running:
                    time.sleep(3)
            finally:
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None

    def _handle_tick(self, tick):
        iid = tick["instrument_id"]
        price = tick["price"]
        volume = tick["volume"]
        bid = tick["bid"]
        ask = tick["ask"]
        oi = tick.get("open_interest", 0)
        change = tick.get("change", 0)
        change_pct = tick.get("change_pct", 0)
        process_tick(iid, price, volume, bid, ask, oi, change, change_pct)

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()


md_client = None


def start_md_client():
    """Try to connect to md_server. Falls back to demo mode."""
    global md_client, demo_mode
    md_client = MDServerClient(MD_SERVER_HOST, MD_SERVER_PORT)

    # Test connection - give it 5 seconds to connect
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.settimeout(3)
    try:
        test_sock.connect((MD_SERVER_HOST, MD_SERVER_PORT))
        test_sock.close()
        print("[MDClient] md_server is available - using real CTP data")
        md_client.start()
        demo_mode = False
        return
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(f"[MDClient] md_server not available ({e}) - using demo mode")
        demo_mode = True
        global demo_generator
        demo_generator = DemoDataGenerator()
        demo_generator.start()


# ============== Flask Routes ==============
@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/instruments")
def api_instruments():
    return jsonify(get_instruments_list())

@app.route("/api/kline/<instrument_id>/<period>")
def api_kline(instrument_id, period):
    valid_periods = ["1min", "5min", "15min", "30min", "1hour", "1day"]
    if period not in valid_periods:
        return jsonify({"error": "Invalid period"}), 400
    return jsonify(get_kline(instrument_id, period))

@app.route("/api/demo/status")
def api_demo_status():
    return jsonify({"demo_mode": demo_mode})


# ============== SocketIO Events ==============
@socketio.on("connect")
def on_connect():
    print(f"Client connected: {request.sid}")
    connected_clients.add(request.sid)
    emit("instruments_update", get_instruments_list())
    emit("connected", {"status": "ok", "demo_mode": demo_mode})

@socketio.on("disconnect")
def on_disconnect():
    print("Client disconnected")
    connected_clients.discard(request.sid)


# ============== Init ==============
start_md_client()

if __name__ == "__main__":
    print("=" * 60)
    print("CTP Futures Dashboard Server")
    print("=" * 60)
    print(f"MDServer: {MD_SERVER_HOST}:{MD_SERVER_PORT}")
    print(f"Demo Mode: {demo_mode}")
    print(f"Access: http://localhost:5000")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
