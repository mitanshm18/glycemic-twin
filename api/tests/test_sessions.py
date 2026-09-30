"""Session lifecycle behind the M6 web app: restoration after a browser reload, expiry, revocation,
logout, CSRF under SameSite=Lax, and the public sign-in provider list (disposable PostgreSQL;
SYNTHETIC data)."""

from __future__ import annotations

from typing import Any

from api_support import PASSWORDS
from sqlalchemy import text
from twin_api.security import sha256_hex

API = "/api/v1"


def code(r: Any) -> str:
    return str(r.json()["error"]["code"])


def sign_in(c: Any, role: str = "clinician") -> str:
    r = c.post(f"{API}/auth/login", json={"username": role, "password": PASSWORDS[role]})
    assert r.status_code == 200, r.text
    return str(r.json()["csrf_token"])


def test_session_is_restored_after_a_reload(app: Any) -> None:
    """A reload is a new page with only the cookie: the session must still be recognised, and a
    fresh CSRF token must be obtainable for the next state-changing request."""
    from fastapi.testclient import TestClient

    with TestClient(app) as first:
        sign_in(first)
        cookie = first.cookies.get("twin_session")
    assert cookie
    with TestClient(app, cookies={"twin_session": cookie}) as reloaded:
        me = reloaded.get(f"{API}/auth/me")
        assert me.status_code == 200 and me.json()["username"] == "clinician"
        csrf = reloaded.get(f"{API}/auth/csrf").json()["csrf_token"]
        r = reloaded.post(f"{API}/patients/2/predictions", json={}, headers={"X-CSRF-Token": csrf})
        assert r.status_code != 403, r.text  # the restored session can act (CSRF accepted)


def test_protected_routes_refuse_requests_without_a_session(client: Any) -> None:
    for path in ("/auth/me", "/overview/patients", "/patients/2/twin", "/models"):
        r = client.get(API + path)
        assert r.status_code == 401 and code(r) == "UNAUTHENTICATED", path


def test_an_expired_session_is_refused(app: Any, engine: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        sign_in(c)
        token = c.cookies.get("twin_session")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "update sessions set created_at = now() - interval '9 hours', "
                    "expires_at = now() - interval '1 hour' where token_sha256 = :h"
                ),
                {"h": sha256_hex(token)},
            )
        r = c.get(f"{API}/auth/me")
        assert r.status_code == 401 and code(r) == "UNAUTHENTICATED"


def test_logout_revokes_the_session_everywhere_and_clears_the_cookie(app: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        csrf = sign_in(c)
        token = c.cookies.get("twin_session")
        r = c.post(f"{API}/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 204
        cleared = r.headers["set-cookie"].lower()
        assert "twin_session=" in cleared and ("max-age=0" in cleared or "expires=" in cleared)
    # the same cookie replayed from another tab or device no longer works
    with TestClient(app, cookies={"twin_session": token}) as other:
        assert other.get(f"{API}/auth/me").status_code == 401


def test_logout_needs_the_csrf_token(app: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        sign_in(c)
        r = c.post(f"{API}/auth/logout")
        assert r.status_code == 403 and code(r) == "CSRF_FAILED"
        assert c.get(f"{API}/auth/me").status_code == 200  # still signed in


def test_lax_cookie_does_not_weaken_csrf(app: Any) -> None:
    """With SameSite=Lax a cross-site form POST could carry the cookie; the CSRF header still
    stops it (a cross-site page can neither read nor set that header)."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        sign_in(c)
        for headers in ({}, {"X-CSRF-Token": "guessed"}, {"Origin": "https://evil.example"}):
            r = c.post(
                f"{API}/patients/2/what-if", json={"changes": {"carbs_g": -10}}, headers=headers
            )
            assert r.status_code == 403 and code(r) == "CSRF_FAILED", headers


def test_each_sign_in_issues_a_new_session_token(app: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        sign_in(c)
        a = c.cookies.get("twin_session")
        sign_in(c)
        b = c.cookies.get("twin_session")
    assert a and b and a != b  # no session fixation


def test_provider_list_is_public_and_reports_google_off_by_default(client: Any) -> None:
    r = client.get(f"{API}/auth/providers")
    assert r.status_code == 200 and r.json() == {"password": True, "google": False}


def test_password_sign_in_works_without_google_configured(client: Any) -> None:
    sign_in(client)
    assert client.get(f"{API}/auth/me").json()["role"] == "clinician"
