"""
CTP Market Data Bridge - runs CTP in subprocess, communicates via stdout JSON.
This avoids the segfault from running CTP DLL inside Flask's threading model.
"""
import sys
import time
import json
import subprocess
import threading
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime.front_config import resolve_ctp_connection

# CTP API path
SIMNOW_MD_PATH = r"E:/Develop/projects/ctp/runtime/md_simnow"

DEFAULT_FRONT = "tcp://182.254.243.31:40011"

# Build instrument list
def build_instrument_list():
    all_instruments = set()
    # SHFE
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
    # DCE
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
    # CZCE
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
    # CFFEX
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
    # INE
    ine = [
        "sc2605","sc2606","sc2607","sc2608","sc2609","sc2610","sc2611","sc2612",
    ]
    all_instruments.update(ine)
    return list(all_instruments)


class CTPBridge:
    """Run CTP MD in subprocess, parse JSON output for ticks."""

    def __init__(self):
        self.process = None
        self.running = False
        self.base_prices = {}

    def start(self):
        """Start the CTP subprocess bridge."""
        self.running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        print("[Bridge] CTP subprocess started")

    def _run(self):
        """Run CTP in subprocess."""
        settings = resolve_ctp_connection(DEFAULT_FRONT)
        print(f"[Bridge] Front: {settings.front} ({settings.front_source})", flush=True)
        if len(settings.front_candidates) > 1:
            print(f"[Bridge] Front pool: {', '.join(settings.front_candidates)}", flush=True)
        print(f"[Bridge] Auth source: {settings.auth_source}", flush=True)
        if settings.redis_error:
            print(f"[Bridge] Redis config warning: {settings.redis_error}", flush=True)
        # Build a script that outputs JSON ticks
        script = f'''
import sys
sys.path.insert(0, r"{SIMNOW_MD_PATH}")
import thostmduserapi as mdapi
import time
import json

FRONT = "{settings.front}"
BROKER_ID = "{settings.broker_id}"
USER_ID = "{settings.user_id}"
PASSWORD = "{settings.password}"
APP_ID = "{settings.app_id}"
AUTH_CODE = "{settings.auth_code}"
USER_PRODUCT_INFO = "{settings.user_product_info}"

class Spi(mdapi.CThostFtdcMdSpi):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.base_prices = {{}}

    def OnFrontConnected(self):
        auth_fn = getattr(self.api, "ReqAuthenticate", None)
        if APP_ID or AUTH_CODE:
            if callable(auth_fn):
                req = mdapi.CThostFtdcReqAuthenticateField()
                req.BrokerID = BROKER_ID
                req.UserID = USER_ID
                req.AppID = APP_ID
                req.AuthCode = AUTH_CODE
                req.UserProductInfo = USER_PRODUCT_INFO
                auth_fn(req, 0)
                print("AUTH_SENT", flush=True)
                return
            print("AUTH_SKIPPED:NO_API_METHOD", flush=True)
        req = mdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = BROKER_ID
        req.UserID = USER_ID
        req.Password = PASSWORD
        self.api.ReqUserLogin(req, 0)

    def OnFrontDisconnected(self, n):
        pass

    def OnRspAuthenticate(self, p, info, req, last):
        if info and info.ErrorID != 0:
            print(f"AUTH_FAILED: {{info.ErrorID}}", flush=True)
            return
        print("AUTH_OK", flush=True)
        login = mdapi.CThostFtdcReqUserLoginField()
        login.BrokerID = BROKER_ID
        login.UserID = USER_ID
        login.Password = PASSWORD
        self.api.ReqUserLogin(login, 1)

    def OnRspUserLogin(self, p, info, req, last):
        if info and info.ErrorID != 0:
            print(f"LOGIN_FAILED: {{info.ErrorID}}", flush=True)
            return
        print(f"LOGIN_OK:{{p.TradingDay}}", flush=True)
        codes = [c.encode() for c in {build_instrument_list()}]
        n = self.api.SubscribeMarketData(codes, len(codes))
        print(f"SUBSCRIBED:{{n}}", flush=True)

    def OnRtnDepthMarketData(self, p):
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

        data = {{
            "type": "tick",
            "instrument_id": iid,
            "price": price,
            "volume": vol,
            "bid": bid,
            "ask": ask,
            "open_interest": oi,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "timestamp": ts,
        }}
        print("TICK:" + json.dumps(data), flush=True)

api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
spi = Spi(api)
api.RegisterFront(FRONT)
api.RegisterSpi(spi)
api.Init()

# Keep alive
while True:
    time.sleep(1)
'''
        self.process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SIMNOW_MD_PATH,
            env={**os.environ, "PYTHONPATH": SIMNOW_MD_PATH}
        )

        for line in self.process.stdout:
            if not self.running:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if line.startswith("TICK:"):
                tick_data = json.loads(line[5:])
                self._handle_tick(tick_data)
            elif line.startswith("LOGIN_OK:"):
                print(f"[Bridge] {line}", flush=True)
            elif line.startswith("AUTH_OK") or line.startswith("AUTH_SENT") or line.startswith("AUTH_FAILED:") or line.startswith("AUTH_SKIPPED:"):
                print(f"[Bridge] {line}", flush=True)
            elif line.startswith("LOGIN_FAILED:"):
                print(f"[Bridge] {line}", flush=True)
            elif line.startswith("SUBSCRIBED:"):
                print(f"[Bridge] {line}", flush=True)

    def _handle_tick(self, tick):
        """Override this to handle ticks."""
        # This method is called in the bridge thread
        # Forward via a callback mechanism
        if self.on_tick:
            self.on_tick(tick)

    def stop(self):
        self.running = False
        if self.process:
            self.process.terminate()


# Global bridge instance
bridge = None
_tick_callback = None

def set_tick_callback(cb):
    """Set the callback for receiving ticks from the bridge."""
    global _tick_callback
    _tick_callback = cb

def start_bridge():
    """Start the CTP bridge in background."""
    global bridge
    bridge = CTPBridge()
    bridge.on_tick = _tick_callback
    bridge.start()

if __name__ == "__main__":
    # Test: just print ticks
    def print_tick(t):
        print(f"TICK: {t['instrument_id']} price={t['price']} vol={t['volume']}")

    set_tick_callback(print_tick)
    start_bridge()
    time.sleep(30)
