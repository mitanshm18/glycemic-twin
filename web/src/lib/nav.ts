/**
 * Post-login destination guard: only paths inside this app are accepted (no open redirects).
 * Anything that could resolve to another origin ("//evil", "/\evil", "https://…", control
 * characters) falls back to the patient list.
 */
const ORIGIN = "http://app.invalid";

export function safeNext(raw: string | null | undefined): string {
  const fallback = "/patients";
  if (!raw || !raw.startsWith("/") || /[\\\u0000-\u001f]/.test(raw)) return fallback;
  let url: URL;
  try {
    url = new URL(raw, ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== ORIGIN || url.pathname.startsWith("/login")) return fallback;
  return url.pathname + url.search + url.hash;
}
