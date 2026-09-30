/**
 * Client-side auth helpers. The session itself is the HttpOnly cookie the server checks on every
 * request (ADR-018/019); nothing here stores or reads a credential.
 */

import { safeNext } from "./nav";

export type SignInReason = "expired" | "signed_out";

/** /login URL that brings the user back to `next` (validated again on arrival). */
export function loginHref(next: string | null | undefined, reason?: SignInReason): string {
  const q = new URLSearchParams();
  const dest = safeNext(next);
  if (dest !== "/patients") q.set("next", dest);
  if (reason === "expired") q.set("expired", "1");
  if (reason === "signed_out") q.set("signed_out", "1");
  const s = q.toString();
  return `/login${s ? `?${s}` : ""}`;
}

/** Server-mediated Google sign-in: a plain top-level navigation to the API (never a popup). */
export function googleStartHref(next: string | null | undefined): string {
  const dest = safeNext(next);
  return `/api/v1/auth/google/start${dest !== "/patients" ? `?next=${encodeURIComponent(dest)}` : ""}`;
}

export interface AuthMessage {
  tone: "error" | "notice";
  title: string;
  body?: string;
}

/** Wording for the `auth_error` codes the Google callback redirects with. */
export const AUTH_ERRORS: Record<string, AuthMessage> = {
  google_not_configured: {
    tone: "notice",
    title: "Google sign-in isn’t set up on this server",
    body: "Sign in with your username and password, or ask an administrator to configure it.",
  },
  google_not_provisioned: {
    tone: "error",
    title: "This Google account isn’t linked to a clinician account",
    body: "Accounts are provisioned by an administrator. Ask them to link this Google account, or sign in with your username and password.",
  },
  google_identity_mismatch: {
    tone: "error",
    title: "This email is linked to a different Google account",
    body: "Ask an administrator to check the link for this address.",
  },
  account_unavailable: {
    tone: "error",
    title: "This account can’t sign in right now",
    body: "It is inactive or temporarily locked after failed attempts. Try again later or contact an administrator.",
  },
  google_cancelled: { tone: "notice", title: "Google sign-in was cancelled" },
  google_denied: { tone: "error", title: "Google didn’t complete the sign-in", body: "Try again." },
  google_state_invalid: {
    tone: "error",
    title: "That sign-in attempt expired or was already used",
    body: "Start again from this page.",
  },
  google_exchange_failed: {
    tone: "error",
    title: "Couldn’t finish signing in with Google",
    body: "The server could not reach Google. Try again in a moment.",
  },
  google_token_invalid: {
    tone: "error",
    title: "Google’s response couldn’t be verified",
    body: "Nothing was signed in. Start again from this page.",
  },
  google_email_unverified: {
    tone: "error",
    title: "This Google account’s email isn’t verified",
    body: "Verify the address with Google, or sign in with your username and password.",
  },
  google_wrong_domain: {
    tone: "error",
    title: "This Google account is outside the organisation",
    body: "Use your organisation’s Google account, or your username and password.",
  },
};

export function authErrorMessage(code: string | null | undefined): AuthMessage | null {
  if (!code) return null;
  return AUTH_ERRORS[code] ?? { tone: "error", title: "Sign-in with Google didn’t complete", body: "Try again." };
}
