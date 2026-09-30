import { PHASE_LABEL, PHASES, riskView, UNCERTAINTY_LABEL } from "@/lib/risk";

describe("risk language", () => {
  it("compares the probability with the model's own threshold", () => {
    expect(riskView("scored", 0.4, 0.38).short).toBe("Above threshold");
    expect(riskView("scored", 0.38, 0.38).tone).toBe("risk");
    expect(riskView("scored", 0.2, 0.38).glyph).toBe("down");
  });

  it("never presents an unscored state as low risk", () => {
    for (const s of ["not_applicable", "unavailable"] as const) {
      const v = riskView(s, 0.1, 0.38);
      expect(v.tone).toBe("neutral");
      expect(v.glyph).toBe("dash");
    }
    expect(riskView("scored", null, 0.38).short).toBe("No prediction");
  });

  it("has a text label for every phase and uncertainty level", () => {
    expect(PHASES.map((p) => PHASE_LABEL[p])).toEqual(["Cold start", "Warming up", "Personalized"]);
    expect(Object.keys(UNCERTAINTY_LABEL)).toEqual(["low", "moderate", "high"]);
  });
});
