import argparse
import json
import socket
import threading
import time
from datetime import datetime

import thostmduserapi as mdapi


DEFAULT_FRONT = "tcp://trading.openctp.cn:30011"
DEFAULT_PORT = 19842
DEFAULT_SYMBOLS = ["cu2605", "au2606"]


def default_exchange(instrument_id: str) -> str:
    prefix = "".join(ch for ch in instrument_id if ch.isalpha()).lower()
    mapping = {
        "SHFE": {"cu", "au", "ag", "al", "zn", "rb", "hc", "ru", "bu", "ni", "sn", "ss", "pb"},
        "DCE": {"m", "y", "c", "cs", "a", "b", "p", "l", "pp", "v", "eb", "eg", "pg", "i", "j", "jm"},
        "CZCE": {"ma", "ta", "fg", "pf", "rm", "sr", "cf", "cy", "oi", "wh", "pm"},
        "CFFEX": {"if", "ih", "ic", "im", "tf", "ts", "t"},
        "INE": {"sc", "bc"},
    }
    for exchange, prefixes in mapping.items():
        if prefix in prefixes:
            return exchange
    return "UNKNOWN"


class TickRelayServer:
    def __init__(self, port: int):
        self.port = port
        self.sock = None
        self.clients = set()
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.listen(50)
        self.sock.settimeout(1.0)
        self.running = True
        print(f"[TTS-MDServer] Listening on port {self.port}", flush=True)
        while self.running:
            try:
                client, addr = self.sock.accept()
                client.settimeout(60.0)
                with self.lock:
                    self.clients.add(client)
                print(f"[TTS-MDServer] Client connected: {addr}, total={len(self.clients)}", flush=True)
            except socket.timeout:
                continue
            except Exception as exc:
                if self.running:
                    print(f"[TTS-MDServer] Accept error: {exc}", flush=True)

    def broadcast(self, tick):
        payload = ("TICK:" + json.dumps(tick, ensure_ascii=False) + "\n").encode("utf-8")
        dead = []
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.sendall(payload)
            except Exception:
                dead.append(client)
        if dead:
            with self.lock:
                for client in dead:
                    self.clients.discard(client)
                    try:
                        client.close()
                    except Exception:
                        pass

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()


class MdClient(mdapi.CThostFtdcMdSpi):
    def __init__(self, front: str, symbols, relay: TickRelayServer, broker_id: str = "", user_id: str = "", password: str = ""):
        super().__init__()
        self.front = front
        self.symbols = [s.encode("utf-8") for s in symbols]
        self.relay = relay
        self.broker_id = broker_id
        self.user_id = user_id
        self.password = password
        self.api = None

    def run(self):
        self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
        self.api.RegisterFront(self.front)
        self.api.RegisterSpi(self)
        self.api.Init()
        print("[TTS-MDServer] API Init complete", flush=True)

    def OnFrontConnected(self):
        print("[TTS-MDServer] OnFrontConnected", flush=True)
        req = mdapi.CThostFtdcReqUserLoginField()
        if self.broker_id:
            req.BrokerID = self.broker_id
            req.UserID = self.user_id
            req.Password = self.password
            print(f"[TTS-MDServer] Login with BrokerID={self.broker_id} UserID={self.user_id}", flush=True)
        self.api.ReqUserLogin(req, 0)

    def OnFrontDisconnected(self, nReason):
        print(f"[TTS-MDServer] OnFrontDisconnected nReason={nReason}", flush=True)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            print(f"[TTS-MDServer] Login failed: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}", flush=True)
            return
        print(f"[TTS-MDServer] Login succeed. TradingDay={pRspUserLogin.TradingDay}", flush=True)
        self.api.SubscribeMarketData(self.symbols, len(self.symbols))

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        instrument_id = pSpecificInstrument.InstrumentID
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            print(
                f"[TTS-MDServer] Subscribe failed: {instrument_id} {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}",
                flush=True,
            )
            return
        print(f"[TTS-MDServer] Subscribe succeed: {instrument_id}", flush=True)

    def OnRtnDepthMarketData(self, pDepthMarketData):
        tick = {
            "type": "tick",
            "instrument_id": pDepthMarketData.InstrumentID,
            "exchange": default_exchange(pDepthMarketData.InstrumentID),
            "price": float(pDepthMarketData.LastPrice or 0),
            "volume": int(pDepthMarketData.Volume or 0),
            "bid": float(pDepthMarketData.BidPrice1 or 0),
            "ask": float(pDepthMarketData.AskPrice1 or 0),
            "open_interest": int(pDepthMarketData.OpenInterest or 0),
            "change": 0.0,
            "change_pct": 0.0,
            "timestamp": time.time(),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trading_day": datetime.now().strftime("%Y-%m-%d"),
        }
        self.relay.broadcast(tick)


def parse_args():
    parser = argparse.ArgumentParser(description="openctp TTS market data TCP relay")
    parser.add_argument("--front", default=DEFAULT_FRONT)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--broker", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("no symbols provided")

    print(f"[TTS-MDServer] API version: {mdapi.CThostFtdcMdApi.GetApiVersion()}", flush=True)
    print(f"[TTS-MDServer] Front: {args.front}", flush=True)
    print(f"[TTS-MDServer] Symbols: {', '.join(symbols)}", flush=True)
    relay = TickRelayServer(args.port)
    threading.Thread(target=relay.start, daemon=True).start()

    client = MdClient(args.front, symbols, relay, args.broker, args.user, args.password)
    client.run()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        relay.stop()


if __name__ == "__main__":
    main()
