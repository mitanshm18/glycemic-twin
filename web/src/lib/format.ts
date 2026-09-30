/** Number formatting used everywhere, so units and precision are consistent. */

export const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? v.toFixed(digits) : DASH;
}

/** 0.4213 -> "42%" (or "42.1%" with digits = 1) */
export function fmtPct(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : DASH;
}

/** Signed percentage points: +4.2 pp */
export function fmtPp(v: number | null | undefined, digits = 1): string {
  if (!isNum(v)) return DASH;
  const pp = v * 100;
  const sign = pp > 0 ? "+" : pp < 0 ? "−" : "±";
  return `${sign}${Math.abs(pp).toFixed(digits)} pp`;
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(digits)}`;
}

/** First 12 hex chars of a SHA-256, the conventional short form. */
export function shortHash(h: string | null | undefined, n = 12): string {
  return h ? h.slice(0, n) : DASH;
}

/** "xgboost__full_personal@contract-v1-92b22c0cf283/data-0c61090e1568/2026-…" -> "XGBoost · full_personal" */
export function modelLabel(name: string | null | undefined, featureSet?: string | null): string {
  if (!name) return DASH;
  const pretty = name === "xgboost" ? "XGBoost" : name === "logistic" ? "Logistic regression" : name;
  return featureSet ? `${pretty} · ${featureSet}` : pretty;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** The engine's change sentences carry full-precision floats ("scored:0.6757997958"); round them for reading. */
export function tidyNumbers(text: string): string {
  return text.replace(/-?\d+\.\d{4,}/g, (m) => {
    const v = Number(m);
    return Math.abs(v) <= 1 ? v.toFixed(3) : v.toFixed(1);
  });
}
