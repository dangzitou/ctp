# Seed / Worker / Admin High-Availability Deployment

This repository now includes a cross-platform HA stack built around three services:

- `seed`: publishes ticks into Kafka
- `worker`: consumes ticks from Kafka and materializes the latest market state into Redis
- `admin`: management plane and read API for health, topology, and latest market data

The deployment entrypoint is:

- `docker_ctp/docker-compose.ha.yml`

## What Runs Where

### Default Mac/Linux mode

On a fresh Mac/Linux machine, the stack runs in `sim` mode by default.
That means:

- Kafka, Redis, and MySQL run in Docker
- `seed` generates realistic demo ticks
- `worker` processes those ticks
- `admin` shows topology and market state

This mode is fully cross-platform and requires only Docker.

### Real-data mode on Mac/Linux

The official CTP DLLs in this repo are still Windows-oriented, so the recommended real-data path for Mac/Linux is:

1. Run `runtime/md_simnow/md_server.py` on a Windows host that has the CTP API available.
2. Point the HA `seed` container at that TCP relay.

That gives you real data on another Mac/Linux machine without needing to run the CTP DLL locally.

## Quick Start

```bash
cd docker_ctp
cp .env.ha .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

Open:

- Admin UI: `http://localhost:18081`
- Admin topology API: `http://localhost:18081/api/topology`
- Latest instruments API: `http://localhost:18081/api/instruments`
- Single instrument API: `http://localhost:18081/api/tick/cu2605`

## Real Data Setup

Edit `.env.ha.local`:

```env
SEED_MODE=tcp
MD_SERVER_HOST=<windows-host-or-ip>
MD_SERVER_PORT=19842
```

Then restart:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

### If Docker is running on Linux

If the Windows relay is reachable by IP, set `MD_SERVER_HOST` to that IP directly.

If you want to relay from the same host running Docker, the compose file already includes:

```text
host.docker.internal:host-gateway
```

so modern Docker on Linux/Mac can resolve that alias.

## High Availability Model

### Seed

`seed` uses Redis leader election:

- multiple `seed` replicas can run
- only the leader publishes into Kafka
- standby replicas keep heartbeats and take over when the leader disappears

Scale it with:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --scale seed=2
```

### Worker

`worker` is active-active through a Kafka consumer group:

- multiple replicas share the topic load
- each worker publishes its own heartbeat

Scale it with:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --scale worker=2
```

### Admin

`admin` is stateless:

- each instance reads topology and market data from Redis
- `admin-lb` uses HAProxy to front the admin replicas

Scale it with:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --scale admin=2
```

The externally visible entrypoint remains `http://localhost:18081`.

## Service Ports

Defaults come from `docker_ctp/.env.ha`:

- Admin LB: `18081`
- MySQL: `13307`
- Redis: `16380`
- Kafka internal client port exposed locally: `19092`
- Kafka external port exposed locally: `19094`

These alternate ports avoid colliding with the existing single-node stack already present in this repo.

## Health and Topology

The admin plane aggregates service heartbeats from Redis.

Useful endpoints:

- `/health`
- `/api/topology`
- `/api/instruments`
- `/api/tick/<instrument>`

Topology response includes:

- all visible `seed`, `worker`, and `admin` instances
- leader vs standby for `seed`
- processed tick counters for `worker`

## Operational Commands

Start:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

Tail logs:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local logs -f seed worker admin admin-lb
```

Stop:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down
```

Destroy volumes too:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down -v
```

## Notes

- The existing `docker_ctp/dashboard` Spring service is still available and unchanged.
- This HA stack is a separate operational path focused on `seed + worker + admin`.
- On Mac/Linux, fully local real-time CTP login is not guaranteed by this repo alone because the bundled vendor API assets are not packaged as a portable Docker-ready Linux client here. The relay approach is the practical cross-platform path.
