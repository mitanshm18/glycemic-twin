/**
 * The only place the browser talks to the backend. Same-origin requests to /api/v1 (proxied to
 * FastAPI by next.config.ts), so the HttpOnly session cookie is sent automatically.
 *
 * CSRF: every POST needs the session's CSRF token in X-CSRF-Token. It is kept in memory only
 * (never in storage). After a page reload the token is gone, so the client asks the server for a
 * fresh one (GET /auth/csrf, which rotates it) before the first POST.
 *
 * Session expiry: any 401 fires the "twin:session-expired" event; the auth provider sends the user
 * to /login and says why.
 */

import type { ApiErrorBody } from "./types";

export const API = "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Network failure (backend down, proxy unreachable): distinct from an API error. */
export class NetworkError extends Error {
  constructor() {
    super("The backend could not be reached.");
    this.name = "NetworkError";
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export const SESSION_EXPIRED_EVENT = "twin:session-expired";

/**
 * After a deliberate sign-out the next 401s are expected, not an expiry: suppress the event until
 * the next successful sign-in so the user is not told their session "ended".
 */
let expiryMuted = false;

export function muteSessionExpiry(muted: boolean): void {
  expiryMuted = muted;
}

export function sessionExpiryMuted(): boolean {
  return expiryMuted;
}

type Query = Record<string, string | number | boolean | null | undefined>;

function url(path: string, query?: Query): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return `${API}${path}${s ? `?${s}` : ""}`;
}

async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body: unknown = text ? JSON.parse(text) : undefined;
  if (res.ok) return body as T;
  const err = (body as ApiErrorBody | undefined)?.error;
  if (res.status === 401 && typeof window !== "undefined" && !expiryMuted) {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
  }
  throw new ApiError(
    res.status,
    err?.code ?? `HTTP_${res.status}`,
    err?.message ?? res.statusText ?? "request failed",
    err?.details,
  );
}

async function send(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, { credentials: "same-origin", ...init });
  } catch {
    throw new NetworkError();
  }
}

export async function get<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  const res = await send(url(path, query), { headers: { Accept: "application/json" }, signal });
  return parse<T>(res);
}

async function ensureCsrf(): Promise<string> {
  if (!csrfToken) {
    const out = await get<{ csrf_token: string }>("/auth/csrf");
    csrfToken = out.csrf_token;
  }
  return csrfToken;
}

export async function post<T>(path: string, body?: unknown, opts?: { csrf?: boolean }): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (opts?.csrf !== false) headers["X-CSRF-Token"] = await ensureCsrf();
  let res = await send(url(path), {
    method: "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 403 && opts?.csrf !== false) {
    // The token may have been rotated by another tab: fetch a fresh one and retry once.
    const clone = res.clone();
    const code = ((await clone.json().catch(() => null)) as ApiErrorBody | null)?.error?.code;
    if (code === "CSRF_FAILED") {
      csrfToken = null;
      headers["X-CSRF-Token"] = await ensureCsrf();
      res = await send(url(path), {
        method: "POST",
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    }
  }
  return parse<T>(res);
}

export function isApiError(e: unknown, code?: string): e is ApiError {
  return e instanceof ApiError && (code === undefined || e.code === code);
}
