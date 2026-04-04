import json
import os
import threading
import time
import uuid
from datetime import datetime

import redis
from flask import Flask, jsonify, render_template_string


INSTANCE_ID = os.getenv("INSTANCE_ID", str(uuid.uuid4())[:8])
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PORT = int(os.getenv("PORT", "8081"))
HEARTBEAT_INTERVAL = 2

app = Flask(__name__)
rds = redis.Redis.from_url(REDIS_URL, decode_responses=True)


INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CTP Admin</title>
  <style>
    body { font-family: Menlo, Consolas, monospace; margin: 32px; background: #f6f4ef; color: #1f2933; }
    h1 { margin-bottom: 8px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .card { background: white; border: 1px solid #d9d4c7; border-radius: 12px; padding: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.04); }
    code { background: #f2ede3; padding: 2px 6px; border-radius: 6px; }
    table { width: 100%; border-collapse: collapse; }
    td, th { padding: 6px 0; border-bottom: 1px solid #eee7da; text-align: left; }
  </style>
</head>
<body>
  <h1>CTP Admin</h1>
  <p>Admin instance <code>{{ admin.instance_id }}</code> is serving the management plane.</p>
  <div class="grid">
    <div class="card">
      <h2>Services</h2>
      <table>
        <tr><th>Service</th><th>Role</th><th>Updated</th></tr>
        {% for service in services %}
        <tr><td>{{ service.service }}#{{ service.instance_id }}</td><td>{{ service.role or "-" }}</td><td>{{ service.updated_at }}</td></tr>
        {% endfor %}
      </table>
    </div>
    <div class="card">
      <h2>Metrics</h2>
      <p>Total processed ticks: <code>{{ metrics.ticks_processed or "0" }}</code></p>
      <p>Last instrument: <code>{{ metrics.last_instrument or "-" }}</code></p>
      <p>Last update: <code>{{ metrics.last_update_at or "-" }}</code></p>
    </div>
    <div class="card">
      <h2>Latest Instruments</h2>
      <table>
        <tr><th>Instrument</th><th>Price</th><th>Source</th></tr>
        {% for tick in ticks %}
        <tr><td>{{ tick.instrument_id }}</td><td>{{ tick.price }}</td><td>{{ tick.source_mode or "-" }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>
</body>
</html>
"""


def heartbeat_loop():
    while True:
        key = f"ctp:heartbeat:admin:{INSTANCE_ID}"
        rds.hset(
            key,
            mapping={
                "instance_id": INSTANCE_ID,
                "service": "admin",
                "role": "active",
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        rds.expire(key, 30)
        time.sleep(HEARTBEAT_INTERVAL)


def all_services():
    services = []
    for pattern in ("ctp:heartbeat:seed:*", "ctp:heartbeat:worker:*", "ctp:heartbeat:admin:*"):
        for key in sorted(rds.scan_iter(pattern)):
            services.append(rds.hgetall(key))
    services.sort(key=lambda item: (item.get("service", ""), item.get("instance_id", "")))
    return services


def latest_ticks(limit=12):
    instruments = [item for item in rds.zrevrange("ctp:latest_timestamps", 0, limit - 1)]
    ticks = []
    for instrument_id in instruments:
        payload = rds.get(f"ctp:latest:{instrument_id}")
        if payload:
            ticks.append(json.loads(payload))
    return ticks


@app.route("/")
def index():
    return render_template_string(
        INDEX_HTML,
        admin={"instance_id": INSTANCE_ID},
        services=all_services(),
        metrics=rds.hgetall("ctp:metrics"),
        ticks=latest_ticks(),
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "instance_id": INSTANCE_ID, "time": datetime.utcnow().isoformat() + "Z"})


@app.route("/api/topology")
def topology():
    return jsonify({"services": all_services(), "metrics": rds.hgetall("ctp:metrics")})


@app.route("/api/instruments")
def instruments():
    return jsonify(latest_ticks(limit=100))


@app.route("/api/tick/<instrument_id>")
def tick(instrument_id):
    payload = rds.get(f"ctp:latest:{instrument_id}")
    if not payload:
        return jsonify({"error": "not found", "instrument_id": instrument_id}), 404
    return jsonify(json.loads(payload))


if __name__ == "__main__":
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
