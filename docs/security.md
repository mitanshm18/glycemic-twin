# Security and production configuration

Glycemic Twin is a research prototype on open, de-identified research data (CGMacros v1.0.0). It is
not a medical device. This page states what the system protects, how, what production requires,
and what it deliberately does not do.

## Architecture assumption: one origin

In production, one reverse proxy (Caddy) serves everything on one HTTPS origin:
`/api/v1/*` → FastAPI, everything else → the Next.js server. The browser only ever talks to that
origin, so:

- the session cookie is first-party (`SameSite=Lax`, `HttpOnly`, `Secure`);
- there is **no CORS** configuration, and none is needed;
- the Next.js `/api/v1` rewrite (`TWIN_API_ORIGIN`, fixed at build time) is only used when the web
  server runs without the proxy (local development).

## Production requirements (enforced at startup)

With `TWIN_ENVIRONMENT=production` the API refuses to start (and names the problem, without
printing any value) unless:

| Rule | Why |
|---|---|
| `TWIN_COOKIE_SECURE=true` | session cookies travel over HTTPS only |
| `TWIN_TRUSTED_HOSTS` lists the public host name(s), no `*` | requests with any other `Host` header get 400 (host-header attacks, stray DNS) |
| Google sign-in: all of client id, secret and redirect URI, or none | a half-configured OIDC client is refused, not silently disabled |
| `TWIN_GOOGLE_REDIRECT_URI` uses `https` | the authorization code never travels in clear text |

Also in production: `/api/v1/docs` and `/api/v1/openapi.json` are not served, and
`twin-api serve --reload` is refused. `TWIN_ENVIRONMENT` accepts only `development`, `test` or
`production`.

Include internal host names used by health checks in `TWIN_TRUSTED_HOSTS` (for example
`twin.example.org,api,localhost`).

## What each layer does

**Passwords.** Argon2id (RFC 9106 second recommended parameters: t=3, p=4, 64 MiB), minimum 12
characters. At most two hashes run at once: a burst of sign-ins queues instead of exhausting memory
(this fixed a 500 under concurrent failed logins). Unknown usernames spend the same time as a real
check (no user enumeration).

**Lockout.** After `TWIN_MAX_FAILED_LOGINS` (5) wrong passwords the account is locked for
`TWIN_LOCKOUT_MINUTES` (15). Every sign-in failure returns the same message.

**Sessions.** A 256-bit random token in an `HttpOnly`, `SameSite=Lax`, `Secure` (production) cookie;
the database stores only its SHA-256. Sessions are server-side: logout and expiry
(`TWIN_SESSION_TTL_MINUTES`, 8 h) take effect immediately. A new token is issued on every sign-in
(no session fixation).

**CSRF.** Every state-changing request must send the per-session token in `X-CSRF-Token` (stored
hashed, compared in constant time). `SameSite=Lax` is defence in depth, not the defence.

**Google sign-in (optional).** Authorization code + PKCE + nonce + state (single-use, 10 min,
HttpOnly flow cookie). ID tokens are validated server-side and never reach the browser. A Google
account signs in only if an admin linked it to an existing user; no account is ever created from
Google.

**Roles.** `clinician` and `admin`; admin endpoints check the role and denials are audited.

**Audit log.** Sign-ins, denials, CSRF failures, role denials, model activation, user creation. It
never stores passwords or tokens; an unknown sign-in name (often a password typed in the wrong
field) is stored only as a truncated SHA-256; failed Google sign-ins store the email's domain and a
hash.

**Errors.** One envelope, `{"error": {"code", "message", "details"}}`. Validation errors list the
field and the rule, never the submitted value. Unexpected errors return a generic 500; the
traceback goes to the server log with the method and path only (no body, cookies or headers).
Database errors never carry bound parameters. In production, model-loading problems are reported
as "the active model cannot be served" (to clinicians and on `/ready`) without file paths or
hashes; the detail is logged server-side.

**Response headers (API).** `Cache-Control: no-store` (patient data is never cached),
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, and in
production `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. The web app sets
its own `nosniff`, `same-origin` referrer, `DENY` framing and a restrictive permissions policy.

**Secrets.** Only in the untracked `.env` (or the server's environment). The database URL and the
Google client secret are secret types: they never appear in reprs, logs or configuration errors.
`.env`, `.env.*` (except `.env.example`), raw and processed data, model bundles and local test
credentials (`web/.env.e2e.local`) are gitignored.

## Known limitations (accepted for a research prototype)

- **No per-IP rate limiting.** Lockout is per account. A proxy-level limit on
  `POST /api/v1/auth/login` is recommended in deployment.
- **No content security policy on the web pages yet.** Next.js needs inline scripts (the
  no-flash theme script); a nonce-based CSP is possible later. HSTS is set at the proxy.
- **No multi-factor authentication** (optional Google sign-in can carry the organisation's MFA).
- **Audit IP addresses** are the proxy's unless the API trusts forwarded headers from it (set when
  the containers are defined).
- **Data:** CGMacros is de-identified research data (CC BY-NC-SA 4.0); the system is not designed
  or assessed for identifiable patient data.
