# One entry point for every task. Run `make help`.
# SOURCE: the CGMacros v1.0.0 ZIP or its extracted folder (never modified).
SOURCE ?= data/raw/CGMacros_dateshifted365.zip
SUMS   ?=
# Local settings (database URLs, cookie flag). Copy .env.example to .env first.
-include .env
export

.PHONY: help setup m1 m2 m3 test lint typecheck check \
        db-up db-down db-reset db-migrate ingest support-profile register-models create-admin m5 api

help:
	@echo "make setup                 install Python dependencies with uv"
	@echo "make m1 SOURCE=<zip|dir>   run the M1 data pipeline and audit (add SUMS=SHA256SUMS.txt for a ZIP)"
	@echo "make m2                    build features + labels + folds from M1 outputs; run leakage checks"
	@echo "make m3                    train + evaluate (nested participant CV, calibration, OOF, SHAP, bundles)"
	@echo "make db-up / db-down       start / stop the local PostgreSQL 16 (docker compose, reads .env)"
	@echo "make db-migrate            apply Alembic migrations (TWIN_DATABASE_URL)"
	@echo "make m5                    migrate + ingest M1/M2 outputs + support profile + register M3 models"
	@echo "make create-admin USER=me  create an admin account (asks for the password)"
	@echo "make api                   run the FastAPI dev server on http://127.0.0.1:8000/api/v1/docs"
	@echo "make test                  run all tests (database tests need TWIN_TEST_DATABASE_URL)"
	@echo "make check                 lint + typecheck + tests"

setup:
	uv sync

m1:
	uv run twin-ml m1 --source "$(SOURCE)" $(if $(SUMS),--official-sums "$(SUMS)",)

m2:
	uv run twin-ml m2

m3:
	uv run twin-ml m3

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d --wait postgres
	uv run twin-api migrate

db-migrate:
	uv run twin-api migrate

ingest:
	uv run twin-api ingest

support-profile:
	uv run twin-api support-profile

register-models:
	uv run twin-api register-m3 --activate xgboost

m5: db-migrate ingest support-profile register-models

create-admin:
	uv run twin-api create-user "$(USER)" --role admin

api:
	uv run twin-api serve --reload

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy packages/twin_core/src ml/src api/src

check: lint typecheck test
