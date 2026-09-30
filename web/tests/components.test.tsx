import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { CurrentState } from "@/components/twin/CurrentState";
import { RiskDial } from "@/components/twin/RiskDial";
import { WhatIf } from "@/components/twin/WhatIf";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorState } from "@/components/ui/StateMessage";
import { Tip } from "@/components/ui/Tip";
import { ApiError } from "@/lib/api/client";
import type { TwinState } from "@/lib/api/types";
import fixture from "./fixtures/twin-state.synthetic.json";

// SYNTHETIC fixture: produced by the real twin_core engine on the synthetic test record.
const STATE = fixture as unknown as TwinState;

function withQuery(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("RiskDial", () => {
  it("exposes its meaning as text, not only as an arc", () => {
    render(<RiskDial probability={0.72} threshold={0.37} tone="risk" label="72% estimated probability, alert threshold 37%" />);
    expect(screen.getByRole("img", { name: /72% estimated probability/ })).toBeInTheDocument();
  });

  it("shows a dash, not 0%, when there is no estimate", () => {
    render(<RiskDial probability={null} threshold={null} tone="neutral" label="No prediction" />);
    expect(screen.getByRole("img")).toHaveTextContent("—");
    expect(screen.getByRole("img")).not.toHaveTextContent("0%");
  });
});

describe("Segmented", () => {
  function Harness() {
    const [v, setV] = useState<"a" | "b" | "c">("a");
    return (
      <Segmented
        label="Choice"
        value={v}
        onChange={setV}
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
          { value: "c", label: "C" },
        ]}
      />
    );
  }

  it("is one tab stop with arrow-key selection (radio group pattern)", () => {
    render(<Harness />);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    fireEvent.keyDown(radios[0]!, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "B" })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(screen.getByRole("radio", { name: "B" }), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("radio", { name: "A" }), { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "C" })).toHaveAttribute("aria-checked", "true");
  });
});

describe("Tip", () => {
  it("gives a focusable trigger a name and the tip as its description", () => {
    render(
      <Tip text="Chosen on training folds" focusable label="About the threshold">
        <span aria-hidden="true">i</span>
      </Tip>,
    );
    const btn = screen.getByRole("button", { name: "About the threshold" });
    expect(btn).toHaveAccessibleDescription("Chosen on training folds");
  });
});

describe("ErrorState", () => {
  it("announces a specific, code-backed message with a retry", () => {
    const retry = vi.fn();
    render(<ErrorState error={new ApiError(503, "MODEL_UNAVAILABLE", "x")} what="the twin" onRetry={retry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Model unavailable");
    expect(alert).toHaveTextContent("MODEL_UNAVAILABLE");
    fireEvent.click(within(alert).getByRole("button", { name: /try again|retry/i }));
    expect(retry).toHaveBeenCalled();
  });
});

describe("CurrentState", () => {
  it("separates the model estimate from measured values and names the outcome", () => {
    withQuery(<CurrentState state={STATE} />);
    expect(screen.getByText("Model estimate")).toBeInTheDocument();
    expect(screen.getByText("Measured")).toBeInTheDocument();
    expect(screen.getAllByText(/glucose above 180 mg\/dL/).length).toBeGreaterThan(0);
  });
});

describe("WhatIf", () => {
  it("is labelled as a non-causal model scenario and only offers meal and activity levers", () => {
    withQuery(<WhatIf state={STATE} />);
    expect(screen.getByText("Model-estimated scenario")).toBeInTheDocument();
    expect(screen.getByText("Non-causal")).toBeInTheDocument();
    expect(screen.getByText("Not medical advice")).toBeInTheDocument();
    for (const name of ["Carbohydrate", "Fiber", "Protein", "Fat"]) {
      expect(screen.getByRole("slider", { name })).toBeInTheDocument();
    }
    for (const forbidden of [/insulin/i, /medication/i, /dose/i, /metformin/i, /diagnos/i]) {
      expect(screen.queryByLabelText(forbidden)).toBeNull();
    }
  });

  it("explains itself instead of offering levers when nothing is scored", () => {
    const unscored = { ...STATE, risk: { ...STATE.risk, status: "not_applicable" as const }, current_meal: null };
    withQuery(<WhatIf state={unscored} />);
    expect(screen.getByText(/needs a scored meal/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("slider")).toHaveLength(0);
  });
});
