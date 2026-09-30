# Deployment (Docker Compose + Caddy)

One Linux host runs the whole system with Docker Compose:

```
browser ──HTTPS──> caddy ──/api/v1/*──> api (FastAPI, uvicorn) ──> postgres (PostgreSQL 16)
                     └────everything else──> web (Next.js standalone)
```

- **One origin.** Caddy serves the web app and the API on the same host name, so the session cookie
  is first-party and there is no CORS. Caddy obtains and renews the HTTPS certificate itself.
- **Only Caddy is reachable from outside** (ports 80 and 443). The API and PostgreSQL publish no
  ports. Two networks: `frontend` (caddy ↔ web) and `backend` (caddy ↔ api ↔ postgres, init).
- **Images.** `api/Dockerfile` (Python 3.11, dependencies installed exactly from `uv.lock`, runs as
  the unprivileged user `twin`) and `web/Dockerfile` (Node 22, Next.js standalone server, runs as
  `node`). No data, models or secrets are inside either image.
- **Data and models are mounted read-only** from the host (`deploy/data`, see below). The init job
  loads them into PostgreSQL and registers the existing M3 model; nothing is retrained.

## What the host needs

- Docker Engine with the Compose plugin (v2), about 3 GB free disk, 2 vCPU / 4 GB RAM.
- A DNS name pointing at the host, with ports 80 and 443 open (for automatic HTTPS).
- This repository (for `deploy/compose.yml`, `deploy/Caddyfile` and the Dockerfiles).
- The processed data bundle in `deploy/data/` (about 12 MB, never in git):

```
deploy/data/
  SHA256SUMS                                   checked by the init job before anything is loaded
  m1/run_manifest.json  m1/cgm.parquet  m1/wearable.parquet  m1/meals.parquet
  m1/meal_outcomes.parquet  m1/clinical_long.parquet  m1/clinical_wide.parquet
  m2/run_manifest.json  m2/dataset.parquet     (the training-support profile is built from it)
  m3/models/xgboost__full_personal.joblib/.json   the active model (SHA-256 recorded at registration)
  m3/models/logistic__full_personal.joblib/.json  registered, not active
```

Make it on the machine that ran the pipeline (`make m1 m2 m3`), then copy it to the host:

```bash
deploy/package-data.sh                 # writes deploy/data with SHA256SUMS, readable by containers
rsync -a deploy/data/ host:/path/to/repo/deploy/data/
```

The raw 655 MB CGMacros download is never needed on the host.

## Configuration

```bash
cd deploy
cp .env.example .env                   # then edit; .env is gitignored
```

| Variable | Required | Notes |
|---|---|---|
| `TWIN_PUBLIC_HOST` | yes | the public host name; `localhost` for a local trial |
| `POSTGRES_USER`, `POSTGRES_DB` | yes | |
| `POSTGRES_PASSWORD` | yes | letters and digits only (it is placed in a URL): `openssl rand -hex 32` |
| `TWIN_GOOGLE_CLIENT_ID`, `_SECRET`, `_REDIRECT_URI` | all or none | redirect: `https://<host>/api/v1/auth/google/callback` |
| `TWIN_COOKIE_NAME` | no | recommended `__Host-twin_session`; also baked into the web image at build |
| `TWIN_DATA_DIR` | no | default `./data` |
| `TWIN_LOG_LEVEL` | no | default `INFO` |

The compose file always sets `TWIN_ENVIRONMENT=production`, `TWIN_COOKIE_SECURE=true` and
`TWIN_TRUSTED_HOSTS=<public host>,api,localhost,127.0.0.1` (the extra names are for health checks
inside the stack). The API refuses to start with an unsafe configuration (see
[security.md](security.md)).

## Start

```bash
cd deploy
docker compose up -d --build           # first start builds the images (a few minutes)
docker compose ps                      # postgres, api, web, caddy healthy; init "Exited (0)"
```

Startup order, enforced by health checks and `depends_on`:

1. **postgres** starts; healthy when `pg_isready` answers.
2. **init** runs once: checks `SHA256SUMS`, then `twin-api migrate` → `twin-api ingest` →
   `twin-api support-profile` → `twin-api register-m3 --activate xgboost`. Every step is
   idempotent: on later starts it reports `already_ingested` and the existing registrations.
3. **api** starts after init succeeded; healthy when `GET /api/v1/ready` returns 200 (database
   reachable, migrations at head, active model loads and matches its SHA-256).
4. **web** starts; healthy when it serves `/login`.
5. **caddy** starts when api and web are healthy.

Then create the first account (accounts are never created from the web):

```bash
docker compose exec api twin-api create-user alice --role clinician     # prompts for a password
docker compose exec api twin-api create-user admin --role admin
```

## Inspect

```bash
curl https://<host>/api/v1/health      # liveness: {"status":"ok"} while the API process runs
curl https://<host>/api/v1/ready       # readiness: 200 when ready, 503 with generic reasons if not
docker compose logs -f api             # JSON lines: request_id, method, path, route, status, latency
docker compose logs init               # what the last initialisation did
```

Each response carries `X-Request-ID`; the same id is on the API's log line for that request.
Container logs are rotated by Docker (10 MB × 5 per service).

## Stop, restart, update

```bash
docker compose restart api             # or web / caddy / postgres
docker compose down                    # stops everything; data stays in the named volumes
docker compose up -d                   # starts again (init re-checks and changes nothing)
docker compose up -d --build           # after `git pull`: rebuild images, re-run init, restart
docker compose down -v                 # DESTROYS the database, certificates and support profile
```

Named volumes: `pgdata` (database), `support` (training-support profile file), `caddy_data`
(certificates), `caddy_config`. Sessions live in PostgreSQL, so restarting any container keeps
users signed in. While PostgreSQL is down, `/health` stays 200 and `/ready` returns 503; it
recovers on its own when the database is back.

## Proxy headers and request ids

- Caddy replaces any client-sent `X-Request-ID` with a fresh UUID before the API sees it; the API
  keeps it (it matches the id pattern) and returns it.
- Caddy sets `X-Forwarded-For`/`-Proto` from the real connection and does not trust incoming ones.
  The API believes forwarded headers only from Caddy's fixed address on the backend network
  (`TWIN_FORWARDED_ALLOW_IPS=172.30.10.10`, subnet `172.30.10.0/24` in `compose.yml`), so audit
  log IPs are the real client's and cannot be spoofed by a client-sent header.
- If the host already uses `172.30.10.0/24`, change the subnet and the address together.

## Architecture (Apple Silicon → amd64 server)

Images are built for the machine that builds them. Two supported ways:

- **Build on the server** (simplest): `docker compose up -d --build` there.
- **Build elsewhere for amd64**: `docker buildx build --platform linux/amd64 ...` for both images,
  then push them to a registry or `docker save | ssh host docker load`, and set
  `TWIN_IMAGE_TAG` accordingly.

Both amd64 images were built and run under emulation on Apple Silicon; the real XGBoost bundle
gives the same probabilities on arm64 and amd64 (largest difference 2.6e-8 over all 1,663 meals).

## Local trial

`TWIN_PUBLIC_HOST=localhost` runs the same stack on a laptop: open https://localhost (Caddy's own
certificate authority; the browser warns once). Ports 80 and 443 must be free. The stack's
PostgreSQL publishes no port, so it runs alongside the development database from the root
`docker-compose.yml`.
