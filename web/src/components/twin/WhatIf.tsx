"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { isApiError } from "@/lib/api/client";
import { useWhatIf } from "@/lib/api/queries";
import type { Lever, ScenarioResult, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { featureInfo, fmtFeature } from "@/lib/features";
import { fmtNum, fmtPct, fmtPp } from "@/lib/format";
import { useAnimatedNumber } from "@/lib/motion";
import { UNCERTAINTY_LABEL, UNCERTAINTY_TONE } from "@/lib/risk";

/**
 * Slider ranges are UI affordances only (the server enforces the real bounds from twin.v1 and
 * the training-support profile, and its answer is always the one shown).
 */
const LEVERS: Array<{ key: Lever; label: string; unit: string; min: number; max: number; step: number }> = [
  { key: "carbs_g", label: "Carbohydrate", unit: "g", min: -100, max: 100, step: 5 },
  { key: "fiber_g", label: "Fiber", unit: "g", min: -30, max: 30, step: 1 },
  { key: "protein_g", label: "Protein", unit: "g", min: -60, max: 60, step: 5 },
  { key: "fat_g", label: "Fat", unit: "g", min: -60, max: 60, step: 5 },
  { key: "active_min_3h", label: "Active minutes before the meal", unit: "min", min: -120, max: 120, step: 5 },
];

type Deltas = Partial<Record<Lever, number>>;

function LeverRow({
  lever,
  base,
  delta,
  onChange,
}: {
  lever: (typeof LEVERS)[number];
  base: number;
  delta: number;
  onChange: (v: number) => void;
}) {
  const id = useId();
  const after = base + delta;
  return (
    <div className={cx("lever", delta !== 0 && "lever--changed")}>
      <label htmlFor={id} className="lever__label">
        {lever.label}
      </label>
      <div className="lever__values mono">
        <span className="muted">{fmtNum(base)}</span>
        <Icon name="arrowRight" size={12} className="muted" />
        <span className={cx(after < 0 && "lever__invalid")}>{fmtNum(after)}</span>
        <span className="muted">{lever.unit}</span>
      </div>
      <input
        id={id}
        className="lever__range"
        type="range"
        min={lever.min}
        max={lever.max}
        step={lever.step}
        value={delta}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={`${delta >= 0 ? "plus" : "minus"} ${Math.abs(delta)} ${lever.unit}, ${fmtNum(after)} ${lever.unit} in total`}
      />
      <span className={cx("lever__delta mono", delta > 0 && "is-up", delta < 0 && "is-down")}>
        {delta > 0 ? "+" : delta < 0 ? "−" : "±"}
        {Math.abs(delta)} {lever.unit}
      </span>
    </div>
  );
}

function Compare({ label, p, threshold, model }: { label: string; p: number | null; threshold: number; model?: boolean }) {
  return (
    <div className="cmp">
      <span className="cmp__label">{label}</span>
      <span className="cmp__track">
        {p !== null && <span className={cx("cmp__fill", model && "cmp__fill--model")} style={{ width: `${p * 100}%` }} />}
        <span className="cmp__threshold" style={{ left: `${threshold * 100}%` }} aria-hidden="true" />
      </span>
      <span className="cmp__val mono">{fmtPct(p)}</span>
    </div>
  );
}

/** The scenario's effect, counting smoothly to each new server answer. */
function Delta({ d }: { d: number }) {
  const shown = useAnimatedNumber(d, 320) ?? d;
  const dir = d > 0.0005 ? "up" : d < -0.0005 ? "down" : "flat";
  return (
    <span className={cx("wi-delta mono", dir === "up" && "is-up", dir === "down" && "is-down")}>
      <Icon name={dir === "up" ? "arrowUp" : dir === "down" ? "arrowDown" : "dash"} size={18} />
      {fmtPp(shown)}
    </span>
  );
}

function Result({ r, threshold }: { r: ScenarioResult; threshold: number }) {
  if (r.status === "out_of_support") {
    const off = r.changed_inputs.filter((c) => !c.in_support);
    return (
      <div className="wi-result wi-result--oos" aria-live="polite">
        <div className="row">
          <Tag tone="warning" icon="alert">
            Outside training support
          </Tag>
        </div>
        <p className="wi-result__title">No estimate: this scenario leaves the range the model was trained on.</p>
        <p className="small secondary">
          Estimates are only reported where every changed input stays within the 1st–99th percentile of the
          training meals. Beyond that the model would be extrapolating.
        </p>
        <ul className="support">
          {off.map((c) => {
            const lo = c.support_lo ?? 0;
            const hi = c.support_hi ?? 1;
            const span = hi - lo || 1;
            const pos = c.after === null ? 0 : Math.min(1.08, Math.max(-0.08, (c.after - lo) / span));
            return (
              <li key={c.feature} className="support__item">
                <span className="support__name">{featureInfo(c.feature).label}</span>
                <span className="support__track" aria-hidden="true">
                  <span className="support__range" />
                  <span className="support__value" style={{ left: `${10 + pos * 80}%` }} />
                </span>
                <span className="small">
                  <span className="mono">{fmtFeature(c.feature, c.after)}</span> vs trained range{" "}
                  <span className="mono">
                    {fmtFeature(c.feature, c.support_lo)} – {fmtFeature(c.feature, c.support_hi)}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }
  const d = r.risk_delta ?? 0;
  return (
    <div className="wi-result" aria-live="polite">
      <Compare label="As logged" p={r.baseline_probability} threshold={threshold} />
      <Compare label="Scenario" p={r.scenario_probability} threshold={threshold} model />
      <div className="wi-result__delta">
        <Delta d={d} />
        <span className="small secondary">change in the model-estimated probability</span>
      </div>
      <div className="row">
        <Tag tone="success" icon="check">
          Within training support
        </Tag>
        {r.uncertainty && <Tag tone={UNCERTAINTY_TONE[r.uncertainty.level]}>{UNCERTAINTY_LABEL[r.uncertainty.level]}</Tag>}
      </div>
      <p className="xsmall muted">Held fixed: {r.held_fixed}.</p>
    </div>
  );
}

export function WhatIf({ state }: { state: TwinState }) {
  const meal = state.current_meal;
  const scored = state.risk.status === "scored" && meal !== null;
  const mutation = useWhatIf(state.patient_id);
  const [deltas, setDeltas] = useState<Deltas>({});
  const timer = useRef<number | undefined>(undefined);

  const activity = state.current_physiology.active_min_3h;
  const levers = useMemo(() => LEVERS.filter((l) => l.key !== "active_min_3h" || activity !== null), [activity]);
  const baseOf = (k: Lever): number =>
    k === "active_min_3h" ? (activity ?? 0) : ((meal?.[k] as number | null | undefined) ?? 0);

  // A new moment resets the scenario.
  useEffect(() => {
    setDeltas({});
    mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.state_id]);

  const changes = Object.fromEntries(Object.entries(deltas).filter(([, v]) => v !== 0)) as Deltas;
  const key = JSON.stringify(changes);

  // input change -> short pause -> run (validation and support checks happen on the server)
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!scored || Object.keys(changes).length === 0) return;
    timer.current = window.setTimeout(() => {
      mutation.mutate({ asOf: state.as_of, mealId: meal?.meal_id ?? null, changes });
    }, 450);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, scored, state.as_of]);

  if (!scored) {
    return (
      <EmptyState icon="sliders" title="What-if needs a scored meal">
        Scenarios change the macros of the meal the twin is predicting. Choose a moment with a scored meal
        (above) to explore one.
      </EmptyState>
    );
  }

  const disabled = isApiError(mutation.error, "MODEL_UNAVAILABLE");
  const threshold = state.risk.threshold ?? 0.5;
  const nothing = Object.keys(changes).length === 0;

  return (
    <div className="whatif">
      <div className="whatif__labels">
        <Tag tone="model">Model-estimated scenario</Tag>
        <Tag tone="neutral">Non-causal</Tag>
        <Tag tone="neutral">Not medical advice</Tag>
      </div>
      <div className="whatif__grid">
        <fieldset className="whatif__levers" disabled={disabled}>
          <legend className="sr-only">Scenario changes to the current meal</legend>
          {levers.map((l) => (
            <LeverRow
              key={l.key}
              lever={l}
              base={baseOf(l.key)}
              delta={deltas[l.key] ?? 0}
              onChange={(v) => setDeltas((d) => ({ ...d, [l.key]: v }))}
            />
          ))}
          {activity === null && (
            <p className="xsmall muted">Pre-meal activity is not available: this person&rsquo;s wearable does not record METs.</p>
          )}
          <p className="xsmall muted">Calories follow macro changes automatically. Post-meal activity cannot be simulated: the model has no post-meal inputs.</p>
          <div className="row">
            <Button size="sm" variant="ghost" onClick={() => setDeltas({})} disabled={nothing}>
              <Icon name="rotate" size={14} /> Reset
            </Button>
          </div>
        </fieldset>

        <div className="whatif__out">
          {disabled ? (
            <EmptyState icon="shield" title="What-if is disabled on this server" tone="notice">
              The active model has no training-support profile, so scenarios cannot be checked against the range
              it was trained on. An admin can build one with <code>make support-profile</code>.
            </EmptyState>
          ) : nothing ? (
            <div className="wi-idle">
              <Compare label="As logged" p={state.risk.probability} threshold={threshold} />
              <p className="small secondary">Move a slider to estimate how the model&rsquo;s probability would change for this meal.</p>
            </div>
          ) : mutation.isError ? (
            <EmptyState icon="alert" title="Scenario not accepted" tone="notice">
              {isApiError(mutation.error, "WHAT_IF_UNSUPPORTED") || isApiError(mutation.error, "VALIDATION_ERROR")
                ? (mutation.error as Error).message
                : "The server could not evaluate this scenario. Try a smaller change."}
            </EmptyState>
          ) : mutation.data ? (
            <div className={cx(mutation.isPending && "is-pending")}>
              <Result r={mutation.data} threshold={threshold} />
            </div>
          ) : (
            <div className="wi-idle" aria-live="polite">
              <p className="small secondary">Estimating…</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
