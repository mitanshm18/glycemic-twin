import { parseNaive } from "@/lib/time";
import { glucoseDomain, linear, linePath, nearest, timeTicks, toPoints, verdict, windowOutcome, type Pt } from "@/lib/timeline";
import type { CgmPoint, MealOutcome } from "@/lib/api/types";

const T0 = parseNaive("2021-06-05T12:00:00");
const pts = (vals: number[], stepMin = 5): Pt[] => vals.map((v, i) => ({ t: T0 + i * stepMin * 60_000, v }));

describe("CGM points", () => {
  it("keep only native Dexcom readings, sorted", () => {
    const raw: CgmPoint[] = [
      { ts: "2021-06-05T12:05:00", dexcom_mgdl: 120, dexcom_is_native: true, libre_mgdl: null },
      { ts: "2021-06-05T12:01:00", dexcom_mgdl: 118.4, dexcom_is_native: false, libre_mgdl: null },
      { ts: "2021-06-05T12:00:00", dexcom_mgdl: 117, dexcom_is_native: true, libre_mgdl: 110 },
      { ts: "2021-06-05T12:10:00", dexcom_mgdl: null, dexcom_is_native: true, libre_mgdl: null },
    ];
    expect(toPoints(raw).map((p) => p.v)).toEqual([117, 120]);
  });
});

describe("chart geometry", () => {
  it("linear scales invert", () => {
    const x = linear([0, 10], [100, 200]);
    expect(x(5)).toBe(150);
    expect(x.invert(150)).toBe(5);
  });

  it("uses a fixed clinical glucose frame that only grows", () => {
    expect(glucoseDomain(pts([100, 150]))).toEqual([40, 300]);
    const [lo, hi] = glucoseDomain(pts([35, 330]));
    expect(lo).toBeLessThanOrEqual(25);
    expect(hi).toBeGreaterThanOrEqual(340);
  });

  it("breaks the line across CGM gaps instead of inventing readings", () => {
    const x = linear([T0, T0 + 3 * 3_600_000], [0, 300]);
    const y = linear([40, 300], [100, 0]);
    const gap: Pt[] = [...pts([100, 101]), { t: T0 + 60 * 60_000, v: 140 }];
    const d = linePath(gap, x, y);
    expect(d.match(/M/g)).toHaveLength(2);
  });

  it("puts ticks on whole hours and respects the budget", () => {
    const ticks = timeTicks(T0 + 7 * 60_000, T0 + 7 * 3_600_000, 4);
    expect(ticks.length).toBeLessThanOrEqual(4);
    for (const t of ticks) expect(t % 3_600_000).toBe(0);
  });

  it("finds the nearest reading", () => {
    const p = pts([1, 2, 3, 4]);
    expect(nearest(p, T0 + 11 * 60_000)).toBe(2);
    expect(nearest([], T0)).toBe(-1);
  });
});

describe("prediction vs reality", () => {
  const outcome = (label: 0 | 1, usable = true) => ({ label, frozen_usable: usable }) as MealOutcome;

  it("reads the window after the moment only, and trusts the frozen label", () => {
    const series = pts([150, 170, 185, 200, 190, 175]);
    const w = windowOutcome(series, T0, 120, outcome(1));
    expect(w.peak?.v).toBe(200);
    expect(w.firstAbove?.v).toBe(185);
    expect(w.label).toBe(1);
    expect(windowOutcome(series, T0, 120, outcome(1, false)).label).toBeNull();
  });

  it("names every quadrant of the decision", () => {
    expect(verdict(0.6, 0.38, 1)).toBe("true_alert");
    expect(verdict(0.6, 0.38, 0)).toBe("false_alarm");
    expect(verdict(0.2, 0.38, 1)).toBe("missed");
    expect(verdict(0.2, 0.38, 0)).toBe("true_quiet");
    expect(verdict(0.38, 0.38, 0)).toBe("false_alarm");
  });
});
