"use client";

import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/ui/StateMessage";
import { Origin } from "@/components/ui/Tag";
import type { TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtNum, fmtPct, fmtSigned } from "@/lib/format";
import { PHASE_HELP, PHASE_LABEL, PHASES } from "@/lib/risk";
import { fmtClock, fmtDay, parseNaive } from "@/lib/time";

/** The PERSONALIZED weight threshold, read from the engine's own lifecycle text (twin.v1). */
function weightThreshold(reason: string): number {
  const m = /(?:>=|≥)\s*([0-9.]+)/.exec(reason);
  const v = m ? Number(m[1]) : NaN;
  return Number.isFinite(v) && v > 0 && v < 1 ? v : 0.5;
}

export function PersonalResponse({ state }: { state: TwinState }) {
  const { lifecycle, personal_response: pr } = state;
  const current = PHASES.indexOf(lifecycle.phase);
  const need = weightThreshold(lifecycle.reason);
  const weight = pr?.personal_weight ?? lifecycle.personal_weight ?? 0;

  return (
    <div className="personal">
      <ol className="lifecycle" aria-label="Twin lifecycle">
        {PHASES.map((p, i) => (
          <li
            key={p}
            className={cx("lifecycle__step", i < current && "is-done", i === current && "is-current")}
            aria-current={i === current ? "step" : undefined}
          >
            <span className="lifecycle__marker" aria-hidden="true">
              {i < current ? <Icon name="check" size={12} /> : i + 1}
            </span>
            <span className="lifecycle__name">{PHASE_LABEL[p]}</span>
            <span className="lifecycle__help">{PHASE_HELP[p]}</span>
          </li>
        ))}
      </ol>
      <p className="personal__reason small secondary">
        <strong>{PHASE_LABEL[lifecycle.phase]}:</strong> {lifecycle.reason}
        {lifecycle.next_phase_requires && <> Next: {lifecycle.next_phase_requires}.</>}
      </p>

      {!pr ? (
        <EmptyState icon="info" title="Personal response unavailable">
          The personal estimates need the population prior stored with an active model.
        </EmptyState>
      ) : (
        <div className="personal__grid">
          <div className="personal__evidence">
            <div className="personal__label">
              Evidence strength <Origin kind="model" />
            </div>
            <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(weight * 100)} aria-label={`Personal evidence weight ${fmtPct(weight)}; personalized at ${fmtPct(need)} or more`}>
              <div className="meter__fill" style={{ width: `${weight * 100}%` }} />
              <div className="meter__mark" style={{ left: `${need * 100}%` }}>
                <span>personalized at {fmtPct(need)}</span>
              </div>
            </div>
            <p className="xsmall secondary">
              <span className="mono">{fmtPct(weight)}</span> of the personal estimate comes from this person&rsquo;s own{" "}
              {pr.closed_usable_meals} closed meal{pr.closed_usable_meals === 1 ? "" : "s"}; the rest from the population prior (
              {pr.prior_fitted_on_people} people, {pr.prior_fitted_on_meals} meals).
            </p>
          </div>

          <dl className="personal__stats">
            <div>
              <dt>Closed meals</dt>
              <dd className="mono">{pr.closed_usable_meals}</dd>
            </div>
            <div>
              <dt>Went above 180</dt>
              <dd className="mono">{pr.closed_positive_meals}</dd>
            </div>
            <div>
              <dt>Rise vs population</dt>
              <dd className="mono">{fmtSigned(pr.rise_offset_mgdl, 1)} mg/dL</dd>
            </div>
          </dl>

          <div className="rates" aria-label="Personal versus population response rate">
            <div className="rates__row">
              <span className="rates__name">This person</span>
              <span className="rates__bar">
                <span className="rates__fill rates__fill--model" style={{ width: `${pr.p_personal * 100}%` }} />
              </span>
              <span className="mono rates__val">{fmtPct(pr.p_personal)}</span>
            </div>
            <div className="rates__row">
              <span className="rates__name">Population</span>
              <span className="rates__bar">
                <span className="rates__fill" style={{ width: `${pr.population_rate * 100}%` }} />
              </span>
              <span className="mono rates__val">{fmtPct(pr.population_rate)}</span>
            </div>
            <p className="xsmall muted">Shrunk rate of meals that went above 180 mg/dL (beta-binomial, closed windows only).</p>
          </div>

          {state.recent_history.recent_closed_meals.length > 0 && (
            <div className="closed">
              <div className="personal__label">
                Latest closed meals <Origin kind="observed" />
              </div>
              <ul className="closed__list">
                {state.recent_history.recent_closed_meals.map((m) => {
                  const t = parseNaive(m.started_at);
                  return (
                    <li key={m.meal_id} className="closed__item">
                      <span className={cx("closed__dot", m.label === 1 && "is-pos", m.label === 0 && "is-neg")} aria-hidden="true" />
                      <span className="mono">
                        {fmtDay(t)} {fmtClock(t)}
                      </span>
                      <span className="secondary">
                        {m.label === 1 ? "above 180" : m.label === 0 ? "stayed ≤ 180" : "not usable"}
                      </span>
                      <span className="mono muted">{m.rise_native_mgdl === null ? "" : `rise ${fmtNum(m.rise_native_mgdl)}`}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
