import json
import os
import random
import socket
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import redis
from kafka import KafkaProducer


INSTANCE_ID = os.getenv("INSTANCE_ID", str(uuid.uuid4())[:8])
SEED_MODE = os.getenv("SEED_MODE", "sim").strip().lower()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ctp-ticks")
LEADER_KEY = os.getenv("LEADER_KEY", "ctp:ha:seed:leader")
LEADER_TTL_SEC = int(os.getenv("LEADER_TTL_SEC", "10"))
HEARTBEAT_INTERVAL_SEC = float(os.getenv("HEARTBEAT_INTERVAL_SEC", "2"))
MD_SERVER_HOST = os.getenv("MD_SERVER_HOST", "host.docker.internal")
MD_SERVER_PORT = int(os.getenv("MD_SERVER_PORT", "19842"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "9101"))

INSTRUMENTS = {
    "cu2605": 95800.0,
    "au2606": 1034.0,
    "rb2610": 3135.0,
    "sc2605": 512.8,
    "if2606": 3579.2,
}

state = {
    "instance_id": INSTANCE_ID,
    "mode": SEED_MODE,
    "role": "starting",
    "published_ticks": 0,
    "last_tick_at": "",
    "last_error": "",
    "leader": "",
    "started_at": datetime.utcnow().isoformat() + "Z",
}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class HaSeed:
    def __init__(self):
        self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda item: json.dumps(item).encode("utf-8"),
            acks="all",
            retries=5,
            linger_ms=50,
        )
        self.running = True

    def start(self):
        threading.Thread(target=self._run_health_server, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        print(f"[seed] instance={INSTANCE_ID} mode={SEED_MODE} kafka={KAFKA_BOOTSTRAP_SERVERS}", flush=True)

        while self.running:
            if not self._ensure_leadership():
                state["role"] = "standby"
                time.sleep(1.0)
                continue

            state["role"] = "leader"
            try:
                if SEED_MODE == "tcp":
                    self._run_tcp_source()
                else:
                    self._run_sim_source()
            except Exception as exc:
                state["last_error"] = str(exc)
                print(f"[seed] source error: {exc}", flush=True)
                time.sleep(2.0)

    def _run_health_server(self):
        server = ThreadedHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
        server.serve_forever()

    def _heartbeat_loop(self):
        while self.running:
            state["leader"] = self.redis.get(LEADER_KEY) or ""
            key = f"ctp:heartbeat:seed:{INSTANCE_ID}"
            self.redis.hset(
                key,
                mapping={
                    "instance_id": INSTANCE_ID,
                    "service": "seed",
                    "mode": SEED_MODE,
                    "role": state["role"],
                    "leader": state["leader"],
                    "published_ticks": state["published_ticks"],
                    "last_tick_at": state["last_tick_at"],
                    "last_error": state["last_error"],
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
            )
            self.redis.expire(key, LEADER_TTL_SEC * 3)
            time.sleep(HEARTBEAT_INTERVAL_SEC)

    def _ensure_leadership(self):
        acquired = self.redis.set(LEADER_KEY, INSTANCE_ID, ex=LEADER_TTL_SEC, nx=True)
        if acquired:
            return True
        current = self.redis.get(LEADER_KEY)
        if current == INSTANCE_ID:
            self.redis.expire(LEADER_KEY, LEADER_TTL_SEC)
            return True
        return False

    def _publish(self, tick):
        self.producer.send(KAFKA_TOPIC, tick).get(timeout=5)
        state["published_ticks"] += 1
        state["last_tick_at"] = datetime.utcnow().isoformat() + "Z"
        state["last_error"] = ""

    def _run_sim_source(self):
        for instrument_id, base_price in INSTRUMENTS.items():
            if not self._ensure_leadership():
                return
            price = round(base_price + random.uniform(-0.8, 0.8), 2)
            tick = {
                "type": "tick",
                "instrument_id": instrument_id,
                "exchange": self._exchange(instrument_id),
                "price": price,
                "bid": round(price - 0.2, 2),
                "ask": round(price + 0.2, 2),
                "volume": random.randint(10_000, 900_000),
                "open_interest": random.randint(1_000, 900_000),
                "change": round(random.uniform(-20, 20), 2),
                "change_pct": round(random.uniform(-2, 2), 2),
                "timestamp": int(time.time()),
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": f"seed:{INSTANCE_ID}",
                "source_mode": "sim",
            }
            self._publish(tick)
        time.sleep(0.5)

    def _run_tcp_source(self):
        with socket.create_connection((MD_SERVER_HOST, MD_SERVER_PORT), timeout=10) as sock:
            sock.settimeout(20)
            buffer = ""
            print(f"[seed] tcp relay connected to {MD_SERVER_HOST}:{MD_SERVER_PORT}", flush=True)
            while self.running and self._ensure_leadership():
                chunk = sock.recv(8192)
                if not chunk:
                    raise RuntimeError("upstream md_server disconnected")
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("TICK:"):
                        continue
                    tick = json.loads(line[5:])
                    tick["source"] = f"seed:{INSTANCE_ID}"
                    tick["source_mode"] = "tcp"
                    self._publish(tick)

    @staticmethod
    def _exchange(instrument_id):
        prefix = "".join(c for c in instrument_id if c.isalpha()).lower()
        mapping = {
            "SHFE": {"cu", "au", "rb"},
            "INE": {"sc"},
            "CFFEX": {"if"},
        }
        for exchange, prefixes in mapping.items():
            if prefix in prefixes:
                return exchange
        return "UNKNOWN"


if __name__ == "__main__":
    HaSeed().start()
