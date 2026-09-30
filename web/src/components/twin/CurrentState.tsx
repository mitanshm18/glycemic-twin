"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Origin, Tag } from "@/components/ui/Tag";
import { Tip } from "@/components/ui/Tip";
import type { TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtNum, fmtPct, modelLabel } from "@/lib/format";
import { useAnimatedNumber } from "@/lib/motion";
import {
  OUTCOME,
  PHASE_LABEL,
  PHASE_TONE,
  UNCERTAINTY_LABEL,
  UNCERTAINTY_TONE,
  riskView,
} from "@/lib/risk";
import { fmtClock, fmtDateTime, fmtDuration, MINUTE, parseNaive } from "@/lib/time";
import { RiskDial } from "./RiskDial";

/** Keys of `values` whose value differs from the previous render (for a brief highlight). */
function useChanged(values: Record<string, unknown>, resetKey: string): Set<string> {
  const prev = useRef<Record<string, unknown> | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const sig = JSON.stringify(values);
  useEffect(() => {
    const before = prev.current;
    if (before) {
      const next = new Set(Object.keys(values).filter((k) => before[k] !== values[k]));
      setChanged(next);
    }
    prev.current = values;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, resetKey]);
  return changed;
}

function trend(slope: number | null): { icon: "arrowUp" | "arrowDown" | "arrowRight"; text: string } | null {
  if (slope === null) return null;
  if (slope > 1) return { icon: "arrowUp", text: `rising ${fmtNum(slope, 1)} mg/dL/min` };
  if (slope < -1) return { icon: "arrowDown", text: `falling ${fmtNum(Math.abs(slope), 1)} mg/dL/min` };
  return { icon: "arrowRight", text: `steady (${fmtNum(slope, 1)} mg/dL/min)` };
}

export function CurrentState({ state }: { state: TwinState }) {
  const { risk, current_physiology: phys, freshness, lifecycle, current_meal: meal } = state;
  const view = riskView(risk.status, risk.probability, risk.threshold);
  const unc = risk.uncertainty;
  const model = state.provenance.model;
  const glucose = useAnimatedNumber(phys.glucose_mgdl);
  const tr = trend(phys.slope_15_mgdl_per_min);
  const asOf = parseNaive(state.as_of);
  const changed = useChanged(
    {
      glucose: phys.glucose_mgdl,
      phase: lifecycle.phase,
      unc: unc?.level ?? null,
      fresh: freshness.cgm_age_min,
      status: risk.status,
    },
    String(state.patient_id),
  );
  const flash = (k: string) => (changed.has(k) ? "changed" : undefined);

  const dialLabel =
    risk.status === "scored"
      ? `Model estimate ${fmtPct(risk.probability)} probability of ${OUTCOME}. Alert threshold ${fmtPct(risk.threshold)}. ${view.label}.`
      : `No probability: ${risk.reason ?? view.label}`;

  return (
    <div className="hero" aria-labelledby="now-title">
      <h2 id="now-title" className="sr-only">
        Current twin state
      </h2>

      {/* ---- model estimate ---- */}
      <div className="hero__risk">
        <Origin kind="model" />
        <div className="hero__dial">
          <RiskDial probability={risk.probability} threshold={risk.threshold} tone={view.tone} label={dialLabel} />
          <div className="hero__risk-text">
            <Tag
              key={view.short}
              className="tag--enter"
              tone={view.tone}
              icon={view.glyph === "up" ? "arrowUp" : view.glyph === "down" ? "arrowDown" : "dash"}
            >
              {view.short}
            </Tag>
            <p className="hero__outcome">
              {risk.status === "scored" ? (
                <>
                  Estimated probability of <strong>glucose above 180 mg/dL</strong> within 120 min of{" "}
                  {meal ? `the ${meal.meal_type ?? "meal"} at ${fmtClock(parseNaive(meal.started_at))}` : "this meal"}.
                </>
              ) : (
                <>{risk.reason ?? "There is no meal with an open prediction window at this moment."}</>
              )}
            </p>
            {risk.threshold !== null && (
              <p className="hero__threshold">
                <span className="hero__tick" aria-hidden="true" />
                Alert threshold <span className="mono">{fmtPct(risk.threshold)}</span>
                <Tip text="Chosen on held-out training folds to maximise F1 (M3). Estimates at or above it are flagged." focusable label="About the alert threshold">
                  <Icon name="info" size={13} className="muted" />
                </Tip>
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="hero__rule" aria-hidden="true" />

      {/* ---- measured + twin status ---- */}
      <div className="hero__facts">
        <div className={cx("hero__glucose", flash("glucose"))}>
          <Origin kind="observed" />
          <div className="hero__glucose-row">
            <span className="hero__glucose-num mono">{glucose === null ? "—" : Math.round(glucose)}</span>
            <span className="hero__glucose-unit">mg/dL</span>
            {tr && (
              <span className="hero__trend" title={tr.text}>
                <Icon name={tr.icon} size={16} />
                <span className="sr-only">{tr.text}</span>
              </span>
            )}
          </div>
          <p className="hero__sub">
            {phys.glucose_mgdl === null
              ? "No native Dexcom reading in the 15 min before this moment"
              : `Native Dexcom reading, ${fmtDuration((phys.glucose_age_min ?? 0) * MINUTE)} before ${fmtClock(asOf)}${tr ? ` · ${tr.text}` : ""}`}
          </p>
        </div>

        <dl className="hero__grid">
          <div className={flash("phase")}>
            <dt>Twin lifecycle</dt>
            <dd>
              <Tag tone={PHASE_TONE[lifecycle.phase]}>{PHASE_LABEL[lifecycle.phase]}</Tag>
              <span className="hero__note">
                {lifecycle.closed_usable_meals} closed meal{lifecycle.closed_usable_meals === 1 ? "" : "s"} learned
              </span>
            </dd>
          </div>
          <div className={flash("unc")}>
            <dt>Uncertainty</dt>
            <dd>
              {unc ? (
                <>
                  <Tag tone={UNCERTAINTY_TONE[unc.level]}>{UNCERTAINTY_LABEL[unc.level]}</Tag>
                  <span className="hero__note">{unc.reasons[0] ?? "No reliability flags raised"}</span>
                </>
              ) : (
                <span className="muted">Not applicable</span>
              )}
            </dd>
          </div>
          <div className={flash("fresh")}>
            <dt>Data freshness</dt>
            <dd>
              <Tag tone={freshness.cgm_stale ? "warning" : "success"} icon={freshness.cgm_stale ? "alert" : "check"}>
                {freshness.cgm_stale ? "CGM stale" : "CGM current"}
              </Tag>
              <span className="hero__note">
                {freshness.cgm_age_min === null ? "no CGM yet" : `CGM ${fmtDuration(freshness.cgm_age_min * MINUTE)} old`}
                {" · "}
                {freshness.wearable_age_min === null
                  ? "no wearable data"
                  : freshness.wearable_stale
                    ? `wearable ${fmtDuration(freshness.wearable_age_min * MINUTE)} old`
                    : "wearable current"}
              </span>
            </dd>
          </div>
          <div>
            <dt>Moment</dt>
            <dd>
              <span className="mono">{fmtDateTime(asOf)}</span>
              <span className="hero__note">Nothing after this time is visible to the twin</span>
            </dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>
              <span>{modelLabel(model?.model_name, model?.feature_set)}</span>
              <span className="hero__note mono">
                contract v{model?.contract_version ?? "—"} · {model?.n_columns ?? "—"} inputs
              </span>
            </dd>
          </div>
          {meal && (
            <div>
              <dt>Current meal</dt>
              <dd>
                <span>
                  {meal.meal_type ?? "Meal"} · <span className="mono">{fmtClock(parseNaive(meal.started_at))}</span>
                </span>
                <span className="hero__note">
                  {meal.macros_valid
                    ? `${fmtNum(meal.carbs_g)} g carbs · ${fmtNum(meal.fiber_g)} g fiber · ${fmtNum(meal.calories_kcal)} kcal`
                    : "macros not usable"}
                </span>
              </dd>
            </div>
          )}
        </dl>
      </div>
    </div>
  );
}
