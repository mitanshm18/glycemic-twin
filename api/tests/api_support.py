"""Shared constants and helpers for the M5 tests (imported by conftest and the test modules)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PASSWORDS = {"admin": "admin-password-123!", "clinician": "clinician-password-456!"}
SOURCE_LABEL = "SYNTHETIC M1 FIXTURE"


def alembic_config(url: str) -> Any:
    from alembic.config import Config

    cfg = Config(str(REPO / "api/alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def login(client: Any, role: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": role, "password": PASSWORDS[role]})
    assert r.status_code == 200, r.text
    return str(r.json()["csrf_token"])
