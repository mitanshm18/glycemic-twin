import { clamp, DASH, fmtNum, fmtPct, fmtPp, fmtSigned, isNum, modelLabel, shortHash, readableChange } from "@/lib/format";

describe("number formatting", () => {
  it("never renders NaN, Infinity or null as a number", () => {
    for (const v of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(fmtNum(v)).toBe(DASH);
      expect(fmtPct(v)).toBe(DASH);
      expect(fmtPp(v)).toBe(DASH);
      expect(fmtSigned(v)).toBe(DASH);
    }
    expect(isNum(0)).toBe(true);
    expect(isNum("1")).toBe(false);
  });

  it("formats probabilities and signed changes", () => {
    expect(fmtPct(0.4213)).toBe("42%");
    expect(fmtPct(0.4213, 1)).toBe("42.1%");
    expect(fmtPp(0.042)).toBe("+4.2 pp");
    expect(fmtPp(-0.109)).toBe("−10.9 pp");
    expect(fmtPp(0)).toBe("±0.0 pp");
    expect(fmtSigned(-0.5)).toBe("−0.50");
    expect(fmtSigned(0.48)).toBe("+0.48");
  });

  it("labels models and hashes", () => {
    expect(modelLabel("xgboost", "full_personal")).toBe("XGBoost · full_personal");
    expect(modelLabel("logistic")).toBe("Logistic regression");
    expect(modelLabel(null)).toBe(DASH);
    expect(shortHash("0c61090e1568ea611fc6a200")).toBe("0c61090e1568");
    expect(clamp(5, 0, 1)).toBe(1);
  });
});

describe("readable engine changes", () => {
  it("re-expresses the engine's own values and drops what the page already shows", () => {
    expect(readableChange("risk scored:0.118 -> scored:0.136")).toEqual({ text: "Estimated risk 12% → 14%", rank: 1 });
    expect(readableChange("personal rate 0.450 -> 0.478, weight 0.90 -> 0.89")?.text).toBe("Personal response rate 45% → 48%, evidence weight 90% → 89%");
    expect(readableChange("lifecycle WARMING -> PERSONALIZED: weight >= 0.5")?.text).toBe("Lifecycle Warming up → Personalized");
    expect(readableChange("latest glucose 97.0 -> 86.0 mg/dL")?.text).toBe("Latest glucose 97 → 86 mg/dL");
    expect(readableChange("risk scored:0.2 -> not_applicable:None")?.text).toBe("Estimated risk 20% → no estimate");
    expect(readableChange("current meal 3-1 -> 3-2")).toBeNull();
    expect(readableChange("a different model version produced the risk")?.text).toBe("a different model version produced the risk");
  });
});
