"""Server-side sessions, role checks, CSRF and the audit log.

Flow: POST /auth/login verifies the Argon2id hash (or, M6, the Google callback maps a verified
Google identity to an admin-linked user), creates a ``sessions`` row holding only the SHA-256 of a
random token, and sets that token in an HttpOnly, SameSite=Lax (and, outside local development,
Secure) cookie. Every request looks the session up server-side, so logout and expiry take effect
immediately. State-changing requests must also send the per-session CSRF token in
``X-CSRF-Token``; that header, not the SameSite attribute, is the CSRF defence, so Lax is safe.
Lax (M6, ADR-019) lets the cookie accompany top-level navigations that began on another site: with
Strict, a page first opened from an external link lost the session on every reload, and the
Google callback could not land a signed-in user. Failed logins are counted per user and lock the
account for a while.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from twin_api import errors
from twin_api.db import session_scope
from twin_api.models import AuditLog, AuditOutcome, User, UserIdentity, UserRole, UserSession
from twin_api.security import (
    burn_verification_time,
    hash_password,
    new_token,
    same,
    sha256_hex,
    verify_password,
)
from twin_api.settings import Settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _now() -> datetime:
    return datetime.now(UTC)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    with session_scope(factory) as s:
        yield s


def audit(
    request: Request,
    action: str,
    outcome: AuditOutcome,
    *,
    user: User | None = None,
    username: str | None = None,
    status_code: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Written in its own transaction, so denials and failures are kept even when the request fails."""
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    with session_scope(factory) as s:
        s.add(
            AuditLog(
                user_id=user.id if user else None,
                username=user.username if user else username,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                status_code=status_code,
                ip=client_ip(request),
                detail={"method": request.method, "path": request.url.path, **(detail or {})},
            )
        )


@dataclass(frozen=True)
class Principal:
    user: User
    session: UserSession


def create_user(session: Session, username: str, password: str, role: str) -> User:
    if session.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise errors.conflict(f"user {username!r} already exists")
    user = User(username=username, password_hash=hash_password(password), role=UserRole(role))
    session.add(user)
    session.flush()
    return user


def login(
    session: Session,
    settings: Settings,
    request: Request,
    response: Response,
    username: str,
    password: str,
) -> tuple[User, str, datetime]:
    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    now = _now()
    if user is None or not user.is_active:
        burn_verification_time(password)
        audit(
            request,
            "login",
            AuditOutcome.denied,
            username=username,
            status_code=401,
            detail={"reason": "unknown or inactive user"},
        )
        raise errors.unauthenticated("invalid username or password")
    if user.locked_until is not None and user.locked_until > now:
        burn_verification_time(password)
        audit(
            request,
            "login",
            AuditOutcome.denied,
            user=user,
            status_code=401,
            detail={"reason": "account temporarily locked"},
        )
        raise errors.unauthenticated("invalid username or password")
    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
        session.commit()
        audit(
            request,
            "login",
            AuditOutcome.denied,
            user=user,
            status_code=401,
            detail={"reason": "wrong password"},
        )
        raise errors.unauthenticated("invalid username or password")
    csrf, expires = start_session(session, settings, request, response, user)
    audit(request, "login", AuditOutcome.success, user=user, status_code=200)
    return user, csrf, expires


def start_session(
    session: Session, settings: Settings, request: Request, response: Response, user: User
) -> tuple[str, datetime]:
    """New server-side session for an authenticated user; sets the cookie, returns the CSRF token.

    Always a fresh random token (no session fixation). Shared by password and Google sign-in.
    """
    now = _now()
    token, csrf = new_token(), new_token()
    expires = now + timedelta(minutes=settings.session_ttl_minutes)
    session.add(
        UserSession(
            user_id=user.id,
            token_sha256=sha256_hex(token),
            csrf_sha256=sha256_hex(csrf),
            expires_at=expires,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:256],
        )
    )
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    session.flush()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return csrf, expires


def logout(session: Session, principal: Principal, settings: Settings, response: Response) -> None:
    principal.session.revoked_at = _now()
    session.flush()
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:  # noqa: B008
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise errors.unauthenticated()
    now = _now()
    row = db.scalar(select(UserSession).where(UserSession.token_sha256 == sha256_hex(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise errors.unauthenticated("session expired or signed out")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise errors.unauthenticated("session expired or signed out")
    if request.method in UNSAFE:
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not same(sha256_hex(sent), row.csrf_sha256):
            audit(request, "csrf_check", AuditOutcome.denied, user=user, status_code=403)
            raise errors.csrf_failed()
    row.last_seen_at = now
    return Principal(user, row)


# ------------------------------------------------------------------ external identities (M6)


def normalize_email(email: str) -> str:
    e = email.strip().lower()
    if e.count("@") != 1 or e.startswith("@") or e.endswith("@") or len(e) > 320:
        raise ValueError(f"not an email address: {email!r}")
    return e


def link_identity(
    session: Session, username: str, provider: str, email: str, created_by: str | None = None
) -> UserIdentity:
    """Admin provisioning: allow ``email``'s Google account to sign in as ``username``.

    The account is identified by email until its first sign-in, when Google's stable subject is
    bound; from then on the subject must match. Nothing here creates a user.
    """
    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise errors.not_found(f"user {username!r}")
    e = normalize_email(email)
    if session.scalar(
        select(UserIdentity).where(UserIdentity.provider == provider, UserIdentity.email == e)
    ):
        raise errors.conflict(f"{provider} account {e} is already linked")
    ident = UserIdentity(user_id=user.id, provider=provider, email=e, created_by=created_by)
    session.add(ident)
    session.flush()
    return ident


def unlink_identities(session: Session, username: str, provider: str) -> int:
    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise errors.not_found(f"user {username!r}")
    rows = list(
        session.scalars(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id, UserIdentity.provider == provider
            )
        )
    )
    for r in rows:
        session.delete(r)
    session.flush()
    return len(rows)


def require_role(*roles: UserRole) -> Callable[..., Principal]:
    def dep(request: Request, principal: Principal = Depends(current_principal)) -> Principal:  # noqa: B008
        if principal.user.role not in roles:
            audit(
                request,
                "authorize",
                AuditOutcome.denied,
                user=principal.user,
                status_code=403,
                detail={"required": [r.value for r in roles]},
            )
            raise errors.forbidden()
        return principal

    return dep


any_user = require_role(UserRole.clinician, UserRole.admin)
admin_only = require_role(UserRole.admin)
