import json
import os
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import redis
from kafka import KafkaConsumer


INSTANCE_ID = os.getenv("INSTANCE_ID", str(uuid.uuid4())[:8])
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ctp-ticks")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "ctp-worker")
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "9102"))

state = {
    "instance_id": INSTANCE_ID,
    "service": "worker",
    "processed_ticks": 0,
    "last_instrument": "",
    "last_tick_at": "",
    "last_error": "",
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


class Worker:
    def __init__(self):
        self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self.consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=CONSUMER_GROUP,
            enable_auto_commit=True,
            auto_offset_reset="latest",
            value_deserializer=lambda payload: json.loads(payload.decode("utf-8")),
        )

    def start(self):
        threading.Thread(target=self._run_health_server, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        print(f"[worker] instance={INSTANCE_ID} kafka={KAFKA_BOOTSTRAP_SERVERS}", flush=True)
        for message in self.consumer:
            self._process(message.value)

    def _run_health_server(self):
        server = ThreadedHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
        server.serve_forever()

    def _heartbeat_loop(self):
        while True:
            key = f"ctp:heartbeat:worker:{INSTANCE_ID}"
            self.redis.hset(
                key,
                mapping={
                    "instance_id": INSTANCE_ID,
                    "service": "worker",
                    "processed_ticks": state["processed_ticks"],
                    "last_instrument": state["last_instrument"],
                    "last_tick_at": state["last_tick_at"],
                    "last_error": state["last_error"],
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
            )
            self.redis.expire(key, 30)
            time.sleep(2)

    def _process(self, tick):
        instrument_id = tick["instrument_id"]
        state["processed_ticks"] += 1
        state["last_instrument"] = instrument_id
        state["last_tick_at"] = datetime.utcnow().isoformat() + "Z"
        state["last_error"] = ""

        latest_key = f"ctp:latest:{instrument_id}"
        self.redis.set(latest_key, json.dumps(tick))
        self.redis.expire(latest_key, 24 * 3600)
        self.redis.sadd("ctp:instruments", instrument_id)
        self.redis.zadd("ctp:latest_timestamps", {instrument_id: tick.get("timestamp", int(time.time()))})
        self.redis.hincrby("ctp:metrics", "ticks_processed", 1)
        self.redis.hset("ctp:metrics", mapping={"last_instrument": instrument_id, "last_update_at": state["last_tick_at"]})


if __name__ == "__main__":
    Worker().start()
