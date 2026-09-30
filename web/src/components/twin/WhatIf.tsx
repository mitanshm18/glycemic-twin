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
import { easeOut, MOTION, prefersReducedMotion, useAnimatedNumber } from "@/lib/motion";
import { riskView, UNCERTAINTY_LABEL, UNCERTAINTY_TONE } from "@/lib/risk";
import { QUICK, scenarioSummary, thresholdRelation } from "@/lib/whatif";
import { RiskDial } from "./RiskDial";

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

const DEBOUNCE_MS = 450;
const MORPH_MS = MOTION.morph; // the same time the risk dial takes: number, arc and bar move as one
const SETTLE_MS = MOTION.settle; // the delta and the support/uncertainty arrive once the value has mostly settled

type Deltas = Partial<Record<Lever, number>>;

function LeverRow({
  lever,
  base,
  delta,
  calculating,
  outOfSupport,
  onChange,
}: {
  lever: (typeof LEVERS)[number];
  base: number;
  delta: number;
  calculating: boolean;
  outOfSupport: boolean;
  onChange: (v: number) => void;
}) {
  const id = useId();
  const after = base + delta;
  return (
    <div className={cx("lever", delta !== 0 && "lever--changed", calculating && "lever--calculating", outOfSupport && "lever--oos")}>
      <label htmlFor={id} className="lever__label">
        {lever.label}
      </label>
      <div className="lever__values mono">
        <span className="muted">{fmtNum(base)}</span>
        <Icon name="arrowRight" size={12} className="muted" />
        <span className={cx("lever__after", after < 0 && "lever__invalid")}>{fmtNum(after)}</span>
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
        {calculating ? (
          <span className="lever__calc">
            <span className="lever__calc-dot" aria-hidden="true" />
            calculating
          </span>
        ) : (
          <>
            {delta > 0 ? "+" : delta < 0 ? "−" : "±"}
            {Math.abs(delta)} {lever.unit}
          </>
        )}
      </span>
    </div>
  );
}

/** One probability as a bar on the shared 0–100% scale, with the alert threshold marked. */
function Bar({ label, value, threshold, from, model, empty }: { label: string; value: number | null; threshold: number; from?: number; model?: boolean; empty?: boolean }) {
  const v = value === null ? null : Math.max(0, Math.min(1, value));
  const lo = from === undefined || v === null ? null : Math.min(from, v);
  const hi = from === undefined || v === null ? null : Math.max(from, v);
  return (
    <div className={cx("cmp", empty && "cmp--empty")}>
      <span className="cmp__label">{label}</span>
      <span className="cmp__track">
        {v !== null && <span className={cx("cmp__fill", model && "cmp__fill--model")} style={{ width: `${v * 100}%` }} />}
        {/* the move itself: from the baseline to where the scenario is now */}
        {lo !== null && hi !== null && hi - lo > 0.001 && (
          <span className={cx("cmp__move", v! > from! ? "is-up" : "is-down")} style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
        )}
        {from !== undefined && <span className="cmp__from" style={{ left: `${from * 100}%` }} aria-hidden="true" />}
        {empty ? <span className="cmp__none">no estimate</span> : <span className="cmp__threshold" style={{ left: `${threshold * 100}%` }} aria-hidden="true" />}
      </span>
      <span className="cmp__val mono">{v === null ? "—" : `${Math.round(v * 100)}%`}</span>
    </div>
  );
}

function OutOfSupport({ r }: { r: ScenarioResult }) {
  const off = r.changed_inputs.filter((c) => !c.in_support);
  return (
    <div className="wi-oos">
      <p className="wi-result__title">No estimate: this scenario leaves the range the model was trained on.</p>
      <p className="small secondary">
        Estimates are only reported where every changed input stays within the 1st–99th percentile of the training meals.
        Beyond that the model would be extrapolating.
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

export function WhatIf({ state }: { state: TwinState }) {
  const meal = state.current_meal;
  const scored = state.risk.status === "scored" && meal !== null && state.risk.probability !== null;
  const mutation = useWhatIf(state.patient_id);
  const [deltas, setDeltas] = useState<Deltas>({});
  const [lastLever, setLastLever] = useState<Lever | null>(null);
  const [waiting, setWaiting] = useState(false); // between an input change and its request
  const [result, setResult] = useState<ScenarioResult | null>(null); // the last answer, kept while recalculating
  const [error, setError] = useState<unknown>(null);
  const [settled, setSettled] = useState<string | null>(null); // scenario_id whose transition has settled
  const timer = useRef<number | undefined>(undefined);
  const seq = useRef(0);
  const quickRaf = useRef(0);

  const activity = state.current_physiology.active_min_3h;
  const levers = useMemo(() => LEVERS.filter((l) => l.key !== "active_min_3h" || activity !== null), [activity]);
  const baseOf = (k: Lever): number => (k === "active_min_3h" ? (activity ?? 0) : ((meal?.[k] as number | null | undefined) ?? 0));

  // A new moment resets the scenario.
  useEffect(() => {
    cancelAnimationFrame(quickRaf.current);
    setDeltas({});
    setResult(null);
    setError(null);
    setLastLever(null);
    mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.state_id]);

  const changes = Object.fromEntries(Object.entries(deltas).filter(([, v]) => v !== 0)) as Deltas;
  const key = JSON.stringify(changes);
  const nothing = Object.keys(changes).length === 0;

  // input change -> short pause -> run (validation and support checks happen on the server)
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!scored) return;
    if (nothing) {
      seq.current++; // any answer still in flight is now stale
      setWaiting(false);
      setResult(null);
      setError(null);
      return;
    }
    setWaiting(true);
    timer.current = window.setTimeout(() => {
      const n = ++seq.current;
      setWaiting(false);
      mutation.mutate(
        { asOf: state.as_of, mealId: meal?.meal_id ?? null, changes },
        {
          onSuccess: (r) => {
            if (n !== seq.current) return;
            setResult(r);
            setError(null);
          },
          onError: (e) => {
            if (n !== seq.current) return;
            setError(e);
          },
        },
      );
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, scored, state.as_of]);

  // the delta and the support/uncertainty settle in after the probability has mostly moved
  useEffect(() => {
    if (!result) return;
    if (prefersReducedMotion()) {
      setSettled(result.scenario_id);
      return;
    }
    const t = window.setTimeout(() => setSettled(result.scenario_id), SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [result]);
  useEffect(() => () => cancelAnimationFrame(quickRaf.current), []);

  const threshold = state.risk.threshold ?? 0.5;
  const baseline = result?.baseline_probability ?? state.risk.probability ?? 0;
  const oos = result?.status === "out_of_support";
  // the scenario starts AT the baseline and moves from wherever it is to each new answer
  const target = nothing || !result ? baseline : oos ? null : result.scenario_probability;
  const shownPct = useAnimatedNumber(target === null ? null : target * 100, MORPH_MS);
  const shown = shownPct === null ? null : shownPct / 100;
  const calculating = waiting || mutation.isPending;
  const done = Boolean(result && settled === result.scenario_id && !calculating && !nothing);

  const setLever = (k: Lever, v: number) => {
    cancelAnimationFrame(quickRaf.current);
    setLastLever(k);
    setDeltas((d) => ({ ...d, [k]: v }));
  };
  // a quick scenario moves its slider there (visibly, unless motion is reduced), then runs as usual
  const runQuick = (k: Lever, to: number) => {
    cancelAnimationFrame(quickRaf.current);
    setLastLever(k);
    const lever = LEVERS.find((l) => l.key === k)!;
    const from = deltas[k] ?? 0;
    if (prefersReducedMotion() || from === to) {
      setDeltas((d) => ({ ...d, [k]: to }));
      return;
    }
    const began = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - began) / MOTION.emphasis);
      const v = Math.round((from + (to - from) * easeOut(p)) / lever.step) * lever.step;
      setDeltas((d) => ({ ...d, [k]: p < 1 ? v : to }));
      if (p < 1) quickRaf.current = requestAnimationFrame(tick);
    };
    quickRaf.current = requestAnimationFrame(tick);
  };

  if (!scored) {
    return (
      <EmptyState icon="sliders" title="What-if needs a scored meal">
        Scenarios change the macros of the meal the twin is predicting. Choose a moment with a scored meal (above) to explore
        one.
      </EmptyState>
    );
  }

  const disabled = isApiError(mutation.error, "MODEL_UNAVAILABLE") || isApiError(error, "MODEL_UNAVAILABLE");
  const rejected = error && !disabled ? error : null;
  const rel = !nothing && result && !oos && result.scenario_probability !== null ? thresholdRelation(baseline, result.scenario_probability, threshold) : null;
  const scenTone = shown === null ? "neutral" : riskView("scored", shown, threshold).tone;
  const baseTone = riskView("scored", baseline, threshold).tone;
  const offFeatures = new Set(oos ? result!.changed_inputs.filter((c) => !c.in_support).map((c) => c.feature) : []);
  const changedList = levers.filter((l) => (changes[l.key] ?? 0) !== 0);
  const d = result?.risk_delta ?? 0;
  const dir = d > 0.0005 ? "up" : d < -0.0005 ? "down" : "flat";
  const quick = QUICK.filter((q) => levers.some((l) => l.key === q.lever));
  // the input the story is about: the lever moved last (or the first one still changed)
  const focusLever = levers.find((l) => l.key === lastLever && (changes[l.key] ?? 0) !== 0) ?? changedList[0] ?? null;
  const SHORT: Record<Lever, string> = { carbs_g: "g carbs", fiber_g: "g fiber", protein_g: "g protein", fat_g: "g fat", active_min_3h: "active min" };
  const short = (k: Lever) => SHORT[k];

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
          <div className="wi-quick" role="group" aria-label="Quick scenarios">
            <span className="wi-quick__k">Try</span>
            {quick.map((q) => {
              const invalid = baseOf(q.lever) + q.delta < 0;
              const on = deltas[q.lever] === q.delta;
              return (
                <button
                  key={q.label}
                  type="button"
                  className={cx("wi-chip", on && "is-on")}
                  aria-pressed={on}
                  disabled={invalid}
                  title={invalid ? "Would make the logged amount negative" : undefined}
                  onClick={() => runQuick(q.lever, on ? 0 : q.delta)}
                >
                  {q.label}
                </button>
              );
            })}
          </div>
          {levers.map((l) => (
            <LeverRow
              key={l.key}
              lever={l}
              base={baseOf(l.key)}
              delta={deltas[l.key] ?? 0}
              calculating={calculating && lastLever === l.key}
              outOfSupport={offFeatures.has(l.key) && !calculating}
              onChange={(v) => setLever(l.key, v)}
            />
          ))}
          {activity === null && (
            <p className="xsmall muted">Pre-meal activity is not available: this person&rsquo;s wearable does not record METs.</p>
          )}
          <p className="xsmall muted">
            Calories follow macro changes automatically. Post-meal activity cannot be simulated: the model has no post-meal
            inputs.
          </p>
          <div className="row">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                cancelAnimationFrame(quickRaf.current);
                setDeltas({});
              }}
              disabled={nothing}
            >
              <Icon name="rotate" size={14} /> Reset
            </Button>
          </div>
        </fieldset>

        <div className="whatif__out">
          {disabled ? (
            <EmptyState icon="shield" title="What-if is disabled on this server" tone="notice">
              The active model has no training-support profile, so scenarios cannot be checked against the range it was trained
              on. An admin can build one with <code>make support-profile</code>.
            </EmptyState>
          ) : (
            <div className={cx("wi", calculating && "is-calculating", oos && !calculating && "is-oos", nothing && "is-idle")}>
              {/* the comparison never unmounts: baseline stays, the scenario moves from it */}
              <div className="wi-dials">
                <div className="wi-side">
                  <span className="wi-side__k">As logged</span>
                  <RiskDial probability={baseline} threshold={threshold} tone={baseTone} size={96} label={`As logged: ${fmtPct(baseline)} estimated probability, alert threshold ${fmtPct(threshold)}.`} />
                  <span className="wi-side__in mono">{focusLever ? `${fmtNum(baseOf(focusLever.key))} ${short(focusLever.key)}` : "\u00a0"}</span>
                </div>
                <div className={cx("wi-link", !nothing && `is-${dir}`)} aria-hidden="true">
                  <span className="wi-link__line" />
                  <Icon name="arrowRight" size={14} />
                  {done && !oos && (
                    <span key={result!.scenario_id} className={cx("wi-link__delta mono", `is-${dir}`)}>
                      {fmtPp(d)}
                    </span>
                  )}
                </div>
                <div className="wi-side wi-side--scenario">
                  <span className="wi-side__k">{nothing ? "Scenario (unchanged)" : "Scenario"}</span>
                  <RiskDial
                    probability={nothing ? baseline : target}
                    threshold={threshold}
                    tone={oos && !calculating ? "neutral" : scenTone}
                    size={96}
                    label={oos ? "Scenario: no estimate, outside training support." : `Scenario: ${fmtPct(target)} estimated probability.`}
                  />
                  <span className="wi-side__in mono">
                    {focusLever ? `${fmtNum(baseOf(focusLever.key) + (changes[focusLever.key] ?? 0))} ${short(focusLever.key)}` : "\u00a0"}
                  </span>
                </div>
              </div>

              <div className="wi-bars">
                <Bar label="As logged" value={baseline} threshold={threshold} />
                <Bar label="Scenario" value={oos && !calculating ? null : shown} threshold={threshold} from={nothing ? undefined : baseline} model empty={oos && !calculating} />
              </div>

              {/* what changed, in the lever's own words: the input side of the story */}
              <div className="wi-inputs">
                {nothing ? (
                  <p className="small secondary">Move a slider or try a quick scenario to see how the model&rsquo;s estimate for this meal would change.</p>
                ) : (
                  <ul className="wi-changes">
                    {changedList.map((l) => (
                      <li key={l.key} className={cx(offFeatures.has(l.key) && !calculating && "is-oos")}>
                        <span>{l.label}</span>{" "}
                        <span className="mono">
                          {fmtNum(baseOf(l.key))} → {fmtNum(baseOf(l.key) + (changes[l.key] ?? 0))} {l.unit}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* the outcome of the transition, once it has settled (space kept so nothing jumps) */}
              <div className={cx("wi-foot", nothing && "is-empty")}>
              {rejected ? (
                <div className="wi-note wi-note--warn" role="status">
                  <Icon name="alert" size={14} />
                  {isApiError(rejected, "WHAT_IF_UNSUPPORTED") || isApiError(rejected, "VALIDATION_ERROR")
                    ? (rejected as Error).message
                    : "The server could not evaluate this scenario. Try a smaller change."}
                </div>
              ) : oos && !calculating ? (
                <OutOfSupport r={result!} />
              ) : done && rel ? (
                <div key={result!.scenario_id} className="wi-settle">
                  <p className={cx("wi-threshold", `is-${rel.move}`)}>
                    <span className="wi-threshold__mark" aria-hidden="true" />
                    {rel.text}
                    <span className="muted">
                      {" "}
                      · {rel.gapPp.toFixed(1)} pp {rel.above ? "above" : "below"} the {fmtPct(threshold)} threshold (was {rel.wasPp.toFixed(1)} pp {baseline >= threshold ? "above" : "below"})
                    </span>
                  </p>
                  <div className="row">
                    <Tag tone="success" icon="check">
                      Within training support
                    </Tag>
                    {result!.uncertainty && (
                      <Tag tone={UNCERTAINTY_TONE[result!.uncertainty.level]}>{UNCERTAINTY_LABEL[result!.uncertainty.level]}</Tag>
                    )}
                  </div>
                  <p className="xsmall muted">Held fixed: {result!.held_fixed}.</p>
                </div>
              ) : !nothing ? (
                <p className="wi-note small secondary">{calculating ? "Recalculating the model estimate…" : " "}</p>
              ) : null}
              </div>

              {/* announced once per answer, not on every animation frame */}
              <p className="sr-only" aria-live="polite">
                {calculating
                  ? ""
                  : rejected
                    ? "Scenario not accepted."
                    : oos
                      ? "No estimate: the scenario leaves the model's training support."
                      : result && !nothing && result.scenario_probability !== null
                        ? scenarioSummary(baseline, result.scenario_probability, threshold)
                        : ""}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
