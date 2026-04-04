# CTP HA Deployment

This repository includes a Docker-first deployment path intended for Mac/Linux operators.

The high-availability stack now contains:

- `seed`: tick producer with Redis leader election
- `worker`: Kafka consumer group worker
- `admin`: management plane
- `dashboard`: Java Spring dashboard service
- `admin-lb`: HAProxy entrypoint for admin
- `dashboard-lb`: HAProxy entrypoint for dashboard
- `kafka`, `redis`, `mysql`: shared infrastructure

The main entrypoint is:

- `docker_ctp/docker-compose.ha.yml`

## Access Points

With the default `docker_ctp/.env.ha` values:

- Admin UI and API: `http://localhost:18081`
- Dashboard API/UI: `http://localhost:18080`
- Redis: `localhost:16380`
- MySQL: `localhost:13307`
- Kafka: `localhost:19092` and `localhost:19094`

## Data Modes

### Sim mode

This is the default and works cross-platform with Docker only.

- `seed` generates realistic simulated futures ticks
- `worker` consumes and materializes state
- `dashboard` and `admin` expose the result

### Real-data mode

For real futures data on Mac/Linux, use a Windows relay:

1. Run `runtime/md_simnow/md_server.py` on a Windows machine with the CTP API available.
2. Point the Docker `seed` service at that relay with:

```env
SEED_MODE=tcp
MD_SERVER_HOST=<windows-host-or-ip>
MD_SERVER_PORT=19842
```

This avoids requiring Windows-only CTP DLLs on the Mac itself.

### Runtime interface switching

Real-data entrypoints support switchable front pools and decoupled auth:

- front set in Redis: `ctp_collect_url`
- auth hash in Redis: `ctp_collect_auth`

Resolution order:

1. env overrides such as `CTP_FRONT`, `CTP_BROKER_ID`, `CTP_USER_ID`, `CTP_PASSWORD`, `CTP_APP_ID`, `CTP_AUTH_CODE`
2. Redis control-plane keys
3. built-in defaults

Typical operator flow:

```bash
redis-cli -p 16380 SADD ctp_collect_url tcp://101.230.178.179:53313
redis-cli -p 16380 SADD ctp_collect_url tcp://101.230.178.178:53313
redis-cli -p 16380 HSET ctp_collect_auth broker_id your_broker_id
redis-cli -p 16380 HSET ctp_collect_auth user_id your_user_id
redis-cli -p 16380 HSET ctp_collect_auth password 'your_password'
redis-cli -p 16380 HSET ctp_collect_auth app_id your_app_id
redis-cli -p 16380 HSET ctp_collect_auth auth_code 'your_auth_code'
docker compose -f docker-compose.ha.yml --env-file .env.ha.local restart seed
```

Switching is restart-based. Existing processes keep their selected front until restarted.

## High Availability Model

- `seed`: active-standby via Redis leader key
- `worker`: active-active via Kafka consumer group
- `admin`: stateless, horizontally scalable behind `admin-lb`
- `dashboard`: stateless enough for horizontal scaling behind `dashboard-lb`

Example scaling:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build \
  --scale seed=2 \
  --scale worker=2 \
  --scale admin=2 \
  --scale dashboard=2
```

## Operational Commands

Start:

```bash
cd docker_ctp
cp .env.ha .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

View logs:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local logs -f seed worker admin dashboard admin-lb dashboard-lb
```

Stop:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down
```

Destroy volumes:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down -v
```
