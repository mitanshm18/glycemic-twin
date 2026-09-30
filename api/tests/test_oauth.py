"""Google sign-in (M6, ADR-019): state binding, single use and expiry, PKCE/nonce, callback
validation, the provisioning rule (admin-linked identities only; never create users), account
status, redirect safety and secret hygiene. Google's token endpoint is replaced by a stand-in; every
other step is the real code path (disposable PostgreSQL; SYNTHETIC data)."""

from __future__ import annotations

import time
import urllib.parse
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from api_support import SOURCE_LABEL
from sqlalchemy import text
from test_oidc import jwt
from twin_api import oidc
from twin_api.security import sha256_hex

API = "/api/v1"
CLIENT_ID = "test-client.apps.googleusercontent.com"
REDIRECT = "http://testserver/api/v1/auth/google/callback"
SECRET = "test-only-client-secret"


class FakeGoogle:
    """Stands in for https://oauth2.googleapis.com/token and records what the server sent."""

    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.fail = False
        self.calls: list[dict[str, str]] = []

    def __call__(self, url: str, fields: Any) -> dict[str, Any]:
        assert url == oidc.TOKEN_URL
        self.calls.append(dict(fields))
        if self.fail:
            raise oidc.OIDCError("google_exchange_failed", "token endpoint unreachable")
        return {
            "id_token": jwt(self.claims),
            "access_token": "ya29.never-exposed",
            "expires_in": 3599,
        }


@pytest.fixture(scope="module")
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture(scope="module")
def gapp(db_url: str, loaded: dict[str, Any], google: FakeGoogle) -> Any:
    from twin_api.app import create_app
    from twin_api.routers.oauth import oidc_transport
    from twin_api.settings import Settings

    settings = Settings(
        database_url=db_url,
        environment="test",
        cookie_secure=False,
        source_label=SOURCE_LABEL,
        google_client_id=CLIENT_ID,
        google_client_secret=SECRET,
        google_redirect_uri=REDIRECT,
    )
    app = create_app(settings)
    app.dependency_overrides[oidc_transport] = lambda: google
    return app


@pytest.fixture
def gclient(gapp: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    with TestClient(gapp) as c:
        yield c


def link(engine: Any, username: str, email: str) -> None:
    from twin_api.auth import link_identity
    from twin_api.db import make_sessionmaker, session_scope

    with session_scope(make_sessionmaker(engine)) as s:
        link_identity(s, username, "google", email, created_by="tests")


def fresh_email() -> str:
    return f"clin-{uuid.uuid4().hex[:8]}@example.org"


def fresh_sub() -> str:
    return str(uuid.uuid4().int)[:21]


def start(c: Any, next_path: str | None = None) -> dict[str, str]:
    params = {"next": next_path} if next_path else None
    r = c.get(f"{API}/auth/google/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.headers["location"]).query))


def id_claims(flow_nonce: str, email: str, sub: str, **over: Any) -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "azp": CLIENT_ID,
        "sub": sub,
        "email": email,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        "nonce": flow_nonce,
        **over,
    }


def callback(c: Any, state: str, **params: str) -> Any:
    q = {"code": "4/one-time-code", "state": state, **params}
    return c.get(f"{API}/auth/google/callback", params=q, follow_redirects=False)


def auth_error(r: Any) -> str | None:
    assert r.status_code == 303, r.text
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.headers["location"]).query))
    return q.get("auth_error")


def count(engine: Any, sql: str, **params: Any) -> int:
    with engine.connect() as c:
        return int(c.scalar(text(sql), params) or 0)


# ------------------------------------------------------------------------------------ configuration


def test_google_is_reported_only_when_fully_configured(client: Any, gclient: Any) -> None:
    assert client.get(f"{API}/auth/providers").json()["google"] is False
    assert gclient.get(f"{API}/auth/providers").json() == {"password": True, "google": True}


def test_unconfigured_server_gives_a_clear_error_and_starts_nothing(
    client: Any, engine: Any
) -> None:
    before = count(engine, "select count(*) from oauth_flows")
    r = client.get(f"{API}/auth/google/start", follow_redirects=False)
    assert auth_error(r) == "google_not_configured"
    r = client.get(f"{API}/auth/google/callback?code=x&state=y", follow_redirects=False)
    assert auth_error(r) == "google_not_configured"
    assert count(engine, "select count(*) from oauth_flows") == before


# ------------------------------------------------------------------------------------ start


def test_start_binds_a_hashed_single_use_state_to_this_browser(gclient: Any, engine: Any) -> None:
    r = gclient.get(f"{API}/auth/google/start", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(oidc.AUTHORIZE_URL)
    assert r.headers["cache-control"] == "no-store"
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.headers["location"]).query))
    assert q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT
    assert q["code_challenge_method"] == "S256" and len(q["state"]) > 40 and len(q["nonce"]) > 40
    assert SECRET not in r.headers["location"]
    cookie = r.headers["set-cookie"].lower()
    assert "twin_oauth_state=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/v1/auth/google" in cookie
    # only the SHA-256 of the state is stored; the PKCE verifier is not the challenge
    assert (
        count(
            engine,
            "select count(*) from oauth_flows where state_sha256 = :h",
            h=sha256_hex(q["state"]),
        )
        == 1
    )
    assert (
        count(engine, "select count(*) from oauth_flows where state_sha256 = :s", s=q["state"]) == 0
    )
    assert (
        count(
            engine,
            "select count(*) from oauth_flows where code_verifier = :c",
            c=q["code_challenge"],
        )
        == 0
    )


@pytest.mark.parametrize(
    ("asked", "kept"),
    [
        ("/patients/2?at=2021-06-05T13:00:00", "/patients/2?at=2021-06-05T13:00:00"),
        ("//evil.example/x", "/patients"),
        ("/\\evil.example", "/patients"),
        ("https://evil.example", "/patients"),
        ("/login?next=/x", "/patients"),
    ],
)
def test_post_sign_in_destination_stays_inside_the_app(
    gclient: Any, engine: Any, asked: str, kept: str
) -> None:
    q = start(gclient, asked)
    with engine.connect() as c:
        stored = c.scalar(
            text("select next_path from oauth_flows where state_sha256 = :h"),
            {"h": sha256_hex(q["state"])},
        )
    assert stored == kept


# ------------------------------------------------------------------------------------ success


def test_provisioned_account_signs_in_with_an_ordinary_session(
    gclient: Any, engine: Any, google: FakeGoogle
) -> None:
    email, sub = fresh_email(), fresh_sub()
    link(engine, "clinician", email)
    q = start(gclient, "/patients/2")
    google.claims = id_claims(q["nonce"], email.upper(), sub)
    r = callback(gclient, q["state"])
    assert r.status_code == 303 and r.headers["location"] == "/patients/2"
    assert r.headers["cache-control"] == "no-store"
    cookies = " ".join(r.headers.get_list("set-cookie")).lower()
    assert "twin_session=" in cookies and "samesite=lax" in cookies and "httponly" in cookies
    # nothing from Google reaches the browser
    blob = r.headers["location"] + cookies + r.text
    for leaked in ("ya29", "4/one-time-code", SECRET.lower(), "id_token"):
        assert leaked not in blob
    # the server sent the secret and the PKCE verifier to the token endpoint, not the browser
    sent = google.calls[-1]
    assert sent["client_secret"] == SECRET and len(sent["code_verifier"]) >= 43
    # a normal session: me, csrf, logout
    me = gclient.get(f"{API}/auth/me").json()
    assert me["username"] == "clinician"
    csrf = gclient.get(f"{API}/auth/csrf").json()["csrf_token"]
    assert gclient.post(f"{API}/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert gclient.get(f"{API}/auth/me").status_code == 401
    # first use bound Google's stable subject; the flow is gone
    assert (
        count(
            engine,
            "select count(*) from user_identities where email = :e and subject = :s",
            e=email,
            s=sub,
        )
        == 1
    )
    assert (
        count(
            engine,
            "select count(*) from oauth_flows where state_sha256 = :h",
            h=sha256_hex(q["state"]),
        )
        == 0
    )


def test_bound_identity_signs_in_by_subject_even_if_the_email_changed(
    gclient: Any, engine: Any, google: FakeGoogle
) -> None:
    email, sub = fresh_email(), fresh_sub()
    link(engine, "clinician", email)
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, sub)
    assert callback(gclient, q["state"]).headers["location"] == "/patients"
    q = start(gclient)
    google.claims = id_claims(q["nonce"], "renamed@" + email.split("@")[1], sub)
    r = callback(gclient, q["state"])
    assert r.status_code == 303 and r.headers["location"] == "/patients"


# ------------------------------------------------------------------------------------ provisioning


def test_unprovisioned_google_account_is_refused_and_no_user_is_created(
    gclient: Any, engine: Any, google: FakeGoogle
) -> None:
    users = count(engine, "select count(*) from users")
    idents = count(engine, "select count(*) from user_identities")
    q = start(gclient)
    stranger = f"stranger-{uuid.uuid4().hex[:6]}@gmail.com"
    google.claims = id_claims(q["nonce"], stranger, fresh_sub())
    r = callback(gclient, q["state"])
    assert auth_error(r) == "google_not_provisioned"
    assert "twin_session=" not in " ".join(r.headers.get_list("set-cookie"))
    assert gclient.get(f"{API}/auth/me").status_code == 401
    assert count(engine, "select count(*) from users") == users
    assert count(engine, "select count(*) from user_identities") == idents
    # audited without the address itself
    with engine.connect() as c:
        details = [
            d
            for (d,) in c.execute(
                text("select detail::text from audit_log where action = 'login_google'")
            )
        ]
    assert any("google_not_provisioned" in d for d in details)
    assert not any(stranger in d for d in details)


def test_a_different_google_account_cannot_take_over_a_bound_email(
    gclient: Any, engine: Any, google: FakeGoogle
) -> None:
    email, sub = fresh_email(), fresh_sub()
    link(engine, "clinician", email)
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, sub)
    callback(gclient, q["state"])
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, fresh_sub())  # same address, other account
    assert auth_error(callback(gclient, q["state"])) == "google_identity_mismatch"


def test_inactive_or_locked_users_cannot_sign_in_with_google(
    gclient: Any, engine: Any, google: FakeGoogle
) -> None:
    from twin_api.auth import create_user
    from twin_api.db import make_sessionmaker, session_scope

    name = f"g{uuid.uuid4().hex[:8]}"
    with session_scope(make_sessionmaker(engine)) as s:
        create_user(s, name, "another-password-123", "clinician")
    email = fresh_email()
    link(engine, name, email)
    for sql in (
        "update users set is_active = false where username = :u",
        "update users set is_active = true, locked_until = now() + interval '10 minutes' where username = :u",
    ):
        with engine.begin() as c:
            c.execute(text(sql), {"u": name})
        q = start(gclient)
        google.claims = id_claims(q["nonce"], email, fresh_sub())
        assert auth_error(callback(gclient, q["state"])) == "account_unavailable"


def test_linking_needs_an_existing_user_and_a_unique_account(engine: Any, loaded: Any) -> None:
    from twin_api.errors import ApiError

    with pytest.raises(ApiError) as e:
        link(engine, "no-such-user", fresh_email())
    assert e.value.status == 404
    email = fresh_email()
    link(engine, "clinician", email)
    with pytest.raises(ApiError) as e:
        link(engine, "admin", email.upper())
    assert e.value.status == 409
    with pytest.raises(ValueError):
        link(engine, "clinician", "not-an-email")


# ------------------------------------------------------------------------------------ callback checks


def test_state_must_come_from_the_browser_that_started(
    gclient: Any, gapp: Any, engine: Any, google: FakeGoogle
) -> None:
    from fastapi.testclient import TestClient

    email = fresh_email()
    link(engine, "clinician", email)
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, fresh_sub())
    with TestClient(gapp) as victim:  # login CSRF: a link carrying someone else's state
        assert auth_error(callback(victim, q["state"])) == "google_state_invalid"
    assert auth_error(callback(gclient, "tampered-" + q["state"])) == "google_state_invalid"


def test_state_is_single_use(gclient: Any, gapp: Any, engine: Any, google: FakeGoogle) -> None:
    from fastapi.testclient import TestClient

    email = fresh_email()
    link(engine, "clinician", email)
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, fresh_sub())
    assert callback(gclient, q["state"]).headers["location"] == "/patients"
    # replaying the same state and cookie (e.g. from browser history) is refused
    with TestClient(gapp, cookies={"twin_oauth_state": q["state"]}) as replay:
        assert auth_error(callback(replay, q["state"])) == "google_state_invalid"


def test_expired_flow_is_refused(gclient: Any, engine: Any, google: FakeGoogle) -> None:
    q = start(gclient)
    with engine.begin() as c:
        c.execute(
            text(
                "update oauth_flows set created_at = now() - interval '1 hour', "
                "expires_at = now() - interval '1 minute' where state_sha256 = :h"
            ),
            {"h": sha256_hex(q["state"])},
        )
    google.claims = id_claims(q["nonce"], fresh_email(), fresh_sub())
    assert auth_error(callback(gclient, q["state"])) == "google_state_invalid"


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"nonce": "someone-elses-nonce"}, "google_token_invalid"),
        ({"aud": "another-client"}, "google_token_invalid"),
        ({"iss": "https://evil.example"}, "google_token_invalid"),
        ({"exp": int(time.time()) - 3600}, "google_token_invalid"),
        ({"email_verified": False}, "google_email_unverified"),
    ],
)
def test_invalid_id_tokens_are_refused(
    gclient: Any, engine: Any, google: FakeGoogle, over: dict[str, Any], reason: str
) -> None:
    email = fresh_email()
    link(engine, "clinician", email)
    q = start(gclient)
    google.claims = id_claims(q["nonce"], email, fresh_sub(), **over)
    r = callback(gclient, q["state"])
    assert auth_error(r) == reason
    assert gclient.get(f"{API}/auth/me").status_code == 401


def test_cancel_and_exchange_failure_are_explained(gclient: Any, google: FakeGoogle) -> None:
    q = start(gclient, "/model")
    r = gclient.get(
        f"{API}/auth/google/callback",
        params={"state": q["state"], "error": "access_denied"},
        follow_redirects=False,
    )
    assert auth_error(r) == "google_cancelled"
    assert "next=%2Fmodel" in r.headers["location"]  # the user returns to where they were going
    q = start(gclient)
    google.fail = True
    try:
        assert auth_error(callback(gclient, q["state"])) == "google_exchange_failed"
    finally:
        google.fail = False


def test_the_callback_code_and_state_never_reach_access_logs() -> None:
    import logging

    import twin_api.routers.oauth  # noqa: F401  (installs the filter)

    rec = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:5000",
            "GET",
            "/api/v1/auth/google/callback?code=4/secret-code&state=s3cr3t",
            "1.1",
            303,
        ),
        None,
    )
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(rec)
    line = rec.getMessage()
    assert "secret-code" not in line and "s3cr3t" not in line and "callback?[redacted]" in line
