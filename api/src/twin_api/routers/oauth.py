"""Sign-in providers and the server-side Google OpenID Connect flow (M6, ADR-019).

GET /auth/providers          which sign-in methods this server offers (public)
GET /auth/google/start       begin a Google sign-in (browser navigation)
GET /auth/google/callback    Google returns here (through the web app's /api/v1 proxy)

Security properties:
- state: 256-bit random, bound to the starting browser by an HttpOnly flow cookie and stored only
  as its SHA-256 in ``oauth_flows``; single use (deleted on first callback) and short-lived.
- nonce: random per flow, required to match the ID token's ``nonce``.
- PKCE (S256): the verifier never leaves the server.
- the code is exchanged server to server; tokens are never stored, logged or sent to the browser.
- a Google account signs in only through an admin-linked ``user_identities`` row; no account is
  ever created here. Inactive or locked users are refused.
- on success the browser receives the same session cookie as password sign-in, nothing else.
- every outcome is audited without tokens, codes or the email itself (domain + SHA-256 only).
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from twin_api import oidc
from twin_api.auth import audit, get_db, start_session
from twin_api.models import AuditOutcome, OAuthFlow, User, UserIdentity
from twin_api.security import new_token, same, sha256_hex
from twin_api.settings import Settings

router = APIRouter(tags=["auth"])
DB = Annotated[Session, Depends(get_db)]


class _RedactOAuthQuery(logging.Filter):
    """Keep the one-time code and state of the Google callback out of access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/api/v1/auth/google/callback?"):
                record.args = (*args[:2], "/api/v1/auth/google/callback?[redacted]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactOAuthQuery())

PROVIDER = "google"
FLOW_COOKIE = "twin_oauth_state"
FLOW_COOKIE_PATH = "/api/v1/auth/google"
DEFAULT_NEXT = "/patients"


def oidc_transport() -> oidc.Transport:
    """The HTTPS client for the token endpoint (overridden in tests; never a fake in the app)."""
    return oidc.post_form


Transport = Annotated[oidc.Transport, Depends(oidc_transport)]


class ProvidersOut(BaseModel):
    password: bool
    google: bool


def _now() -> datetime:
    return datetime.now(UTC)


def safe_next(raw: str | None) -> str:
    """Only a path inside this app (no scheme, host, backslash or control characters)."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return DEFAULT_NEXT
    if any(c == "\\" or ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return DEFAULT_NEXT
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme or parts.netloc or parts.path.startswith("/login") or len(raw) > 512:
        return DEFAULT_NEXT
    return raw


def _no_store(r: RedirectResponse) -> RedirectResponse:
    r.headers["Cache-Control"] = "no-store"
    r.headers["Referrer-Policy"] = "no-referrer"
    return r


def _clear_flow_cookie(r: RedirectResponse, settings: Settings) -> None:
    r.delete_cookie(
        FLOW_COOKIE,
        path=FLOW_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _email_detail(email: str | None) -> dict[str, str]:
    if not email:
        return {}
    return {"email_domain": email.rsplit("@", 1)[-1], "email_sha256": sha256_hex(email)}


def _fail(
    request: Request,
    code: str,
    *,
    next_path: str | None = None,
    user: User | None = None,
    email: str | None = None,
    audited: bool = True,
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    if audited:
        audit(
            request,
            "login_google",
            AuditOutcome.denied,
            user=user,
            status_code=303,
            detail={"reason": code, **_email_detail(email)},
        )
    query = {"auth_error": code}
    if next_path and next_path != DEFAULT_NEXT:
        query["next"] = next_path
    r = RedirectResponse(f"/login?{urllib.parse.urlencode(query)}", status_code=303)
    _clear_flow_cookie(r, settings)
    return _no_store(r)


@router.get("/auth/providers", response_model=ProvidersOut)
def providers(request: Request) -> ProvidersOut:
    settings: Settings = request.app.state.settings
    return ProvidersOut(password=True, google=settings.google_enabled)


@router.get("/auth/google/start")
def google_start(
    request: Request, db: DB, next: Annotated[str | None, Query(max_length=512)] = None
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    target = safe_next(next)
    if not settings.google_enabled:
        return _fail(request, "google_not_configured", next_path=target, audited=False)
    assert settings.google_client_id and settings.google_redirect_uri  # google_enabled
    now = _now()
    db.execute(delete(OAuthFlow).where(OAuthFlow.expires_at <= now))  # housekeeping
    state, nonce = new_token(), new_token()
    verifier, challenge = oidc.pkce_pair()
    ttl = timedelta(minutes=settings.oauth_flow_ttl_minutes)
    db.add(
        OAuthFlow(
            state_sha256=sha256_hex(state),
            provider=PROVIDER,
            nonce=nonce,
            code_verifier=verifier,
            next_path=target,
            expires_at=now + ttl,
        )
    )
    db.commit()
    url = oidc.authorize_url(
        client_id=settings.google_client_id,
        redirect_uri=settings.google_redirect_uri,
        state=state,
        nonce=nonce,
        code_challenge=challenge,
        hosted_domain=settings.google_hosted_domain,
    )
    r = RedirectResponse(url, status_code=302)
    r.set_cookie(
        FLOW_COOKIE,
        state,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",  # must survive the top-level return from accounts.google.com
        path=FLOW_COOKIE_PATH,
    )
    return _no_store(r)


def _resolve(db: Session, ident: oidc.GoogleIdentity) -> tuple[UserIdentity | None, str | None]:
    """The admin-linked identity for this Google account, or the reason there is none."""
    by_subject = db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == PROVIDER, UserIdentity.subject == ident.subject
        )
    )
    if by_subject is not None:
        return by_subject, None
    by_email = db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == PROVIDER, UserIdentity.email == ident.email
        )
    )
    if by_email is None:
        return None, "google_not_provisioned"
    if by_email.subject is not None and by_email.subject != ident.subject:
        # the linked email now belongs to a different Google account: refuse, never rebind
        return None, "google_identity_mismatch"
    by_email.subject = ident.subject  # first sign-in binds Google's stable subject
    return by_email, None


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    db: DB,
    transport: Transport,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    if not settings.google_enabled:
        return _fail(request, "google_not_configured", audited=False)
    assert settings.google_client_id and settings.google_client_secret
    assert settings.google_redirect_uri

    # 1. the flow: state from Google must equal the state bound to this browser, and be unused
    now = _now()
    cookie_state = request.cookies.get(FLOW_COOKIE)
    found: tuple[str, datetime, str, str, str] | None = None
    if state and cookie_state and same(state, cookie_state):
        flow = db.get(OAuthFlow, sha256_hex(state))
        if flow is not None:
            found = (flow.provider, flow.expires_at, flow.next_path, flow.nonce, flow.code_verifier)
            db.delete(flow)  # single use, whatever happens next
            db.commit()
    if found is None or found[0] != PROVIDER or found[1] <= now:
        return _fail(request, "google_state_invalid")
    _, _, target, nonce, code_verifier = found

    # 2. Google's answer
    if error:
        reason = "google_cancelled" if error == "access_denied" else "google_denied"
        return _fail(request, reason, next_path=target)
    if not code:
        return _fail(request, "google_state_invalid", next_path=target)

    # 3. code -> ID token (server to server) -> validated identity
    try:
        id_token = oidc.exchange_code(
            transport,
            code=code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            redirect_uri=settings.google_redirect_uri,
            code_verifier=code_verifier,
        )
        ident = oidc.validate_claims(
            oidc.id_token_claims(id_token),
            client_id=settings.google_client_id,
            nonce=nonce,
            hosted_domain=settings.google_hosted_domain,
        )
    except oidc.OIDCError as err:
        return _fail(request, err.code, next_path=target)

    # 4. provisioned identity -> active user (never created here)
    link, unlinked = _resolve(db, ident)
    if link is None:
        db.rollback()
        return _fail(
            request, unlinked or "google_not_provisioned", next_path=target, email=ident.email
        )
    user = db.get(User, link.user_id)
    if (
        user is None
        or not user.is_active
        or (user.locked_until is not None and user.locked_until > now)
    ):
        db.rollback()
        return _fail(request, "account_unavailable", next_path=target, user=user, email=ident.email)

    # 5. the ordinary session (same cookie, same lifetime, same CSRF scheme as password sign-in)
    r = _no_store(RedirectResponse(target, status_code=303))
    start_session(db, settings, request, r, user)
    link.last_used_at = now
    db.commit()
    _clear_flow_cookie(r, settings)
    audit(
        request,
        "login_google",
        AuditOutcome.success,
        user=user,
        status_code=303,
        detail=_email_detail(ident.email),
    )
    return r
