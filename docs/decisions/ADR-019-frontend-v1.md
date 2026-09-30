# ADR-019: Clinician frontend v1 (Next.js, CSS design tokens, read-only insight adapter)

- Status: accepted (M6)
- Date: 2026-09-30
- Code: `web/` (Next.js App Router, TypeScript); `api/src/twin_api/routers/insights.py` and
  `api/src/twin_api/explain.py` (additive, read-only)
- Related: ADR-015 (model contract), ADR-017 (twin-state/1), ADR-018 (backend contract)

## Context

M6 adds the product surface: a clinician workspace over the M5 API. It must show real data only,
separate model estimates from measurements everywhere, never imply causation or clinical validity,
and add no treatment, medication or diagnosis features. M1–M5 logic, the 45-column contract, the
labels, the bundles and the twin-state contract are frozen.

## Decision

1. **Stack.** Next.js 15 App Router, React 19, TypeScript (strict, `noUncheckedIndexedAccess`),
   TanStack Query 5. The browser talks only to `/api/v1`, which `next.config.ts` rewrites to the
   FastAPI origin (`TWIN_API_ORIGIN`, default `http://127.0.0.1:8000`): same origin, so the
   HttpOnly session cookie (`SameSite=Lax` since Amendment 1) works and no CORS is opened.
2. **Styling: hand-written CSS on semantic tokens instead of Tailwind + shadcn/ui.**
   `web/src/styles/tokens.css` defines every colour (OKLCH), type step, space, radius, shadow and
   motion duration as a semantic variable (`--surface`, `--text-secondary`, `--risk-line`, `--model`,
   `--observed`, `--chart-band` …) with light values on `:root` and dark values on
   `[data-theme="dark"]`. Five layers (tokens, base, components, shell, pages/twin) use only tokens.
   Reasons: the palette must encode meaning (model vs observed, risk vs success) identically in both
   themes, which is simplest as one token table; the result has no build-time CSS dependency; and it
   was verifiable in the sandbox that built it, where the Tailwind toolchain could not be installed.
   Trade-off: no utility classes, so new screens add a few BEM-style rules.
3. **Charts are custom SVG, not Recharts.** Glucose, the risk dial, the learning curve and the
   calibration plot need clinical conventions (fixed 40–300 mg/dL frame, 70–180 band, 180 threshold,
   lines broken across CGM gaps, the twin's moment, a prediction window) and keyboard/screen-reader
   access; each is a small component over `lib/timeline.ts` scales.
4. **Motion is CSS + `requestAnimationFrame`, not Framer Motion.** Durations are tokens that drop to
   0 under `prefers-reduced-motion`; the prediction→reality reveal jumps to its end state. Motion only
   explains state changes (a number counting to its new value, changed fields highlighting, the
   reveal); nothing moves on its own.
5. **Theme.** Light / Dark / System, stored in `localStorage` (`twin-theme`). An inline head script
   applies it before first paint (no flash); `System` follows `prefers-color-scheme` live. Colours
   cross-fade only while the user is switching.
6. **Read-only insight adapter (the only backend change).** The frontend needed data the M5 API did
   not expose. `routers/insights.py` adds, without touching any existing route, table or contract:
   `GET /auth/csrf`, `GET /overview/patients`, `GET /patients/{id}/twin-states`,
   `GET /twin-states/{a}/diff/{b}` (twin_core's own `diff_states`),
   `GET /twin-states/{id}/explanation`, `GET /models`, `GET /models/active/evaluation`.
   - Explanations are computed on demand from the stored `model_inputs` by the served model:
     exact TreeSHAP (`pred_contribs`) for XGBoost, exact coefficient × transformed-input terms for
     logistic regression (missing-indicator terms added to their feature). Values are log-odds
     contributions before calibration and are labelled "model association, not causal". A state
     produced by a different model version is refused (409) rather than explained with the wrong
     model.
   - The evaluation is the M3 report, served only when its training-data hash equals the active
     model's; the limitations list travels with it.
7. **Honesty rules enforced in the UI.** Every estimate carries an "Model estimate" origin mark and
   every measurement a "Measured" mark; risk tone never appears without its text label; unscored
   states show a dash, never 0%; missing inputs read "missing", never 0; the what-if panel is
   labelled "Model-estimated scenario · Non-causal · Not medical advice", offers only the four
   macros and pre-meal activity (server bounds and support checks are authoritative), and shows no
   estimate outside training support; the model page leads with "not clinically validated".
8. **State in the URL.** The twin's moment (`?at=&meal=`), the record's day (`?day=`) and page
   routes are addressable, so a view can be reloaded or shared exactly.

## Consequences

- The UI cannot drift from the science: every number comes from the API, and the only computation in
  the browser is formatting and chart geometry.
- The adapter is additive and covered by `api/tests/test_insights.py`; M5's 256 tests are unchanged.
- Replacing the CSS layer with Tailwind later is mechanical (tokens map to a Tailwind theme), but not
  needed.

## Amendment 1 (M6 refinement, 2026-09-30): sessions, Google sign-in, motion

### A1. Session cookie is SameSite=Lax (was Strict)

Observed bug: after a reload the app sometimes returned to the sign-in page although the session
was valid. Cause, reproduced in Chromium: browsers withhold `SameSite=Strict` cookies from a
top-level page load that began on another site (a link in a terminal, an e-mail, a chat) and from
reloads of such a page. The Next.js middleware only sees the cookie on page loads, so it sent those
loads to `/login`; in-app `fetch` calls still carried the cookie, which is why everything else
kept working. Decision: `SameSite=Lax`. CSRF protection never depended on SameSite: every
state-changing request must carry the per-session `X-CSRF-Token` header, which a cross-site page
can neither read nor set (tested: `test_lax_cookie_does_not_weaken_csrf`). Lax is also what an
OAuth callback needs. Cookie otherwise unchanged: HttpOnly, `Secure` outside local http, path `/`,
8-hour lifetime, server-side session row, revocable.

### A2. Client-side session gate

`AuthGate` wraps every workspace page. It asks `GET /auth/me` and renders the page only after the
server answers: pending → quiet placeholder (no redirect, no sign-in form); 200 → page; 401 →
`/login?next=…&expired=1`; network failure → "can't confirm your session" with a retry, never a
sign-out. `/login` performs the same check first and forwards a signed-in user without showing the
form. A deliberate sign-out mutes the expiry notice, clears all cached data and lands on
`/login?signed_out=1`; signing in clears any previous user's cache. No timers anywhere: every
decision waits for the server.

### A3. Google sign-in (OpenID Connect, server-side, provisioned identities only)

- Flow: authorization code + PKCE (S256) + state + nonce, entirely server-mediated
  (`GET /auth/google/start`, `GET /auth/google/callback`, `GET /auth/providers`). The browser
  never receives a Google token; on success it gets the ordinary session cookie.
- State binding: 256-bit state stored only as SHA-256 in `oauth_flows` and in an HttpOnly Lax
  cookie scoped to `/api/v1/auth/google`; single use (deleted on first callback), 10-minute expiry.
- Token trust: the ID token is read from Google's token endpoint over certificate-verified TLS,
  which OIDC Core §3.1.3.7(6) accepts in place of signature checking; issuer, audience/azp, expiry,
  issued-at, nonce, verified email and (optionally) the Workspace domain are all validated.
  Standard library only; no new dependency.
- Provisioning: `user_identities` rows are created only by an administrator
  (`twin-api link-google USERNAME EMAIL`). The first sign-in binds Google's stable subject; after
  that a different Google account with the same address is refused. An unlinked account gets
  `google_not_provisioned`; no user is ever created from a sign-in. Inactive or locked users are
  refused.
- Configuration: `TWIN_GOOGLE_CLIENT_ID`, `TWIN_GOOGLE_CLIENT_SECRET` (SecretStr, server only),
  `TWIN_GOOGLE_REDIRECT_URI`, optional `TWIN_GOOGLE_HOSTED_DOMAIN`. Unset → the button is shown
  disabled with an explanation and `/auth/google/start` answers `google_not_configured`.
- Logging: outcomes are audited without codes, tokens or the address itself (domain + SHA-256);
  the callback's query string is redacted from access logs.
- Schema: migration `0002` adds `user_identities` and `oauth_flows`; nothing existing changes.

### A4. Motion

Motion explains a change (page, status, data) and never runs on its own: UI transitions use the
existing 120/200/360 ms tokens on one easing; data reveals are slower (dial 900 ms, chart line
900 ms, prediction→reality 2 s). Transform/opacity only. Theme changes cross-fade whole frames
with the View Transitions API where available. `prefers-reduced-motion` removes all movement while
keeping every state change (tested in unit and end-to-end suites).

### A5. Accessibility fixes found by automated axe scans

Muted text and chart axis labels were raised to WCAG AA on every surface and tint in both themes
(light `--text-muted` 4.1→4.8:1 worst case; dark 4.4→4.7:1). Phones gained a sort control (the
table header, and so its sort buttons, is hidden there). Repeated "Twin" links in the record were
given specific names.
