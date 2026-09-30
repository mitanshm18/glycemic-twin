import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

/*
 * Runs against the real stack: `make api` (FastAPI + PostgreSQL, the ingested data and an active
 * model) and `npm run dev`. Credentials come from the environment (never committed):
 *   E2E_USER=... E2E_PASSWORD=... npm run e2e
 * Optional: E2E_PATIENT=<id> picks the participant to open (default: the first in the list).
 */
const USER = process.env.E2E_USER;
const PASSWORD = process.env.E2E_PASSWORD;
test.skip(!USER || !PASSWORD, "set E2E_USER and E2E_PASSWORD to run the end-to-end suite");

/** Records, from the first byte of every page, whether the sign-in form was ever rendered. */
async function watchForSignInForm(ctx: BrowserContext) {
  await ctx.addInitScript(() => {
    (window as unknown as { __signInSeen: boolean }).__signInSeen = false;
    new MutationObserver(() => {
      if (document.querySelector("form.login__form")) (window as unknown as { __signInSeen: boolean }).__signInSeen = true;
    }).observe(document, { childList: true, subtree: true });
  });
}
const signInSeen = (page: Page) => page.evaluate(() => (window as unknown as { __signInSeen: boolean }).__signInSeen);

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(USER!);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/patients/);
}

/** On narrow screens the sidebar (theme, account) lives in the navigation sheet. */
async function openNavIfCollapsed(page: Page) {
  const menu = page.getByRole("button", { name: "Open navigation" });
  if (await menu.isVisible()) {
    await menu.click();
    await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();
  }
}

async function openFirstTwin(page: Page) {
  const pid = process.env.E2E_PATIENT;
  if (pid) await page.goto(`/patients/${pid}`);
  else {
    await page.goto("/patients");
    await page.locator("table.plist tbody a.plist__name").first().click();
  }
  await expect(page.locator(".hero")).toBeVisible({ timeout: 30_000 });
}

/** Let entrance animations finish so contrast is measured on settled colours (not mid-fade). */
async function settle(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
}

async function expectAccessible(page: Page) {
  await settle(page);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

// ------------------------------------------------------------------------------------ sign-in

test("sign-in: inline validation, password toggle, specific error for bad credentials", async ({ page }) => {
  await page.goto("/login");
  await expectAccessible(page);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("Username")).toHaveAttribute("aria-invalid", "true");
  await page.getByLabel("Username").fill(USER!);
  await page.getByLabel("Password", { exact: true }).fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  // scoped to the form: Next's route announcer is also an (empty) alert
  await expect(page.getByRole("region", { name: "Sign in" }).getByRole("alert")).toContainText(/not recognised|locked/i);
});

test("sign-in shows Google honestly: a server redirect when configured, a clear note when not", async ({ page }) => {
  await page.goto("/login");
  const link = page.getByRole("link", { name: /continue with google/i });
  const disabled = page.getByRole("button", { name: /continue with google/i });
  await expect(link.or(disabled)).toBeVisible();
  if (await link.isVisible()) {
    await expect(link).toHaveAttribute("href", /^\/api\/v1\/auth\/google\/start/);
  } else {
    await expect(disabled).toBeDisabled();
    await page.goto("/api/v1/auth/google/start");
    await expect(page).toHaveURL(/auth_error=google_not_configured/);
    await expect(page.getByText(/isn’t set up on this server/)).toBeVisible();
  }
});

test("sign-in signal: explorable by pointer, silent to assistive tech, no overflow", async ({ page, isMobile }) => {
  await page.goto("/login");
  const signal = page.locator(".signal");
  await expect(signal).toHaveAttribute("aria-hidden", "true");
  // read once, as one sentence, although it reveals word by word
  await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("How one person’s glucose responds to meals.");
  await expectNoHorizontalScroll(page);
  if (isMobile) {
    await expect(page.locator(".signal__anchor")).toHaveCount(0); // a quiet strip on phones
    return;
  }
  const meal = page.locator(".signal__anchor").first();
  await expect(meal).toBeVisible(); // interactive once the opening sequence has drawn the signal
  await meal.click();
  await expect(page.locator(".signal__chip")).toContainText("Meal logged");
  await page.keyboard.press("Escape");
  await expect(page.locator(".signal__chip")).toHaveCount(0);
  // the form is never blocked by the opening sequence
  await page.getByLabel("Username").fill("someone");
  await expect(page.getByLabel("Username")).toHaveValue("someone");
});

test("sign-in under reduced motion: everything is simply there", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", baseURL });
  const page = await ctx.newPage();
  await page.goto("/login");
  const names = await page.evaluate(() =>
    [".login__word", ".login__lede", ".signal__trace", ".login__card"].map((sel) => getComputedStyle(document.querySelector(sel)!).animationName),
  );
  expect(names).toEqual(["none", "none", "none", "none"]);
  await expect(page.locator(".login__caret")).toBeHidden();
  await ctx.close();
});

// ------------------------------------------------------------------------------------ session

test("unauthenticated deep links go to sign-in and come back afterwards", async ({ page }) => {
  await page.goto("/model");
  await expect(page).toHaveURL(/\/login\?next=%2Fmodel/);
  await page.getByLabel("Username").fill(USER!);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/model$/);
});

test("a signed-in user can refresh any page without seeing sign-in (regression)", async ({ context, page }) => {
  await watchForSignInForm(context);
  await signIn(page);
  await openFirstTwin(page);
  const twinUrl = page.url();
  for (const url of [twinUrl, "/patients", "/model", twinUrl.replace(/\?.*$/, "") + "/record"]) {
    await page.goto(url);
    await page.reload();
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.locator("h1")).toBeVisible();
    expect(await signInSeen(page)).toBe(false);
  }
  const cookie = (await context.cookies()).find((c) => c.name === "twin_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
});

test("visiting /login while signed in goes straight on without showing the form", async ({ context, page }) => {
  await watchForSignInForm(context);
  await signIn(page);
  await page.goto("/login?next=%2Fmodel");
  await expect(page).toHaveURL(/\/model$/);
  expect(await signInSeen(page)).toBe(false);
});

test("sign out is immediate and the back button cannot reopen the workspace", async ({ page }) => {
  await signIn(page);
  await page.goto("/model"); // history: … /patients, /model
  await expect(page.locator("h1")).toHaveText("Model");
  await openNavIfCollapsed(page);
  await page.getByRole("button", { name: "Sign out" }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/login\?signed_out=1/);
  await expect(page.getByText("You’re signed out")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/login/);
  expect(await page.evaluate(() => fetch("/api/v1/auth/me").then((r) => r.status))).toBe(401);
});

// ------------------------------------------------------------------------------------ product

test("patient list: search, filters, sorting and keyboard navigation", async ({ page }) => {
  await signIn(page);
  const rows = page.locator("table.plist tbody tr");
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  await page.getByRole("radio", { name: /^All/ }).click();
  expect(await rows.count()).toBeGreaterThanOrEqual(n);
  const sortHeader = page.getByRole("button", { name: "Scorable meals" });
  if (await sortHeader.isVisible()) {
    await sortHeader.click();
    await expect(page.locator('th[aria-sort="ascending"]')).toContainText("Scorable meals");
    await page.keyboard.press("/");
    await expect(page.getByPlaceholder("Search participants")).toBeFocused();
  } else {
    // phones: the table header is hidden, so sorting has its own control
    await page.getByLabel("Sort by").selectOption("meals:1");
    await expect(page.getByLabel("Sort by")).toHaveValue("meals:1");
    await page.getByPlaceholder("Search participants").focus();
  }
  await page.keyboard.type("zzz-no-such-participant");
  await expect(page.getByText("No patients match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await page.locator("a.plist__name").first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("a.plist__name").nth(1)).toBeFocused();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("twin: estimate vs measurement, explanation, reveal, what-if, context tabs, provenance", async ({ page }) => {
  await signIn(page);
  await openFirstTwin(page);
  const hero = page.locator(".hero");
  await expect(hero.getByText("Model estimate")).toBeVisible();
  await expect(hero.getByText("Measured")).toBeVisible();
  await expect(page.getByText(/Model association · not causal/)).toBeVisible();

  const reveal = page.getByRole("button", { name: /Reveal what happened/ });
  if (await reveal.isVisible()) {
    await reveal.click();
    await expect(page.locator(".reveal__result")).toContainText(/Highest reading in 2 h/, { timeout: 10_000 });
    await expect(page.locator(".reveal__result")).toContainText(/Outcome \(labels\.v1\)/);
  }

  const whatIf = page.locator("#what-if");
  await whatIf.scrollIntoViewIfNeeded();
  if (await whatIf.getByRole("slider").count()) {
    for (const label of ["Model-estimated scenario", "Non-causal", "Not medical advice"]) {
      await expect(whatIf.getByText(label)).toBeVisible();
    }
    await whatIf.getByRole("slider", { name: "Carbohydrate" }).focus();
    for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
    await expect(whatIf.locator(".wi-result, .state")).toBeVisible({ timeout: 15_000 });
  }
  await expect(page.getByLabel(/insulin|medication|dose/i)).toHaveCount(0);

  // patient context is kept across the patient's views
  const moment = new URL(page.url()).search;
  await page.getByLabel("Patient views").getByRole("link", { name: "Clinical record" }).click();
  await expect(page.getByRole("heading", { name: "Chronology" })).toBeVisible();
  await page.getByLabel("Patient views").getByRole("link", { name: "Twin" }).click();
  await expect(page.locator(".hero")).toBeVisible({ timeout: 30_000 });
  if (moment) expect(new URL(page.url()).search).toBe(moment);

  const open = page.getByRole("button", { name: /View provenance/ });
  await open.click();
  await expect(page.getByRole("dialog", { name: "Provenance" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(open).toBeFocused();

  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("clinical record and model page are honest and accessible", async ({ page }) => {
  await signIn(page);
  await openFirstTwin(page);
  await page.getByLabel("Patient views").getByRole("link", { name: "Clinical record" }).click();
  await expect(page.getByRole("heading", { name: "Baseline" })).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await page.goto("/model");
  await expect(page.getByText(/not clinically validated/i)).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("theme choice persists across reloads without flashing the other theme", async ({ page }) => {
  await signIn(page);
  await openNavIfCollapsed(page);
  await page.getByRole("radio", { name: "Dark theme" }).filter({ visible: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await openNavIfCollapsed(page);
  await page.getByRole("radio", { name: "Match system theme" }).filter({ visible: true }).click();
});

test("reduced motion: the same states, without movement", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", baseURL });
  const page = await ctx.newPage();
  await signIn(page);
  await openFirstTwin(page);
  const animation = await page.evaluate(() => getComputedStyle(document.querySelector(".page-enter")!).animationName);
  expect(animation).toBe("none");
  const reveal = page.getByRole("button", { name: /Reveal what happened/ });
  if (await reveal.isVisible()) {
    await reveal.click();
    await expect(page.locator(".reveal__result")).toBeVisible({ timeout: 1_000 });
  }
  await ctx.close();
});
