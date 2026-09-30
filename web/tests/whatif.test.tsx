import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { WhatIf } from "@/components/twin/WhatIf";
import type { ScenarioResult, TwinState } from "@/lib/api/types";
import { scenarioSummary, thresholdRelation } from "@/lib/whatif";
import fixture from "./fixtures/twin-state.synthetic.json";
import { setMedia } from "./setup";

// SYNTHETIC fixture: produced by the real twin_core engine on the synthetic test record.
const STATE = fixture as unknown as TwinState;
const BASE = STATE.risk.probability as number; // 0.676
const T = STATE.risk.threshold as number; // 0.376

describe("threshold relation (neutral wording)", () => {
  it("names crossings, and closer / further on the same side", () => {
    expect(thresholdRelation(0.12, 0.45, 0.37)).toMatchObject({ move: "crosses-above", above: true, gapPp: 8, wasPp: 25 });
    expect(thresholdRelation(0.79, 0.3, 0.37)).toMatchObject({ move: "falls-below", above: false });
    expect(thresholdRelation(0.79, 0.61, 0.37)).toMatchObject({ move: "closer", text: "Stays above the alert threshold, closer to it" });
    expect(thresholdRelation(0.2, 0.1, 0.37).move).toBe("further");
    for (const r of [thresholdRelation(0.2, 0.5, 0.37), thresholdRelation(0.5, 0.2, 0.37)]) {
      expect(r.text).not.toMatch(/should|recommend|safe|better|worse/i);
    }
  });
  it("summarises one answer for screen readers", () => {
    expect(scenarioSummary(0.12, 0.07, 0.37)).toBe("Scenario estimate 7%, 5.0 percentage points lower than as logged (12%). Stays below the alert threshold, further to it.");
  });
});

function scenario(p: number | null, status: ScenarioResult["status"] = "ok"): ScenarioResult {
  return {
    scenario_id: `s-${p}-${status}`,
    status,
    patient_id: STATE.patient_id,
    as_of: STATE.as_of,
    base_state_id: STATE.state_id,
    meal_id: STATE.current_meal?.meal_id ?? null,
    changes: { carbs_g: -20 },
    baseline_probability: BASE,
    scenario_probability: p,
    risk_delta: p === null ? null : p - BASE,
    changed_inputs: [{ feature: "carbs_g", before: 60, after: status === "ok" ? 40 : 400, support_lo: 5, support_hi: 180, in_support: status === "ok" }],
    held_fixed: "every other input",
    uncertainty: { level: "moderate", reasons: [], outcome_entropy_bits: null, distance_to_threshold: null, personal_weight: null, missing_inputs: [], out_of_support_inputs: [], support_checked: true, note: "" },
    model: STATE.provenance.model!,
    disclaimer: "x",
    kind: "what_if",
  };
}

/** A what-if endpoint that answers when told to, so the pending state can be looked at. */
function whatIfServer(answer: ScenarioResult) {
  const bodies: unknown[] = [];
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => (release = r));
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/auth/csrf")) return new Response(JSON.stringify({ csrf_token: "t" }), { status: 200 });
    if (url.includes("/what-if")) {
      bodies.push(JSON.parse(String(init?.body)));
      await gate;
      return new Response(JSON.stringify(answer), { status: 200 });
    }
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "x" } }), { status: 404 });
  }) as typeof fetch;
  return { bodies, release: () => release() };
}

function renderWhatIf() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WhatIf state={STATE} />
    </QueryClientProvider>,
  );
}

const carbs = () => screen.getByRole("slider", { name: "Carbohydrate" });
const scenarioDial = () => screen.getByRole("img", { name: /^Scenario/ });

describe("what-if comparison", () => {
  beforeEach(() => setMedia("(prefers-reduced-motion: reduce)", true)); // values update immediately

  it("keeps the baseline visible and the lever says it is calculating while the model answers", async () => {
    const srv = whatIfServer(scenario(0.3));
    renderWhatIf();
    fireEvent.change(carbs(), { target: { value: "-20" } });
    expect(await screen.findByText("calculating")).toBeInTheDocument(); // during the pause before the request
    await waitFor(() => expect(srv.bodies).toHaveLength(1), { timeout: 2000 });
    expect(screen.getByText("calculating")).toBeInTheDocument(); // and while the model answers
    expect(screen.getByRole("img", { name: /^As logged: 68%/ })).toBeInTheDocument();
    expect(scenarioDial()).toHaveAccessibleName(/68%/); // still where it was: no blank "estimating" state
    expect(srv.bodies[0]).toMatchObject({ changes: { carbs_g: -20 } });
    srv.release();
    await waitFor(() => expect(scenarioDial()).toHaveAccessibleName(/30%/));
    expect(screen.queryByText("calculating")).toBeNull();
  });

  it("shows the server's delta and the threshold crossing once settled", async () => {
    const srv = whatIfServer(scenario(0.3));
    renderWhatIf();
    fireEvent.change(carbs(), { target: { value: "-20" } });
    srv.release();
    await screen.findByText("Falls below the alert threshold", {}, { timeout: 3000 });
    expect(screen.getByText("−37.6 pp")).toBeInTheDocument();
    expect(screen.getByText("Within training support")).toBeInTheDocument();
    expect(screen.getByText("Moderate uncertainty")).toBeInTheDocument();
    expect(screen.getByText(/Scenario estimate 30%, 37\.6 percentage points lower/)).toBeInTheDocument();
    // the non-causal framing stays
    expect(screen.getByText("Non-causal")).toBeInTheDocument();
    expect(screen.getByText("Not medical advice")).toBeInTheDocument();
    expect(T).toBeGreaterThan(0.3);
  });

  it("collapses to no estimate outside training support, with the real trained range", async () => {
    const srv = whatIfServer(scenario(null, "out_of_support"));
    renderWhatIf();
    fireEvent.change(carbs(), { target: { value: "100" } });
    srv.release();
    await screen.findByText(/No estimate: this scenario leaves the range/, {}, { timeout: 3000 });
    expect(scenarioDial()).toHaveAccessibleName(/no estimate/);
    expect(scenarioDial()).toHaveTextContent("—");
    expect(screen.getByText(/5 g – 180 g/)).toBeInTheDocument();
    expect(screen.queryByText(/pp$/)).toBeNull(); // no delta without an estimate
  });

  it("runs a quick scenario through the same request", async () => {
    const srv = whatIfServer(scenario(0.3));
    renderWhatIf();
    const quick = within(screen.getByRole("group", { name: "Quick scenarios" }));
    fireEvent.click(quick.getByRole("button", { name: "−20 g carbs" }));
    expect(carbs()).toHaveValue("-20");
    expect(quick.getByRole("button", { name: "−20 g carbs" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(srv.bodies).toHaveLength(1), { timeout: 2000 });
    expect(srv.bodies[0]).toMatchObject({ changes: { carbs_g: -20 } });
    for (const forbidden of [/insulin/i, /medication/i, /dose/i]) expect(quick.queryByRole("button", { name: forbidden })).toBeNull();
  });
});
