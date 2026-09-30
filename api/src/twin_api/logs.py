"""Operational logging: one JSON object per line, a request id on every line, secrets scrubbed.

Standard library only. ``configure_logging`` installs the format on the root logger (uvicorn's own
lines included); ``RequestLog`` is the ASGI middleware that gives each request an id and logs one
line when it ends. What is never logged: request or response bodies, cookies, headers other than
the method and path, query strings (they can carry OAuth codes and state), and database bound
parameters (the engine hides them). ``Redact`` is a last line of defence on every record's text.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "x-request-id"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# health checks run every few seconds: their lines are DEBUG, so they don't drown real traffic
API_PREFIX = "/api/v1"
QUIET_PATHS = (f"{API_PREFIX}/health", f"{API_PREFIX}/ready")

# ------------------------------------------------------------------ redaction

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # bearer tokens (before key=value, which would otherwise take "Bearer" as the value)
    (re.compile(r"(?P<k>\bbearer\s+)[A-Za-z0-9._~+/=-]+", re.I), r"\g<k>***"),
    # user:password@ in any URL (database URLs in connection errors)
    (
        re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^:/@\s]+):[^@\s]+@", re.I),
        r"\g<scheme>\g<user>:***@",
    ),
    # key=value pairs whose key names a secret (query strings, form bodies, repr()s)
    (
        re.compile(
            r"(?P<k>\b(?:password|passwd|secret|client_secret|token|access_token|id_token|refresh_token|"
            r"code|code_verifier|state|nonce|csrf|csrf_token|session|cookie|authorization)\b"
            r"[\"']?\s*[=:]\s*[\"']?)(?P<v>[^\s&,;\"'}]+)",
            re.I,
        ),
        r"\g<k>***",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class Redact(logging.Filter):
    """Scrub secrets from the rendered message and from exception text of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        scrubbed = redact(message)
        if scrubbed != message:
            record.msg, record.args = scrubbed, None
        return True


# ------------------------------------------------------------------ format


class JsonFormatter(logging.Formatter):
    """{"ts", "level", "logger", "msg", "request_id", ...fields, "exc"} on one line."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = getattr(record, "request_id", None) or request_id.get()
        if rid:
            out["request_id"] = rid
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            out.update(fields)
        if record.exc_info and record.exc_info[0] is not None:
            out["exc_type"] = record.exc_info[0].__name__
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Readable single lines for local development; same content, same redaction."""

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None) or request_id.get()
        fields = getattr(record, "fields", None) or {}
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"{record.levelname:<7} {record.name}: {redact(record.getMessage())}"
        line += f" [{rid}]" if rid else ""
        line += f" {extra}" if extra else ""
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + redact(self.formatException(record.exc_info))
        return line


_HANDLER_NAME = "twin_api"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install the format on the root logger once (idempotent); uvicorn logs through it too."""
    root = logging.getLogger()
    for h in root.handlers:
        if h.get_name() == _HANDLER_NAME:
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(Redact())
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    # this middleware logs every request; uvicorn's own access line would repeat it with the query
    logging.getLogger("uvicorn.access").disabled = True
    # alembic announces its plugins at INFO whenever the readiness check loads it: not operational
    logging.getLogger("alembic").setLevel(max(logging.WARNING, root.level))


# ------------------------------------------------------------------ request middleware

log = logging.getLogger("twin_api.request")
INTERNAL_ERROR_BODY = json.dumps(
    {"error": {"code": "INTERNAL_ERROR", "message": "unexpected server error", "details": None}}
).encode()


class RequestLog:
    """Pure ASGI middleware: request id in, one log line out, ``X-Request-ID`` on the response.

    An incoming ``X-Request-ID`` (e.g. from the proxy) is kept if it looks like an id; otherwise a
    new one is made. The line holds the method, the path without its query string, the matched
    route template, the status and the latency. Nothing from headers, cookies or bodies.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = (
            dict(scope.get("headers") or []).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        )
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request_id.set(rid)  # visible to every log line of this request, including threadpool work
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER.encode(), rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        started_response = False

        async def send_tracking(message: Message) -> None:
            nonlocal started_response
            started_response = started_response or message["type"] == "http.response.start"
            await send_with_id(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            # an unexpected error: the traceback goes to the log (redacted, no request contents);
            # the client gets the same generic envelope as always, with the id to quote
            status = 500
            log.error(
                "unhandled %s on %s %s",
                type(exc).__name__,
                scope.get("method"),
                scope.get("path", ""),
                exc_info=exc,
                extra={"fields": {"event": "unhandled_error"}, "request_id": rid},
            )
            if not started_response:
                await send_with_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"no-store"),
                            (b"x-content-type-options", b"nosniff"),
                        ],
                    }
                )
                await send_with_id({"type": "http.response.body", "body": INTERNAL_ERROR_BODY})
        finally:
            path = scope.get("path", "")
            route = getattr(scope.get("route"), "path", None)
            # FastAPI matches included routers by their own paths: restore the API prefix
            if route and path.startswith(API_PREFIX) and not route.startswith(API_PREFIX):
                route = API_PREFIX + route
            fields = {
                "event": "request",
                "method": scope.get("method"),
                "path": path,
                "route": route,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            level = (
                logging.ERROR
                if status >= 500
                else logging.WARNING
                if status >= 400
                else logging.DEBUG
                if path in QUIET_PATHS
                else logging.INFO
            )
            log.log(
                level,
                "%s %s %s",
                fields["method"],
                path,
                status,
                extra={"fields": fields, "request_id": rid},
            )
