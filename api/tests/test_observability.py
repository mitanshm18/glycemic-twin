"""Operational logging (M7 phase 4): JSON lines, request ids, and nothing secret in them.

Most tests need no database: the app's engine connects lazily. Every log line is captured through
the real formatter and redaction filter, exactly as a container would print it.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from twin_api.logs import JsonFormatter, Redact, TextFormatter, redact
from twin_api.settings import Settings

URL = "postgresql+psycopg://twin:p4ssw0rd-secret@127.0.0.1:1/twin"  # port 1: refused at once
HOST = "https://twin.example.org"


class Capture:
    """Every record logged inside the block, as the JSON objects a container would print."""

    def __init__(self, out: list[dict[str, Any]]) -> None:
        self.out = out

    def __enter__(self) -> None:
        # (create the app before entering: the app factory sets the root level from settings)
        self.buf = io.StringIO()
        self.handler = logging.StreamHandler(self.buf)
        self.handler.setFormatter(JsonFormatter())
        self.handler.addFilter(Redact())
        self.root = logging.getLogger()
        self.level = self.root.level
        self.root.addHandler(self.handler)
        self.root.setLevel(logging.DEBUG)

    def __exit__(self, *exc: object) -> None:
        self.root.removeHandler(self.handler)
        self.root.setLevel(self.level)
        self.out.extend(
            json.loads(x) for x in self.buf.getvalue().splitlines() if x.startswith("{")
        )


def _app(**over: Any) -> Any:
    from twin_api.app import create_app

    settings = {
        "database_url": URL,
        "environment": "production",
        "cookie_secure": True,
        "trusted_hosts": "twin.example.org",
    }
    return create_app(Settings(**{**settings, **over}))


def _requests(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [x for x in lines if x.get("event") == "request"]


# ------------------------------------------------------------------------------------ structure


def test_one_json_line_per_request_with_id_method_path_status_latency() -> None:
    captured: list[dict[str, Any]] = []
    app = _app()
    with Capture(captured), TestClient(app, base_url=HOST) as c:
        r = c.get("/api/v1/patients?as_of=2020-01-01T00:00:00")  # no session: 401
    (line,) = [x for x in _requests(captured) if x["path"] == "/api/v1/patients"]
    assert r.status_code == 401
    assert line["method"] == "GET"
    assert line["route"] == "/api/v1/patients"
    assert line["status"] == 401
    assert line["level"] == "warning"
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == r.headers["x-request-id"]
    assert "as_of" not in json.dumps(line)  # query strings are never logged
    assert {"ts", "logger", "msg"} <= line.keys()


def test_a_valid_incoming_request_id_is_kept_and_a_bad_one_replaced() -> None:
    captured: list[dict[str, Any]] = []
    app = _app()
    with Capture(captured), TestClient(app, base_url=HOST) as c:
        kept = c.get("/api/v1/health", headers={"X-Request-ID": "proxy-7f3a9c21"})
        replaced = c.get("/api/v1/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert kept.headers["x-request-id"] == "proxy-7f3a9c21"
    assert replaced.headers["x-request-id"] != "bad id\nwith newline"
    assert len(replaced.headers["x-request-id"]) == 32
    ids = [x["request_id"] for x in _requests(captured)]
    assert ids == ["proxy-7f3a9c21", replaced.headers["x-request-id"]]


def test_health_checks_are_quiet_and_real_traffic_is_not() -> None:
    captured: list[dict[str, Any]] = []
    app = _app()
    with Capture(captured), TestClient(app, base_url=HOST) as c:
        c.get("/api/v1/health")
        c.get("/api/v1/nope")
    levels = {x["path"]: x["level"] for x in _requests(captured)}
    assert levels == {"/api/v1/health": "debug", "/api/v1/nope": "warning"}


def test_startup_and_shutdown_are_logged_without_secrets() -> None:
    captured: list[dict[str, Any]] = []
    app = _app()
    with Capture(captured), TestClient(app, base_url=HOST):
        pass
    events = [x["event"] for x in captured if x.get("event") in ("startup", "shutdown")]
    assert events == ["startup", "shutdown"]
    start = next(x for x in captured if x.get("event") == "startup")
    assert start["environment"] == "production" and start["trusted_hosts"] == ["twin.example.org"]
    assert "p4ssw0rd-secret" not in json.dumps(captured)


# ------------------------------------------------------------------------------------ errors


def test_an_unexpected_error_is_logged_once_with_the_request_id_and_no_request_contents() -> None:
    app = _app()

    @app.post("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("failed while handling the twin")

    captured: list[dict[str, Any]] = []
    with Capture(captured), TestClient(app, base_url=HOST, raise_server_exceptions=False) as c:
        c.cookies.set("twin_session", "session-token-value")
        r = c.post(
            "/api/v1/_boom",
            json={"password": "hunter2-hunter2"},
            headers={"X-CSRF-Token": "csrf-token-value", "Authorization": "Bearer abc.def.ghi"},
        )
    assert r.status_code == 500
    assert r.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "unexpected server error",
        "details": None,
    }
    assert r.headers["cache-control"] == "no-store"
    errors = [x for x in captured if x.get("event") == "unhandled_error"]
    assert len(errors) == 1
    err = errors[0]
    assert err["request_id"] == r.headers["x-request-id"]
    assert err["exc_type"] == "RuntimeError" and "failed while handling the twin" in err["exc"]
    (req,) = [x for x in _requests(captured) if x["path"] == "/api/v1/_boom"]
    assert req["status"] == 500 and req["level"] == "error"
    text = json.dumps(captured)
    for secret in ("hunter2-hunter2", "session-token-value", "csrf-token-value", "abc.def.ghi"):
        assert secret not in text


def test_a_database_outage_answers_generically_and_logs_no_password() -> None:
    captured: list[dict[str, Any]] = []
    app = _app()
    with Capture(captured), TestClient(app, base_url=HOST, raise_server_exceptions=False) as c:
        r = c.post("/api/v1/auth/login", json={"username": "someone", "password": "a-password-123"})
        ready = c.get("/api/v1/ready")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert ready.status_code == 503 and ready.json()["database"] is False
    text = json.dumps(captured)
    assert "p4ssw0rd-secret" not in text
    assert "a-password-123" not in text
    assert any(x.get("event") == "unhandled_error" for x in captured)


# ------------------------------------------------------------------------------------ redaction


@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        ("connect postgresql+psycopg://twin:p4ss@db:5432/twin failed", "p4ss"),
        ("callback?code=4/0AbCdEf&state=xyz789", "4/0AbCdEf"),
        ("callback?code=4/0AbCdEf&state=xyz789", "xyz789"),
        ("{'password': 'hunter2-hunter2'}", "hunter2-hunter2"),
        ("client_secret=GOCSPX-abc", "GOCSPX-abc"),
        ("Authorization: Bearer eyJhbGciOi.x.y", "eyJhbGciOi.x.y"),
        ("id_token=eyJ.a.b refresh_token=r1", "eyJ.a.b"),
        ("twin_session cookie=abcDEF123", "abcDEF123"),
    ],
)
def test_redaction_removes_secrets(raw: str, gone: str) -> None:
    assert gone not in redact(raw)


def test_redaction_leaves_ordinary_diagnostics_alone() -> None:
    msg = "GET /api/v1/patients/3/twin 200 state_id=ab12 status_code=500"
    assert redact(msg) == msg


def test_redaction_applies_to_every_logger_and_to_tracebacks() -> None:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(Redact())
    lg = logging.getLogger("some.library")
    lg.addHandler(handler)
    try:
        try:
            raise ValueError("bad url postgresql://u:topsecret@h/db")
        except ValueError:
            lg.exception("password=hunter2-hunter2 while connecting")
    finally:
        lg.removeHandler(handler)
    line = json.loads(buf.getvalue())
    assert "hunter2" not in line["msg"] and "topsecret" not in line["exc"]


def test_text_format_for_local_development_is_redacted_too() -> None:
    rec = logging.LogRecord("twin_api", logging.INFO, __file__, 1, "token=abc123 ok", None, None)
    assert "abc123" not in TextFormatter().format(rec)


# ------------------------------------------------------------------------------------ settings


def test_log_format_defaults_json_in_production_and_text_in_development() -> None:
    prod = Settings(
        database_url=URL, environment="production", cookie_secure=True, trusted_hosts="h"
    )
    dev = Settings(database_url=URL, environment="development", cookie_secure=False)
    assert prod.log_style == "json" and dev.log_style == "text"
    assert (
        Settings(database_url=URL, environment="development", log_format="json").log_style == "json"
    )


# ------------------------------------------------------------------------------------ with a database


def test_a_real_sign_in_logs_no_password_cookie_or_csrf_token(app: Any) -> None:
    from api_support import PASSWORDS

    captured: list[dict[str, Any]] = []
    with Capture(captured), TestClient(app) as c:
        r = c.post(
            "/api/v1/auth/login", json={"username": "clinician", "password": PASSWORDS["clinician"]}
        )
        csrf = r.json()["csrf_token"]
        cookie = c.cookies.get("twin_session")
        c.get("/api/v1/patients")
        c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and cookie
    text = json.dumps(captured)
    for secret in (PASSWORDS["clinician"], cookie, csrf):
        assert secret not in text
    paths = [x["path"] for x in _requests(captured)]
    assert paths == ["/api/v1/auth/login", "/api/v1/patients", "/api/v1/auth/logout"]
