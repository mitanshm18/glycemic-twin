"""Google OpenID Connect, authorization-code flow with PKCE (M6, ADR-019). Standard library only.

The browser only ever carries the authorization request and the one-time code. The server
exchanges the code directly with Google's token endpoint over TLS, authenticating with the client
secret and the PKCE verifier, and reads the ID token from that response. Access and refresh tokens
are never stored, logged or sent to the browser.

ID token trust: the token comes straight from Google's token endpoint over a certificate-verified
HTTPS connection, which OpenID Connect Core 1.0 section 3.1.3.7 (step 6) accepts in place of
checking the token signature. The claims are still validated in full: issuer, audience (and
authorized party), expiry and issue time with a small clock-skew allowance, the nonce bound to this
flow, a verified email, and optionally the Workspace domain.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
SCOPES = "openid email profile"
CLOCK_SKEW_S = 120
HTTP_TIMEOUT_S = 10

# (url, form fields) -> parsed JSON body; raises OIDCError. Replaceable in tests.
Transport = Callable[[str, Mapping[str, str]], dict[str, Any]]


class OIDCError(Exception):
    """A sign-in failure with a stable, user-facing code (never contains tokens or secrets)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    hosted_domain: str | None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) per RFC 7636: 86 unreserved characters of 512 random bits."""
    verifier = secrets.token_urlsafe(64)
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
    hosted_domain: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "access_type": "online",
    }
    if hosted_domain:
        params["hd"] = hosted_domain  # a hint only; the returned claim is what is enforced
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def post_form(url: str, fields: Mapping[str, str]) -> dict[str, Any]:
    """POST application/x-www-form-urlencoded over verified HTTPS and parse the JSON reply."""
    if not url.startswith("https://"):
        raise OIDCError("google_exchange_failed", "token endpoint must use https")
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(dict(fields)).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as res:  # noqa: S310 (https only)
            body = json.loads(res.read().decode())
    except urllib.error.HTTPError as err:
        # Error bodies carry only an error code; keep that, never echo anything else.
        try:
            code = str(json.loads(err.read().decode()).get("error", "unknown"))
        except Exception:  # noqa: BLE001
            code = "unknown"
        raise OIDCError(
            "google_exchange_failed", f"token endpoint refused the code ({code})"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise OIDCError("google_exchange_failed", "could not reach the token endpoint") from None
    if not isinstance(body, dict):
        raise OIDCError("google_exchange_failed", "unexpected token endpoint response")
    return body


def exchange_code(
    transport: Transport,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
) -> str:
    """Trade the one-time code for tokens; return only the ID token (the rest is discarded)."""
    body = transport(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    id_token = body.get("id_token")
    if not isinstance(id_token, str) or id_token.count(".") != 2:
        raise OIDCError("google_exchange_failed", "the token response had no ID token")
    return id_token


def id_token_claims(id_token: str) -> dict[str, Any]:
    """Payload of a compact JWS (trust established by the direct TLS exchange; see module doc)."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise OIDCError("google_token_invalid", "the ID token could not be read") from None
    if not isinstance(claims, dict):
        raise OIDCError("google_token_invalid", "the ID token could not be read")
    return claims


def validate_claims(
    claims: Mapping[str, Any],
    *,
    client_id: str,
    nonce: str,
    hosted_domain: str | None = None,
    now: float | None = None,
) -> GoogleIdentity:
    t = time.time() if now is None else now
    if claims.get("iss") not in ISSUERS:
        raise OIDCError("google_token_invalid", "unexpected issuer")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if client_id not in audiences:
        raise OIDCError("google_token_invalid", "token was issued for another client")
    if len(audiences) > 1 and claims.get("azp") != client_id:
        raise OIDCError("google_token_invalid", "token authorized party mismatch")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int | float) or exp + CLOCK_SKEW_S < t:
        raise OIDCError("google_token_invalid", "token expired")
    if not isinstance(iat, int | float) or iat - CLOCK_SKEW_S > t:
        raise OIDCError("google_token_invalid", "token issued in the future")
    sent = claims.get("nonce")
    if not isinstance(sent, str) or not secrets.compare_digest(sent.encode(), nonce.encode()):
        raise OIDCError("google_token_invalid", "nonce mismatch")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        raise OIDCError("google_token_invalid", "token has no subject")
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise OIDCError("google_email_unverified", "the Google account has no email address")
    if claims.get("email_verified") not in (True, "true"):
        raise OIDCError("google_email_unverified", "the Google account's email is not verified")
    hd = claims.get("hd")
    if hosted_domain and hd != hosted_domain:
        raise OIDCError("google_wrong_domain", "account is outside the allowed domain")
    return GoogleIdentity(subject=sub, email=email.strip().lower(), hosted_domain=hd)
