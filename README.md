# Glycemic Digital Twin

[![CI](https://github.com/mitanshm18/glycemic-twin/actions/workflows/ci.yml/badge.svg)](https://github.com/mitanshm18/glycemic-twin/actions/workflows/ci.yml)

A personal digital twin for prediabetes and type 2 diabetes that predicts, at each logged meal, whether
Dexcom glucose will exceed 180 mg/dL within the next 120 minutes. Built on real, open CGMacros v1.0.0
data. Research proof of concept; not a medical device.

**Status: Milestone 5 (PostgreSQL + FastAPI backend).** The web app comes in a later milestone.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs the right Python).

```bash
make setup                                   # install dependencies
make test                                    # run the tests (synthetic fixtures only)
make m1 SOURCE=/path/to/CGMacros             # run the M1 pipeline on the real data (folder or ZIP)
make m1 SOURCE=/path/to/CGMacros_dateshifted365.zip SUMS=/path/to/SHA256SUMS.txt
make m2                                      # features + labels + folds + leakage checks (needs M1 outputs)
make m3                                      # nested participant CV, calibration, OOF, SHAP, model bundles (needs M2)
```

`make m1` never writes to `SOURCE`. It writes `data/reports/m1_audit.md` and `.json`,
`data/processed/m1/`, `data/manifests/cgmacros-1.0.0.lock.json`, and refreshes the generated block in
`docs/data-card.md`. It exits non-zero if a blocking issue is found.

`make m2` reads `data/processed/m1/`, writes `data/processed/m2/dataset.parquet`,
`data/reports/m2_dataset.md` and pins `data/manifests/folds.v1.csv`. It stops with an error if a hard
leakage check fails, and exits non-zero if a feature is flagged for review. Feature definitions:
`docs/features.md`.

`make m3` reads the M2 dataset and the pinned folds and trains every model, baseline and ablation with
nested participant-level cross-validation (ADR-016). It writes `data/reports/m3_evaluation.md` and
`.json` (pooled and per-fold AUROC, PR-AUC, Brier, calibration, participant-bootstrap CIs; target group
and healthy participants separately), `data/processed/m3/oof_predictions.parquet`,
`data/processed/m3/shap_oof.parquet` and the serving bundles in `data/processed/m3/models/`. Model
inputs come only from `data/configs/model_features.v1.yaml` (ADR-015); training settings from
`data/configs/training.v1.yaml`.

## Digital Twin engine (M4)

`twin_core.twin` builds a deterministic, versioned per-person state at any moment `as_of`
(`build_state`), runs bounded non-causal what-if scenarios on the current meal (`simulate`) and
explains changes between states (`diff_states`). It serves the M3 model bundle through the frozen
45-feature contract; see ADR-017, `docs/schemas/` and `docs/learning/M4.md`.

## Backend (M5)

```bash
cp .env.example .env          # then choose a local password in .env
make db-up                    # PostgreSQL 16 in Docker (localhost only)
make m5                       # migrate, ingest M1/M2 outputs, support profile, register M3 models
make create-admin USER=you    # prompts for a password (12+ characters)
make api                      # http://127.0.0.1:8000/api/v1/docs
```

Endpoints live under `/api/v1` (auth, patients, clinical/CGM/wearable/meals/outcomes, twin state,
predictions, what-if, replay, admin). See ADR-018 and `docs/learning/M5.md`.

## Clinician workspace (M6)

```bash
make api                      # backend on :8000 (set TWIN_COOKIE_SECURE=false in .env for plain http)
cd web
npm install
npm run dev                   # http://127.0.0.1:3000 (proxies /api/v1 to the backend)
npm run lint && npm run typecheck && npm test
E2E_USER=you E2E_PASSWORD=... npm run e2e   # needs both servers running
```

Optional Google sign-in: set `TWIN_GOOGLE_CLIENT_ID`, `TWIN_GOOGLE_CLIENT_SECRET` and
`TWIN_GOOGLE_REDIRECT_URI` in `.env` (see `.env.example`), restart the API, then link each
clinician's Google account (`uv run twin-api link-google USERNAME EMAIL`). Unlinked Google accounts
cannot sign in and no account is ever created from one. Without these settings the app offers
password sign-in only.

Patients, the Twin (current state, explanation, glucose with prediction-vs-reality, personal
response, what-if, evolution, provenance), the clinical record and the model page. Light, dark and
system themes. Real data only: every number comes from the API. See ADR-019 and
`docs/learning/M6.md`.

## Deployment (M7)

Docker Compose + Caddy: one HTTPS origin in front of the Next.js app and the API, PostgreSQL behind
them, a one-off init job that loads the processed data and registers the existing model.

```bash
deploy/package-data.sh                 # processed artifacts + model bundles -> deploy/data (+ SHA256SUMS)
cd deploy && cp .env.example .env      # host name, database password, optional Google sign-in
docker compose up -d --build
docker compose exec api twin-api create-user alice --role clinician
```

See [docs/deployment.md](docs/deployment.md) and [docs/security.md](docs/security.md).

## Continuous integration

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every pull request and every push to
`main`, as three parallel jobs:

- **Backend:** `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, and `pytest` against
  a throwaway PostgreSQL 16 service (migrations and schema included). The run fails if any test is
  skipped, so the database tests cannot silently drop out.
- **Frontend:** Node 22: `npm ci`, `lint`, `typecheck`, `test` (Vitest), `build`.
- **Images:** builds the API and web production images for `linux/amd64` (the deployment target)
  and smoke-tests them (non-root user, imports, `/login` served). Nothing is pushed.

CI uses only synthetic fixtures: no CGMacros data, processed artifacts, model bundles or secrets.
Checks on the real data (and the Playwright E2E suite) stay local, before a demo.

## Layout

```
packages/twin_core/   shared rules: configs, cleaning, native CGM grid, frozen labels,
                      features, personalization, and the Digital Twin engine (twin/)
ml/                   offline pipeline (M1-M2); training and evaluation (M3)
api/                  PostgreSQL schema + migrations, ingestion, model registry, FastAPI (M5)
web/                  Next.js clinician workspace (M6)
deploy/               Docker Compose stack, Caddyfile, data packaging (M7)
data/configs/         cleaning, labels, features, model_features, training (all v1, fixed before training)
data/raw/             the CGMacros download (not in Git)
data/reference/       the Phase 0A exploratory audit, kept for reconciliation
docs/                 data card, decision records, learning notes
```

## Data

CGMacros v1.0.0, PhysioNet (https://doi.org/10.13026/3z8q-x658), CC BY-NC-SA 4.0. Cite the PhysioNet
record, the CGMacros paper and PhysioNet itself. See `docs/data-card.md`.
