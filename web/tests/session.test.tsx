import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AuthGate } from "@/components/shell/AuthGate";
import { LoginScreen } from "@/features/auth/LoginScreen";
import { makeQueryClient } from "@/lib/api/queries";

/*
 * Session restoration and sign-in behaviour. The server is simulated with a fetch stand-in; the
 * router with vi.mock. Regression tests for the "refresh sends me to sign-in" bug: the gate must
 * wait for the server's answer, never redirect while it is pending, and never show the sign-in form
 * to a signed-in user.
 */

const nav = vi.hoisted(() => ({
  router: { replace: vi.fn(), push: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
  search: "",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => nav.router,
  usePathname: () => "/patients/3",
  useSearchParams: () => new URLSearchParams(nav.search),
}));

type Reply = { status: number; body?: unknown } | "pending" | "offline";

function server(routes: Record<string, Reply>) {
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
    const path = String(input).replace(/^.*\/api\/v1/, "").split("?")[0] ?? "";
    const r = routes[path] ?? { status: 404, body: { error: { code: "NOT_FOUND", message: "x" } } };
    if (r === "pending") return new Promise<Response>(() => {});
    if (r === "offline") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(new Response(r.body === undefined ? null : JSON.stringify(r.body), { status: r.status }));
  }) as typeof fetch;
}

const ME = { status: 200, body: { id: 1, username: "qa.clinician", role: "clinician", is_active: true } };
const NO_SESSION = { status: 401, body: { error: { code: "UNAUTHENTICATED", message: "session expired or signed out" } } };

function withClient(ui: ReactNode) {
  return render(<QueryClientProvider client={makeQueryClient()}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  nav.router.replace.mockReset();
  nav.search = "";
  window.history.replaceState(null, "", "/patients/3?at=2021-06-03T18:30:00");
});

describe("session gate (page reload / deep link)", () => {
  it("restores a valid session: renders the page, no redirect", async () => {
    server({ "/auth/me": ME });
    withClient(<AuthGate>page content</AuthGate>);
    expect(await screen.findByText("page content")).toBeInTheDocument();
    expect(nav.router.replace).not.toHaveBeenCalled();
  });

  it("does not redirect or show sign-in while the server has not answered", async () => {
    server({ "/auth/me": "pending" });
    withClient(<AuthGate>page content</AuthGate>);
    expect(screen.getByRole("status")).toHaveTextContent(/restoring your session/i);
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(nav.router.replace).not.toHaveBeenCalled();
    expect(screen.queryByText("page content")).toBeNull();
  });

  it("sends an expired session to sign-in and remembers the page", async () => {
    server({ "/auth/me": NO_SESSION });
    withClient(<AuthGate>page content</AuthGate>);
    await waitFor(() => expect(nav.router.replace).toHaveBeenCalled());
    expect(nav.router.replace).toHaveBeenCalledWith(
      "/login?next=%2Fpatients%2F3%3Fat%3D2021-06-03T18%3A30%3A00&expired=1",
    );
    expect(screen.queryByText("page content")).toBeNull();
  });

  it("keeps the user signed in when the server is unreachable, and offers a retry", async () => {
    server({ "/auth/me": "offline" });
    withClient(<AuthGate>page content</AuthGate>);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not been signed out/i);
    expect(nav.router.replace).not.toHaveBeenCalled();
    server({ "/auth/me": ME });
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("page content")).toBeInTheDocument();
  });
});

describe("sign-in screen", () => {
  it("never shows the form to a user who is already signed in", async () => {
    nav.search = "next=%2Fmodel";
    server({ "/auth/me": ME, "/auth/providers": { status: 200, body: { password: true, google: false } } });
    withClient(<LoginScreen />);
    await waitFor(() => expect(nav.router.replace).toHaveBeenCalledWith("/model"));
    expect(screen.queryByLabelText("Username")).toBeNull();
  });

  it("validates inline and ties each message to its field", async () => {
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: false } } });
    withClient(<LoginScreen />);
    const submit = await screen.findByRole("button", { name: "Sign in" });
    fireEvent.click(submit);
    const user = screen.getByLabelText("Username");
    expect(user).toHaveAttribute("aria-invalid", "true");
    expect(user).toHaveAccessibleDescription("Enter your username.");
    expect(screen.getByLabelText("Password", { selector: "input" })).toHaveAccessibleDescription("Enter your password.");
  });

  it("lets the user reveal the password with a labelled toggle", async () => {
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: false } } });
    withClient(<LoginScreen />);
    const pw = await screen.findByLabelText("Password", { selector: "input" });
    expect(pw).toHaveAttribute("type", "password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(pw).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");
  });

  it("signs in and returns to the requested page", async () => {
    nav.search = "next=%2Fpatients%2F3";
    server({
      "/auth/me": NO_SESSION,
      "/auth/providers": { status: 200, body: { password: true, google: false } },
      "/auth/login": { status: 200, body: { user: ME.body, csrf_token: "t", expires_at: "2026-10-01T00:00:00Z" } },
    });
    withClient(<LoginScreen />);
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "qa.clinician" } });
    fireEvent.change(screen.getByLabelText("Password", { selector: "input" }), { target: { value: "a-good-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(nav.router.replace).toHaveBeenCalledWith("/patients/3"));
  });

  it("explains wrong credentials without saying which part was wrong", async () => {
    server({
      "/auth/me": NO_SESSION,
      "/auth/providers": { status: 200, body: { password: true, google: false } },
      "/auth/login": NO_SESSION,
    });
    withClient(<LoginScreen />);
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "qa.clinician" } });
    fireEvent.change(screen.getByLabelText("Password", { selector: "input" }), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Username or password not recognised");
    expect(screen.getByLabelText("Password", { selector: "input" })).toHaveValue("");
  });

  it("shows Google as unavailable, not broken, when the server has no Google configuration", async () => {
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: false } } });
    withClient(<LoginScreen />);
    const g = await screen.findByRole("button", { name: /continue with google/i });
    await waitFor(() => expect(g).toHaveAccessibleDescription(/isn’t configured on this server/));
    expect(g).toBeDisabled();
  });

  it("offers Google as a server-side redirect when configured, keeping the destination", async () => {
    nav.search = "next=%2Fmodel";
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: true } } });
    withClient(<LoginScreen />);
    const g = await screen.findByRole("link", { name: /continue with google/i });
    expect(g).toHaveAttribute("href", "/api/v1/auth/google/start?next=%2Fmodel");
    expect(g).toHaveAccessibleDescription(/linked by an administrator/);
  });

  it("reports an unprovisioned Google account clearly", async () => {
    nav.search = "auth_error=google_not_provisioned";
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: true } } });
    withClient(<LoginScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This Google account isn’t linked to a clinician account");
  });

  it("says why the user is here after expiry or sign-out", async () => {
    server({ "/auth/me": NO_SESSION, "/auth/providers": { status: 200, body: { password: true, google: false } } });
    nav.search = "expired=1";
    const { unmount } = withClient(<LoginScreen />);
    expect(await screen.findByText("Your session ended")).toBeInTheDocument();
    unmount();
    nav.search = "signed_out=1";
    withClient(<LoginScreen />);
    expect(await screen.findByText("You’re signed out")).toBeInTheDocument();
  });
});
