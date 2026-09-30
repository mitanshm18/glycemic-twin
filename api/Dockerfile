# syntax=docker/dockerfile:1
# Glycemic Twin API (FastAPI + twin_core + the M3 model loader). Build from the repository root:
#   docker build -f api/Dockerfile -t glycemic-twin-api .
# Dependencies come from uv.lock (--frozen): the image installs exactly what was tested.
# No data, models or secrets are baked in: processed artifacts and model bundles are mounted at
# /app/data/processed at run time (see deploy/compose.yml), configuration comes from TWIN_* env.

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.12.19

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ------------------------------------------------------------------ build: a locked virtualenv
FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# third-party dependencies first (cached until uv.lock changes)
COPY pyproject.toml uv.lock ./
COPY packages/twin_core/pyproject.toml packages/twin_core/
COPY ml/pyproject.toml ml/
COPY api/pyproject.toml api/
# NCCL (~470 MB) is a multi-GPU library xgboost pulls in on Linux; serving is CPU-only
RUN uv sync --frozen --no-dev --no-install-workspace --no-install-package nvidia-nccl-cu12 --no-install-package nvidia-nccl-cu13
# then the three workspace packages (twin_core, twin_ml, twin_api), installed from source
COPY packages/twin_core packages/twin_core
COPY ml ml
COPY api api
RUN uv sync --frozen --no-dev --no-install-package nvidia-nccl-cu12 --no-install-package nvidia-nccl-cu13 \
 # sources keep the permissions of the machine that built them: make them world-readable
 && chmod -R a+rX /app

# ------------------------------------------------------------------ runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
# libgomp: OpenMP runtime used by xgboost's native library
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 twin \
 && useradd --system --uid 10001 --gid twin --home-dir /app --shell /usr/sbin/nologin twin
WORKDIR /app
COPY --from=build /app /app
# frozen configs and the M3 evaluation report are part of the release (tracked in git)
COPY --chmod=0755 data/configs data/configs
COPY --chmod=0755 data/reports data/reports
# writable only where the init job stores the training-support profile it (re)builds
RUN mkdir -p data/processed/m5 && chown twin:twin data/processed/m5
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TWIN_REPO_ROOT=/app \
    TWIN_ENVIRONMENT=production
USER twin
EXPOSE 8000
# readiness, not liveness: 200 only when the database, migrations and active model are all good
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD ["python", "-c", "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4).status == 200 else 1)"]
CMD ["twin-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
