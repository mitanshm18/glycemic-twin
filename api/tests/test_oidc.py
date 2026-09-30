"""Google OIDC helpers (pure; no database, no network): PKCE, authorization URL, code exchange and
ID-token claim validation (M6, ADR-019)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
from typing import Any

import pytest
from twin_api import oidc

CLIENT = "test-client.apps.googleusercontent.com"
NONCE = "n-0123456789abcdef"


def jwt(claims: dict[str, Any]) -> str:
    """An unsigned compact token: enough for claim tests (trust comes from the TLS exchange)."""

    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'RS256', 'typ': 'JWT'})}.{seg(claims)}.sig"


def claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "azp": CLIENT,
        "sub": "110169484474386276334",
        "email": "Clinician@Example.org",
        "email_verified": True,
        "iat": now - 5,
        "exp": now + 3600,
        "nonce": NONCE,
    }
    base.update(over)
    return base


def test_pkce_pair_is_rfc7636_s256() -> None:
    verifier, challenge = oidc.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert set(verifier) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()
    assert oidc.pkce_pair()[0] != verifier


def test_authorize_url_carries_state_nonce_and_pkce_only() -> None:
    url = oidc.authorize_url(
        client_id=CLIENT,
        redirect_uri="http://localhost:3000/api/v1/auth/google/callback",
        state="s",
        nonce="n",
        code_challenge="c",
    )
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query))
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == oidc.AUTHORIZE_URL
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["scope"] == "openid email profile"
    assert {q["state"], q["nonce"], q["code_challenge"]} == {"s", "n", "c"}
    assert "client_secret" not in q and "hd" not in q


def test_valid_claims_give_a_normalised_identity() -> None:
    ident = oidc.validate_claims(claims(), client_id=CLIENT, nonce=NONCE)
    assert ident.subject == "110169484474386276334"
    assert ident.email == "clinician@example.org"


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"iss": "https://evil.example"}, "google_token_invalid"),
        ({"aud": "someone-else"}, "google_token_invalid"),
        ({"aud": [CLIENT, "other"], "azp": "other"}, "google_token_invalid"),
        ({"exp": int(time.time()) - 3600}, "google_token_invalid"),
        ({"iat": int(time.time()) + 3600}, "google_token_invalid"),
        ({"nonce": "replayed-nonce"}, "google_token_invalid"),
        ({"nonce": None}, "google_token_invalid"),
        ({"sub": ""}, "google_token_invalid"),
        ({"email_verified": False}, "google_email_unverified"),
        ({"email": None}, "google_email_unverified"),
    ],
)
def test_invalid_claims_are_refused(over: dict[str, Any], code: str) -> None:
    with pytest.raises(oidc.OIDCError) as e:
        oidc.validate_claims(claims(**over), client_id=CLIENT, nonce=NONCE)
    assert e.value.code == code


def test_hosted_domain_is_enforced_from_the_claim() -> None:
    with pytest.raises(oidc.OIDCError) as e:
        oidc.validate_claims(claims(), client_id=CLIENT, nonce=NONCE, hosted_domain="clinic.org")
    assert e.value.code == "google_wrong_domain"
    ok = oidc.validate_claims(
        claims(hd="clinic.org"), client_id=CLIENT, nonce=NONCE, hosted_domain="clinic.org"
    )
    assert ok.hosted_domain == "clinic.org"


def test_small_clock_skew_is_tolerated() -> None:
    now = time.time()
    oidc.validate_claims(claims(exp=int(now) - 30), client_id=CLIENT, nonce=NONCE, now=now)


def test_exchange_sends_secret_and_verifier_server_side_and_keeps_only_the_id_token() -> None:
    seen: dict[str, Any] = {}

    def transport(url: str, fields: Any) -> dict[str, Any]:
        seen.update(url=url, fields=dict(fields))
        return {"id_token": jwt(claims()), "access_token": "ya29.secret", "refresh_token": "1//x"}

    token = oidc.exchange_code(
        transport,
        code="4/code",
        client_id=CLIENT,
        client_secret="shh",
        redirect_uri="http://localhost:3000/cb",
        code_verifier="v" * 50,
    )
    assert seen["url"] == oidc.TOKEN_URL
    assert seen["fields"]["grant_type"] == "authorization_code"
    assert seen["fields"]["client_secret"] == "shh" and seen["fields"]["code_verifier"] == "v" * 50
    assert "ya29" not in token and oidc.id_token_claims(token)["sub"]


@pytest.mark.parametrize("body", [{}, {"id_token": "not-a-jwt"}, {"id_token": 3}])
def test_exchange_without_an_id_token_fails_cleanly(body: dict[str, Any]) -> None:
    with pytest.raises(oidc.OIDCError) as e:
        oidc.exchange_code(
            lambda u, f: body,
            code="c",
            client_id=CLIENT,
            client_secret="s",
            redirect_uri="r",
            code_verifier="v",
        )
    assert e.value.code == "google_exchange_failed"


def test_garbled_id_token_is_refused() -> None:
    with pytest.raises(oidc.OIDCError) as e:
        oidc.id_token_claims("a.%%%%.c")
    assert e.value.code == "google_token_invalid"


def test_token_endpoint_must_be_https() -> None:
    with pytest.raises(oidc.OIDCError):
        oidc.post_form("http://oauth2.googleapis.com/token", {})
