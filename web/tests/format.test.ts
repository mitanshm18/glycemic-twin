import { clamp, DASH, fmtNum, fmtPct, fmtPp, fmtSigned, isNum, modelLabel, shortHash } from "@/lib/format";

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
