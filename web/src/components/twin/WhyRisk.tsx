"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { useExplanation } from "@/lib/api/queries";
import type { Explanation, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { evidenceFor, evidenceText } from "@/lib/evidence";
import { featureInfo, fmtFeature, GROUP_LABEL } from "@/lib/features";
import { fmtNum, fmtPct, fmtSigned } from "@/lib/format";
import { goToSection, useTwinFocus } from "@/lib/twinFocus";

const TOP = 6;

function Row({ name, value, contribution, max, pulse }: { name: string; value: number | null; contribution: number; max: number; pulse: number | null }) {
  const info = featureInfo(name);
  const up = contribution > 0;
  const share = max > 0 ? Math.abs(contribution) / max : 0;
  const focus = useTwinFocus();
  const ev = evidenceFor(name);
  const evId = useId();
  const ref = useRef<HTMLLIElement>(null);
  const active = focus.evidence?.feature === name;
  // led here from the dial: take focus quietly so the keyboard continues from this driver
  useEffect(() => {
    if (pulse !== null) ref.current?.focus({ preventScroll: true });
  }, [pulse]);
  const enter = () => ev && focus.showEvidence(ev);
  const leave = () => ev && focus.showEvidence(null);
  return (
    <li
      ref={ref}
      className={cx("driver", ev && "driver--linked", active && "is-active", pulse !== null && "is-pulsed")}
      tabIndex={ev ? 0 : -1}
      aria-describedby={ev ? evId : undefined}
      onPointerEnter={(e) => e.pointerType === "mouse" && enter()}
      onPointerLeave={(e) => e.pointerType === "mouse" && leave()}
      onFocus={(e) => e.target === e.currentTarget && enter()}
      onBlur={(e) => e.target === e.currentTarget && leave()}
    >
      {pulse !== null && <span key={pulse} className="driver__pulse" aria-hidden="true" />}
      <div className="driver__text">
        <div className="driver__name">
          {info.label}
          <span className="driver__group">{GROUP_LABEL[info.group]}</span>
        </div>
        <div className="driver__value mono">{fmtFeature(name, value)}</div>
        <p className="driver__plain">
          {value === null
            ? `Missing for this meal (${info.what}); the model's learned handling of missing values ${up ? "raised" : "lowered"} the estimate.`
            : `${capitalize(info.what)}. Associated with a ${up ? "higher" : "lower"} estimate for this meal.`}
        </p>
        {ev && (
          <p id={evId} className="driver__evidence">
            {evidenceText(ev)}
            {(ev.kind === "lookback" || ev.kind === "prior-meals" || ev.kind === "personal") && (
              <button
                type="button"
                className="driver__show"
                onClick={() => {
                  focus.showEvidence(ev, true);
                  goToSection(ev.kind === "personal" ? "personal" : "timeline");
                }}
              >
                {ev.kind === "personal" ? "See personal response" : "Show on timeline"} <Icon name="arrowRight" size={11} />
              </button>
            )}
          </p>
        )}
      </div>
      <div className="driver__bar" aria-hidden="true">
        <span className="driver__axis" />
        <span
          className={cx("driver__fill", up ? "driver__fill--up" : "driver__fill--down")}
          style={{ width: `${Math.max(2, share * 50)}%` }}
        />
      </div>
      <div className={cx("driver__dir", up ? "driver__dir--up" : "driver__dir--down")}>
        <Icon name={up ? "arrowUp" : "arrowDown"} size={13} />
        <span>{up ? "raises" : "lowers"}</span>
        <span className="mono driver__contrib">{fmtSigned(contribution, 2)}</span>
      </div>
    </li>
  );
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Body({ ex }: { ex: Explanation }) {
  const [all, setAll] = useState(false);
  const { pulse } = useTwinFocus();
  const max = useMemo(() => Math.max(...ex.contributions.map((c) => Math.abs(c.contribution)), 0), [ex]);
  const shown = all ? ex.contributions : ex.contributions.slice(0, TOP);
  const rest = ex.contributions.slice(TOP);
  const restUp = rest.filter((c) => c.contribution > 0).reduce((s, c) => s + c.contribution, 0);
  const restDown = rest.filter((c) => c.contribution < 0).reduce((s, c) => s + c.contribution, 0);
  return (
    <div className="why">
      <div className="why__legend">
        <span className="why__legend-item">
          <span className="why__swatch why__swatch--down" /> lowers the estimate
        </span>
        <span className="why__legend-item">
          <span className="why__swatch why__swatch--up" /> raises the estimate
        </span>
        <span className="muted xsmall">bar length = share of the largest contribution</span>
      </div>
      <ol className="drivers" aria-label={all ? "All model inputs by contribution" : `Top ${TOP} model inputs by contribution`}>
        {shown.map((c) => (
          <Row key={c.feature} name={c.feature} value={c.value} contribution={c.contribution} max={max} pulse={pulse?.feature === c.feature ? pulse.n : null} />
        ))}
      </ol>
      {!all && rest.length > 0 && (
        <p className="why__rest xsmall secondary">
          The other {rest.length} inputs together add <span className="mono">{fmtSigned(restUp, 2)}</span> and{" "}
          <span className="mono">{fmtSigned(restDown, 2)}</span>.
        </p>
      )}
      <div className="row">
        <Button size="sm" variant="ghost" onClick={() => setAll((a) => !a)} aria-expanded={all}>
          <Icon name={all ? "chevronDown" : "chevronRight"} size={14} />
          {all ? `Show top ${TOP} only` : `Show all ${ex.contributions.length} inputs`}
        </Button>
      </div>
      <div className="why__math">
        <span>
          Model baseline <span className="mono">{fmtSigned(ex.base_value, 2)}</span>
        </span>
        <Icon name="arrowRight" size={12} />
        <span>
          + inputs <span className="mono">{fmtSigned(ex.raw_score - ex.base_value, 2)}</span>
        </span>
        <Icon name="arrowRight" size={12} />
        <span>
          raw score <span className="mono">{fmtNum(ex.raw_score, 2)}</span> log-odds
        </span>
        <Icon name="arrowRight" size={12} />
        <span>
          calibrated <span className="mono">{fmtPct(ex.probability)}</span>
        </span>
      </div>
      <p className="why__note xsmall muted">
        {ex.method === "tree_shap" ? "Exact TreeSHAP" : "Exact linear attribution"} on the served model. {ex.note}
      </p>
    </div>
  );
}

export function WhyRisk({ state }: { state: TwinState }) {
  const scored = state.risk.status === "scored";
  const q = useExplanation(state.state_id, scored);
  if (!scored) {
    return (
      <EmptyState icon="info" title="No prediction to explain at this moment">
        {state.risk.reason ?? "Choose a moment with a scored meal to see what the estimate rests on."}
      </EmptyState>
    );
  }
  if (q.isPending)
    return (
      <Loading label="Loading explanation">
        <div className="stack">
          {Array.from({ length: TOP }, (_, i) => (
            <Skeleton key={i} h={44} />
          ))}
        </div>
      </Loading>
    );
  if (q.isError) return <ErrorState error={q.error} what="the explanation" onRetry={() => void q.refetch()} />;
  return <Body ex={q.data} />;
}

export function WhyRiskAside() {
  return (
    <Tag tone="model" icon="info">
      Model association · not causal
    </Tag>
  );
}
