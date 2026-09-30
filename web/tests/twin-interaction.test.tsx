import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { CurrentState } from "@/components/twin/CurrentState";
import { GlucoseContext } from "@/components/twin/GlucoseContext";
import { GlucoseTimeline, type TimelineMeal } from "@/components/twin/GlucoseTimeline";
import { RiskDial } from "@/components/twin/RiskDial";
import { TwinRail } from "@/components/twin/TwinRail";
import type { Meal, MealOutcome, TwinState } from "@/lib/api/types";
import { evidenceFor, evidenceRange } from "@/lib/evidence";
import { MINUTE, parseNaive } from "@/lib/time";
import { deltaFromPrevious, seenBy, type Pt } from "@/lib/timeline";
import fixture from "./fixtures/twin-state.synthetic.json";

// SYNTHETIC fixture: produced by the real twin_core engine on the synthetic test record.
const STATE = fixture as unknown as TwinState;
const AS_OF = parseNaive(STATE.as_of);

function withQuery(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

/** A CGM endpoint that (wrongly) also returns readings after the requested end: the UI must drop them. */
function cgmServer() {
  const calls: string[] = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const iso = (t: number) => new Date(t).toISOString().slice(0, 19);
    const body = url.includes("/cgm")
      ? [-80, -40, -20, -10, -5, 0, 5, 30].map((m, i) => ({ ts: iso(AS_OF + m * MINUTE), dexcom_mgdl: 100 + i * 4, dexcom_is_native: true, libre_mgdl: null }))
      : { error: { code: "NOT_FOUND", message: "x" } };
    return Promise.resolve(new Response(JSON.stringify(body), { status: url.includes("/cgm") ? 200 : 404 }));
  }) as typeof fetch;
  return calls;
}

describe("evidence for a model input", () => {
  it("restates what each input is computed from", () => {
    expect(evidenceFor("slope_15")).toEqual({ kind: "lookback", feature: "slope_15", minutes: 15 });
    expect(evidenceFor("mean_180")).toMatchObject({ kind: "lookback", minutes: 180 });
    expect(evidenceFor("carbs_prev_3h")).toMatchObject({ kind: "prior-meals", minutes: 180 });
    expect(evidenceFor("carbs_g")).toMatchObject({ kind: "meal" });
    expect(evidenceFor("p_personal")).toMatchObject({ kind: "personal" });
    expect(evidenceFor("hba1c_pct")).toBeNull(); // nothing on the page to point at
    const r = evidenceRange({ kind: "lookback", feature: "sd_60", minutes: 60 }, AS_OF);
    expect(r).toEqual({ from: AS_OF - 60 * MINUTE, to: AS_OF });
  });
});

describe("timeline helpers", () => {
  const pts: Pt[] = [
    { t: 0, v: 100 },
    { t: 5 * MINUTE, v: 106 },
    { t: 40 * MINUTE, v: 120 },
  ];
  it("compares with the previous reading only when it is recent", () => {
    expect(deltaFromPrevious(pts, 1)).toEqual({ dv: 6, dtMin: 5 });
    expect(deltaFromPrevious(pts, 2)).toBeNull(); // 35 min gap: not a trend
    expect(deltaFromPrevious(pts, 0)).toBeNull();
  });
  it("keeps only what the twin could see", () => {
    expect(seenBy(pts, 5 * MINUTE).map((p) => p.v)).toEqual([100, 106]);
  });
});

describe("surrounding CGM context", () => {
  it("asks for the 90 minutes up to the moment and never shows a later reading", async () => {
    const calls = cgmServer();
    withQuery(<GlucoseContext state={STATE} id="ctx" onClose={() => {}} onShowTimeline={() => {}} />);
    await screen.findByText(/Readings/);
    expect(calls[0]).toContain("end=2021-06-06T19%3A00%3A00");
    // 8 readings served: the 6 at or before the moment are counted, the 2 after it are dropped
    expect(screen.getByText("6", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText(/at 19:00/)).toBeInTheDocument();
    expect(screen.queryByText(/19:30/)).toBeNull();
  });

  it("opens from the trend control, closes with Esc and returns focus to it", async () => {
    cgmServer();
    withQuery(<CurrentState state={STATE} />);
    const trigger = screen.getByRole("button", { name: /Show the readings from the 90 minutes/ });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("region", { name: /90 minutes before the twin's moment/ })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("region", { name: /90 minutes before/ })).toBeNull();
    expect(trigger).toHaveFocus();
  });
});

describe("explorable risk dial", () => {
  it("is a control that explains itself and leads on", () => {
    const go = vi.fn();
    render(
      <RiskDial probability={0.12} threshold={0.37} tone="success" label="12% estimated." details={<span>25 pp below the alert threshold</span>} onActivate={go} />,
    );
    const dial = screen.getByRole("button", { name: /12% estimated\. Show what drives this estimate/ });
    expect(dial).toHaveAccessibleDescription(/25 pp below/);
    fireEvent.click(dial);
    expect(go).toHaveBeenCalled();
  });
});

describe("glucose timeline", () => {
  const t0 = AS_OF;
  const points: Pt[] = Array.from({ length: 13 }, (_, i) => ({ t: t0 - 30 * MINUTE + i * 5 * MINUTE, v: 110 + i * 5 }));
  const meals: TimelineMeal[] = [
    { id: "b", t: t0, type: "dinner", current: true, scored: true, carbs_g: 62, fiber_g: 4, protein_g: 30, fat_g: 18, calories_kcal: 540 },
    { id: "a", t: t0 - 20 * MINUTE, type: "snack", scored: false, carbs_g: 12, fiber_g: null, protein_g: 1, fat_g: 0, calories_kcal: 55 },
  ];
  const renderTl = (onMealSelect = vi.fn()) =>
    render(<GlucoseTimeline points={points} start={t0 - 60 * MINUTE} end={t0 + 60 * MINUTE} meals={meals} asOf={t0} revealed={0} summary="chart" onMealSelect={onMealSelect} />);

  it("offers meals as buttons in time order, with their logged macros on focus", () => {
    renderTl();
    const buttons = screen.getAllByRole("button", { name: /at \d\d:\d\d/ });
    expect(buttons.map((b) => b.getAttribute("aria-label")?.split(" at")[0])).toEqual(["Snack", "Dinner"]);
    act(() => (buttons[1] as HTMLElement).focus());
    expect(screen.getByText("62 g")).toBeInTheDocument();
    expect(screen.getByText("540 kcal")).toBeInTheDocument();
    fireEvent.keyDown(buttons[1] as HTMLElement, { key: "ArrowLeft" });
    expect(buttons[0]).toHaveFocus();
    expect(screen.getByText("—")).toBeInTheDocument(); // fiber not logged: shown as missing, not zero
  });

  it("moves the twin with Enter on a meal", () => {
    const go = vi.fn();
    renderTl(go);
    const snack = screen.getByRole("button", { name: /Snack at/ });
    fireEvent.click(snack, { detail: 0 });
    expect(go).toHaveBeenCalledWith("a");
  });

  it("never reads out a reading after the twin's moment before it is revealed", () => {
    renderTl();
    const chart = screen.getByRole("img", { name: "chart" });
    fireEvent.keyDown(chart, { key: "End" });
    const tip = document.getElementById("tl-readout") as HTMLElement;
    expect(within(tip).getByText("19:00")).toBeInTheDocument();
    expect(within(tip).getByText("Seen by the twin · native Dexcom")).toBeInTheDocument();
  });
});

describe("twin rail", () => {
  const mk = (id: string, at: string): Meal => ({ meal_id: id, started_at: at, meal_type: "lunch", carbs_g: 1, protein_g: 1, fat_g: 1, fiber_g: 1, calories_kcal: 1, macro_validity: "valid", macro_reasons: null, image_path: null });
  const meals = [mk("m1", "2021-06-05T12:00:00"), mk("m2", "2021-06-06T12:00:00"), mk("m3", "2021-06-07T12:00:00")];
  const outcomes = meals.map((m) => ({ meal_id: m.meal_id, started_at: m.started_at, eligible: true }) as MealOutcome);

  it("is one slider over the real meal times; arrows move the moment", async () => {
    cgmServer();
    const onSelect = vi.fn();
    withQuery(
      <TwinRail patientId={7} meals={meals} outcomes={outcomes} dataFrom="2021-06-05T00:00:00" dataTo="2021-06-08T00:00:00" state={undefined} moment={{ asOf: "2021-06-06T12:00:00", mealId: "m2" }} onSelect={onSelect} />,
    );
    const rail = screen.getByRole("slider", { name: /Twin moment/ });
    expect(rail).toHaveAttribute("aria-valuetext", expect.stringMatching(/^Meal 2 of 3: Sun 6 Jun 12:00/));
    fireEvent.keyDown(rail, { key: "ArrowRight" });
    expect(onSelect).toHaveBeenCalledWith({ asOf: "2021-06-07T12:00:00", mealId: "m3" });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it("reads a between-meal moment (a replayed step) as itself, and steps to the meals either side", async () => {
    cgmServer();
    const onSelect = vi.fn();
    withQuery(
      <TwinRail patientId={7} meals={meals} outcomes={outcomes} dataFrom="2021-06-05T00:00:00" dataTo="2021-06-08T00:00:00" state={undefined} moment={{ asOf: "2021-06-06T15:30:00", mealId: null }} onSelect={onSelect} />,
    );
    const rail = screen.getByRole("slider", { name: /Twin moment/ });
    expect(rail).toHaveAttribute("aria-valuetext", "Sun 6 Jun 15:30, between meals");
    fireEvent.keyDown(rail, { key: "ArrowRight" });
    expect(onSelect).toHaveBeenLastCalledWith({ asOf: "2021-06-07T12:00:00", mealId: "m3" });
    fireEvent.keyDown(rail, { key: "ArrowLeft" });
    expect(onSelect).toHaveBeenLastCalledWith({ asOf: "2021-06-06T12:00:00", mealId: "m2" });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });
});
