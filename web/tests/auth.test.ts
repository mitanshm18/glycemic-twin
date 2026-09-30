import { AUTH_ERRORS, authErrorMessage, googleStartHref, loginHref } from "@/lib/auth";

describe("sign-in destinations", () => {
  it("remember where the user was going, and why they are signing in", () => {
    expect(loginHref("/patients/3?at=2021-06-03T18:30:00", "expired")).toBe(
      "/login?next=%2Fpatients%2F3%3Fat%3D2021-06-03T18%3A30%3A00&expired=1",
    );
    expect(loginHref(null, "signed_out")).toBe("/login?signed_out=1");
    expect(loginHref("/patients")).toBe("/login");
  });

  it("never carry an off-site or looping destination", () => {
    expect(loginHref("//evil.example")).toBe("/login");
    expect(loginHref("/login?next=/x")).toBe("/login");
    expect(googleStartHref("https://evil.example")).toBe("/api/v1/auth/google/start");
  });

  it("start Google sign-in on the server (a navigation, never a client token flow)", () => {
    expect(googleStartHref("/model")).toBe("/api/v1/auth/google/start?next=%2Fmodel");
    expect(googleStartHref(null)).toBe("/api/v1/auth/google/start");
  });
});

describe("Google sign-in messages", () => {
  it("explain every failure the callback can report", () => {
    for (const code of [
      "google_not_configured",
      "google_not_provisioned",
      "google_identity_mismatch",
      "account_unavailable",
      "google_cancelled",
      "google_state_invalid",
      "google_exchange_failed",
      "google_token_invalid",
      "google_email_unverified",
      "google_wrong_domain",
    ]) {
      const m = authErrorMessage(code);
      expect(m?.title.length).toBeGreaterThan(10);
      expect(m?.title.toLowerCase()).not.toContain("something went wrong");
    }
  });

  it("say plainly that accounts are provisioned, not created", () => {
    expect(AUTH_ERRORS.google_not_provisioned?.body).toMatch(/administrator/);
    expect(authErrorMessage(null)).toBeNull();
    expect(authErrorMessage("unheard_of")?.tone).toBe("error");
  });
});
