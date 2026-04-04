# Mac Docker Deployment Guide

This is the operator guide for using this repository on a Mac with Docker Desktop.

It covers:

1. Starting the Dockerized Java dashboard and HA services
2. Seeing market data from either simulation or a Windows real-data relay
3. Understanding the GitHub AI code-review and scheduled-audit workflows

## 1. What You Need On The Mac

- macOS with Docker Desktop installed
- Git
- Access to this GitHub repository

Optional but recommended:

- A separate Windows machine that can run `runtime/md_simnow/md_server.py` if you want real market data

You do not need Java, Maven, Kafka, Redis, or MySQL installed locally on the Mac for the Docker path.

## 2. Clone The Repository

```bash
git clone https://github.com/dangzitou/ctp.git
cd ctp
```

## 3. Choose Your Deployment Mode

### Option A: Simulated data

Use this first if you only need the system running quickly on a Mac.

Pros:

- no Windows dependency
- fully Dockerized
- good for dashboard validation and workflow demos

### Option B: Real data through a Windows relay

Use this when you need actual CTP data on the Mac.

Pros:

- real market data visible from the Mac
- Docker stack still runs on the Mac

Constraint:

- the upstream CTP DLL/API still runs on Windows, not inside the Mac containers

## 4. Start The HA Stack On Mac

```bash
cd docker_ctp
cp .env.ha .env.ha.local
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

After startup, these services should exist:

- `kafka`
- `mysql`
- `redis`
- `seed`
- `worker`
- `admin`
- `dashboard`
- `admin-lb`
- `dashboard-lb`

## 5. Mac Access URLs

Open these in the browser:

- Admin plane: `http://localhost:18081`
- Java dashboard: `http://localhost:18080`

Useful APIs:

- `http://localhost:18081/api/topology`
- `http://localhost:18081/api/instruments`
- `http://localhost:18081/api/tick/cu2605`
- `http://localhost:18080/api/stats`
- `http://localhost:18080/api/tick/cu2605`

## 6. Real Data Setup From Windows To Mac

On the Windows machine:

```powershell
cd E:\Develop\projects\ctp
python runtime\md_simnow\md_server.py 19842
```

You should see output similar to:

- login succeeded
- instruments subscribed

On the Mac, edit `docker_ctp/.env.ha.local`:

```env
SEED_MODE=tcp
MD_SERVER_HOST=<windows-ip-or-dns-name>
MD_SERVER_PORT=19842
```

Then restart:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

If the Mac can route to the Windows host, `seed` will relay real ticks into Kafka and the rest of the Docker stack will display them.

## 7. Scaling And HA

Example HA scaling on the Mac:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build \
  --scale seed=2 \
  --scale worker=2 \
  --scale admin=2 \
  --scale dashboard=2
```

Behavior:

- only one `seed` is active at a time
- `worker` instances share Kafka consumption
- `admin` instances sit behind `admin-lb`
- `dashboard` instances sit behind `dashboard-lb`

## 8. Health Checks And Troubleshooting

Check running containers:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local ps
```

Tail logs:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local logs -f seed worker admin dashboard
```

If the dashboard is up but shows no real data:

1. Check `seed` logs first
2. Confirm Windows relay is reachable from the Mac
3. Confirm `SEED_MODE=tcp`
4. Confirm the relay host and port are correct

If only simulated data is needed, set:

```env
SEED_MODE=sim
```

and restart the stack.

## 9. Java Dashboard In Docker

The Java dashboard is built from:

- `docker_ctp/dashboard/Dockerfile`

It now uses Java 21 to match the current Maven project configuration.

The dashboard container connects to:

- Kafka for ticks
- Redis for fast state access
- MySQL for persistence

Externally, use the load-balanced entrypoint:

- `http://localhost:18080`

## 10. GitHub AI Review And Audit

These workflows already exist in the repository:

- `.github/workflows/ai-code-review.yml`
- `.github/workflows/ai-repo-audit.yml`

Behavior:

- every push triggers multi-agent code review
- every 6 hours a scheduled multi-agent repo audit runs

Current design:

- 3 parallel reviewers
- 1 coordinator
- push review writes a commit comment
- scheduled audit writes or updates a reusable GitHub issue

The workflows run on GitHub-hosted runners, not on your Mac.

That means once the repo is cloned and you can push changes, your Mac does not need to run the review agents locally.

## 11. GitHub Secrets And Variables

For this repository, the review system expects:

- secret: `MINIMAX_API_KEY`

Optional variables:

- `AI_REVIEW_MODEL`
- `AI_AUDIT_MODEL`
- `AI_REVIEW_MAX_FILES`
- `AI_REVIEW_MAX_PATCH_CHARS`

The workflows use the MiniMax OpenAI-compatible endpoint internally.

## 12. Recommended Daily Usage At Work

If you go back to the office and want the fastest path on a Mac:

1. Pull latest code
2. Start Docker Desktop
3. Run the HA stack in `sim` mode first
4. Verify:
   - `http://localhost:18081`
   - `http://localhost:18080`
5. If you need real data, point `SEED_MODE=tcp` to the Windows relay and restart
6. Push code normally; GitHub Actions will run review and audit automatically

## 13. Useful Commands

Start:

```bash
cd docker_ctp
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

Restart after env change:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local up -d --build
```

Stop:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down
```

Stop and remove volumes:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local down -v
```

Watch logs:

```bash
docker compose -f docker-compose.ha.yml --env-file .env.ha.local logs -f seed worker admin dashboard
```
