"""Production safety (M7 phase 3): configuration guards, trusted hosts, headers, redaction.

The configuration and middleware tests need no database. Tests that serve the model use the
disposable PostgreSQL database and SYNTHETIC fixtures from conftest.py.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from twin_api import security
from twin_api.settings import Settings

URL = "postgresql+psycopg://twin:p4ssw0rd-secret@db.internal:5432/twin"
PROD = {
    "database_url": URL,
    "environment": "production",
    "cookie_secure": True,
    "trusted_hosts": "twin.example.org, api",
}


def prod(**over: Any) -> Settings:
    return Settings(**{**PROD, **over})


# ------------------------------------------------------------------------------------ configuration


def test_a_safe_production_configuration_is_accepted() -> None:
    s = prod()
    assert s.production and s.trusted_host_list == ["twin.example.org", "api"]


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"cookie_secure": False}, "TWIN_COOKIE_SECURE must be true"),
        ({"trusted_hosts": None}, "TWIN_TRUSTED_HOSTS must list"),
        ({"trusted_hosts": " , "}, "TWIN_TRUSTED_HOSTS must list"),
        ({"trusted_hosts": "*"}, "must not contain '*'"),
        ({"forwarded_allow_ips": "*"}, "TWIN_FORWARDED_ALLOW_IPS must name the proxy"),
        ({"google_client_id": "id.apps.googleusercontent.com"}, "partly configured"),
        (
            {
                "google_client_id": "id.apps.googleusercontent.com",
                "google_client_secret": "s",
                "google_redirect_uri": "http://twin.example.org/api/v1/auth/google/callback",
            },
            "TWIN_GOOGLE_REDIRECT_URI must use https",
        ),
    ],
)
def test_production_refuses_to_start_unsafely(over: dict[str, Any], needle: str) -> None:
    with pytest.raises(ValidationError, match="unsafe production configuration") as err:
        prod(**over)
    assert needle in str(err.value)


def test_a_refused_configuration_never_prints_its_secrets() -> None:
    with pytest.raises(ValidationError) as err:
        prod(cookie_secure=False, google_client_secret="a-client-secret")
    assert "p4ssw0rd-secret" not in str(err.value)
    assert "a-client-secret" not in str(err.value)


def test_complete_https_google_sign_in_is_accepted_in_production() -> None:
    s = prod(
        google_client_id="id.apps.googleusercontent.com",
        google_client_secret="a-client-secret",
        google_redirect_uri="https://twin.example.org/api/v1/auth/google/callback",
    )
    assert s.google_enabled


def test_development_may_use_plain_http_cookies() -> None:
    s = Settings(database_url=URL, environment="development", cookie_secure=False)
    assert not s.production and s.trusted_host_list == []


def test_the_environment_name_is_checked() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=URL, environment="prod")  # type: ignore[arg-type]


def test_secrets_never_appear_in_settings_reprs() -> None:
    s = prod(
        google_client_id="id.apps.googleusercontent.com",
        google_client_secret="a-client-secret",
        google_redirect_uri="https://twin.example.org/api/v1/auth/google/callback",
    )
    for text in (repr(s), str(s), str(s.model_dump())):
        assert "p4ssw0rd-secret" not in text
        assert "a-client-secret" not in text
    assert s.database_url.get_secret_value() == URL


# ------------------------------------------------------------------------------------ app behaviour


def _app(settings: Settings) -> Any:
    from twin_api.app import create_app

    return create_app(settings)  # the engine connects lazily: no database needed for these


def test_production_serves_no_docs_or_schema() -> None:
    with TestClient(_app(prod()), base_url="https://twin.example.org") as c:
        assert c.get("/api/v1/docs").status_code == 404
        assert c.get("/api/v1/openapi.json").status_code == 404
        assert c.get("/api/v1/health").status_code == 200


def test_development_keeps_the_docs() -> None:
    dev = Settings(database_url=URL, environment="development", cookie_secure=False)
    with TestClient(_app(dev)) as c:
        assert c.get("/api/v1/openapi.json").status_code == 200


def test_unknown_hosts_are_refused_in_production() -> None:
    app = _app(prod())
    with TestClient(app, base_url="https://evil.example.com") as c:
        assert c.get("/api/v1/health").status_code == 400
    with TestClient(app, base_url="http://api:8000") as c:  # the internal name, for health checks
        assert c.get("/api/v1/health").status_code == 200


def test_every_api_response_is_uncacheable_and_locked_down_in_production() -> None:
    with TestClient(_app(prod()), base_url="https://twin.example.org") as c:
        h = c.get("/api/v1/health").headers
        missing = c.get("/api/v1/no-such-route")
    assert h["cache-control"] == "no-store"
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"


def test_unexpected_errors_are_generic_to_clients_and_logged_without_request_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(prod())

    @app.post("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("internal detail: token=abc123")

    with (
        caplog.at_level(logging.ERROR, logger="twin_api"),
        TestClient(app, base_url="https://twin.example.org", raise_server_exceptions=False) as c,
    ):
        c.cookies.set("twin_session", "session-token-value")
        r = c.post("/api/v1/_boom", json={"password": "hunter2-hunter2"})
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "unexpected server error", "details": None}
    }
    assert "abc123" not in r.text
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "POST /api/v1/_boom" in logged
    for secret in ("hunter2-hunter2", "session-token-value"):
        assert secret not in logged


def test_validation_errors_never_echo_submitted_values() -> None:
    with TestClient(_app(prod()), base_url="https://twin.example.org") as c:
        r = c.post("/api/v1/auth/login", json={"username": "x", "password": "my-secret-password"})
    assert r.status_code == 422
    assert "my-secret-password" not in r.text


# ------------------------------------------------------------------------------------ passwords


def test_password_hashing_never_runs_more_than_the_allowed_number_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bursts of sign-ins queue instead of exhausting memory (the concurrent-login 500)."""
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow_verify(password: bytes, encoded: str) -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    monkeypatch.setattr(security.Argon2id, "verify_phc_encoded", staticmethod(slow_verify))
    results: list[bool] = []
    threads = [
        threading.Thread(target=lambda: results.append(security.verify_password("p", "h")))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 8
    assert peak <= security.MAX_CONCURRENT_HASHES


# ------------------------------------------------------------------------------------ with a database


@pytest.fixture
def prod_app(db_url: str, loaded: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    """The production app on the test database, with its model artifact unavailable."""
    from twin_api import registry
    from twin_core.twin import ModelContractError

    def missing(stored: str, search: Any) -> Any:
        raise ModelContractError("model artifact missing: m.joblib (looked in /srv/secret/models)")

    monkeypatch.setattr(registry, "locate_artifact", missing)
    return _app(prod(database_url=db_url, trusted_hosts="testserver"))


def test_production_readiness_does_not_reveal_server_paths(prod_app: Any) -> None:
    with TestClient(prod_app, base_url="https://testserver") as c:
        r = c.get("/api/v1/ready")
    assert r.status_code == 503
    assert "active model cannot be served" in r.json()["problems"]
    assert "/srv/secret" not in r.text


def test_production_model_errors_do_not_reveal_server_paths(prod_app: Any) -> None:
    from api_support import login

    with TestClient(prod_app, base_url="https://testserver") as c:
        login(c, "clinician")
        pid = c.get("/api/v1/patients").json()[0]["id"]
        r = c.get(f"/api/v1/patients/{pid}/twin")
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "MODEL_INCOMPATIBLE",
        "message": "the active model cannot be served",
        "details": None,
    }


def test_secure_session_cookie_flags_in_production(prod_app: Any) -> None:
    from api_support import PASSWORDS

    with TestClient(prod_app, base_url="https://testserver") as c:
        r = c.post(
            "/api/v1/auth/login", json={"username": "clinician", "password": PASSWORDS["clinician"]}
        )
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200
    for flag in ("httponly", "secure", "samesite=lax", "path=/"):
        assert flag in cookie
    assert PASSWORDS["clinician"] not in r.text


def test_unknown_login_names_are_not_stored_verbatim(client: Any, engine: Any) -> None:
    from sqlalchemy import select
    from twin_api.db import make_sessionmaker
    from twin_api.models import AuditLog

    typed = "Correct.Horse.Battery"  # e.g. a password typed into the username field
    r = client.post("/api/v1/auth/login", json={"username": typed, "password": "whatever-123"})
    assert r.status_code == 401
    with make_sessionmaker(engine)() as s:
        row = s.scalars(
            select(AuditLog).where(AuditLog.action == "login").order_by(AuditLog.id.desc())
        ).first()
    assert row is not None and row.username is None
    assert typed.lower() not in str(row.detail).lower()
    assert len(row.detail["attempted_sha256"]) == 16
