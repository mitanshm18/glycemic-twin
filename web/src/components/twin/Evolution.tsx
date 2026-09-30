"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { fetchTwin, keys, useStateDiff, useStateHistory } from "@/lib/api/queries";
import type { MealOutcome, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtPct, tidyNumbers } from "@/lib/format";
import { PHASE_LABEL, PHASE_TONE } from "@/lib/risk";
import { fmtClock, fmtDateTime, fmtDay, parseNaive } from "@/lib/time";
import { linear } from "@/lib/timeline";
import { useWidth } from "@/lib/useSize";

interface TracePoint {
  mealId: string;
  t: number;
  state: TwinState;
}

/* ------------------------------------------------------------------ learning curve */

function Curve({ points, currentId, onPick }: { points: TracePoint[]; currentId: string; onPick: (p: TracePoint) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const h = 220;
  const m = { top: 14, right: 14, bottom: 26, left: 40 };
  const w = Math.max(280, width);
  const x = linear([0, Math.max(1, points.length - 1)], [m.left, w - m.right]);
  const y = linear([0, 1], [h - m.bottom, m.top]);
  const path = (get: (p: TracePoint) => number | null) =>
    points
      .map((p, i) => {
        const v = get(p);
        return v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      })
      .filter(Boolean)
      .map((s, i) => `${i ? "L" : "M"}${s}`)
      .join("");
  const pop = points[0]?.state.personal_response?.population_rate ?? null;
  const phaseStart = (ph: string) => points.findIndex((p) => p.state.lifecycle.phase === ph);
  const warm = phaseStart("WARMING");
  const pers = phaseStart("PERSONALIZED");
  return (
    <div ref={ref} className="curve">
      <svg width={w} height={h} role="img" aria-label={`Learning curve across ${points.length} meals: personal evidence weight rises from ${fmtPct(points[0]?.state.personal_response?.personal_weight)} to ${fmtPct(points.at(-1)?.state.personal_response?.personal_weight)}.`}>
        {pers >= 0 && <rect className="curve__phase curve__phase--pers" x={x(pers)} y={m.top} width={w - m.right - x(pers)} height={h - m.top - m.bottom} />}
        {warm >= 0 && <rect className="curve__phase curve__phase--warm" x={x(warm)} y={m.top} width={(pers >= 0 ? x(pers) : w - m.right) - x(warm)} height={h - m.top - m.bottom} />}
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line className="tl__grid" x1={m.left} x2={w - m.right} y1={y(v)} y2={y(v)} />
            <text className="tl__ylabel" x={m.left - 6} y={y(v) + 3.5} textAnchor="end">
              {v * 100}%
            </text>
          </g>
        ))}
        {pop !== null && <line className="curve__pop" x1={m.left} x2={w - m.right} y1={y(pop)} y2={y(pop)} />}
        <path className="curve__weight" d={path((p) => p.state.personal_response?.personal_weight ?? null)} />
        <path className="curve__rate" d={path((p) => p.state.personal_response?.p_personal ?? null)} />
        {points.map((p, i) => {
          const prob = p.state.risk.probability;
          return (
            <g key={p.mealId} className={cx("curve__pt", p.state.state_id === currentId && "is-current")} onClick={() => onPick(p)}>
              <title>{`${fmtDay(p.t)} ${fmtClock(p.t)} · risk ${fmtPct(prob)} · ${PHASE_LABEL[p.state.lifecycle.phase]}`}</title>
              {prob !== null && <circle className="curve__risk" cx={x(i)} cy={y(prob)} r={3} />}
              <rect x={x(i) - 6} y={m.top} width={12} height={h - m.top - m.bottom} fill="transparent" />
            </g>
          );
        })}
        <text className="tl__xlabel" x={m.left} y={h - 8}>
          first meal
        </text>
        <text className="tl__xlabel" x={w - m.right} y={h - 8} textAnchor="end">
          meal {points.length}
        </text>
      </svg>
      <div className="curve__legend xsmall">
        <span><span className="curve__key curve__key--weight" /> personal evidence weight</span>
        <span><span className="curve__key curve__key--rate" /> personal response rate</span>
        <span><span className="curve__key curve__key--pop" /> population rate</span>
        <span><span className="curve__key curve__key--risk" /> estimated risk at each meal</span>
      </div>
    </div>
  );
}

function Tracer({ patientId, outcomes, current, onSelect }: { patientId: number; outcomes: MealOutcome[]; current: TwinState; onSelect: (mealId: string, asOf: string) => void }) {
  const qc = useQueryClient();
  const meals = useMemo(() => outcomes.filter((o) => o.eligible).sort((a, b) => a.started_at.localeCompare(b.started_at)), [outcomes]);
  const [points, setPoints] = useState<TracePoint[] | null>(null);
  const [progress, setProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cancel = useRef(false);

  const run = async () => {
    setRunning(true);
    setError(null);
    cancel.current = false;
    const out: TracePoint[] = [];
    try {
      for (const [i, o] of meals.entries()) {
        if (cancel.current) break;
        const state = await qc.fetchQuery({
          queryKey: keys.twin(patientId, o.started_at, o.meal_id),
          queryFn: () => fetchTwin(patientId, o.started_at, o.meal_id),
          staleTime: Number.POSITIVE_INFINITY,
        });
        out.push({ mealId: o.meal_id, t: parseNaive(o.started_at), state });
        setProgress((i + 1) / meals.length);
        setPoints([...out]);
      }
      void qc.invalidateQueries({ queryKey: keys.history(patientId) });
    } catch (e) {
      setError(e);
    } finally {
      setRunning(false);
    }
  };

  if (meals.length === 0) {
    return <EmptyState title="No scorable meals to trace">This participant has no eligible meals.</EmptyState>;
  }
  return (
    <div className="stack">
      <div className="row">
        {!running ? (
          <Button size="sm" onClick={run}>
            <Icon name="play" size={13} />
            {points ? "Trace again" : `Trace the twin across ${meals.length} meals`}
          </Button>
        ) : (
          <Button size="sm" onClick={() => (cancel.current = true)}>
            <Icon name="x" size={13} /> Stop
          </Button>
        )}
        {running && (
          <div className="trace-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)} aria-label="Tracing meals">
            <div className="bar">
              <div className="bar__fill" style={{ width: `${progress * 100}%` }} />
            </div>
            <span className="xsmall muted mono">
              {Math.round(progress * meals.length)}/{meals.length}
            </span>
          </div>
        )}
        {!points && !running && (
          <span className="xsmall muted">Rebuilds the twin at the start of every scorable meal, in time order, using only what was known then.</span>
        )}
      </div>
      {error ? <ErrorState error={error} what="the learning curve" onRetry={run} /> : null}
      {points && points.length > 1 && (
        <Curve points={points} currentId={current.state_id} onPick={(p) => onSelect(p.mealId, p.state.as_of)} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ snapshot diff */

const HIDDEN = [/^risk\.model_inputs\./, /^provenance\.config_sha256/, /^disclaimer$/, /^schema_version$/];
const LABELS: Array<[RegExp, string]> = [
  [/^risk\.probability$/, "Estimated probability"],
  [/^risk\.status$/, "Risk status"],
  [/^lifecycle\.phase$/, "Lifecycle phase"],
  [/^lifecycle\.closed_usable_meals$/, "Closed meals learned"],
  [/^personal_response\.p_personal$/, "Personal response rate"],
  [/^personal_response\.personal_weight$/, "Personal evidence weight"],
  [/^personal_response\.rise_offset_mgdl$/, "Personal rise offset"],
  [/^current_physiology\.glucose_mgdl$/, "Current glucose"],
  [/^current_meal\.meal_id$/, "Current meal"],
  [/^as_of$/, "Moment"],
];

function label(path: string): string {
  return LABELS.find(([re]) => re.test(path))?.[1] ?? path.replaceAll("_", " ").replaceAll(".", " › ");
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 1 ? 3 : 1);
  if (typeof v === "string") {
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v)) return fmtDateTime(parseNaive(v.slice(0, 19)));
    return v.length > 28 ? `${v.slice(0, 26)}…` : v;
  }
  return JSON.stringify(v);
}

function Diff({ patientId, current }: { patientId: number; current: TwinState }) {
  const history = useStateHistory(patientId);
  const others = (history.data ?? []).filter((s) => s.state_id !== current.state_id);
  const [picked, setPicked] = useState<string | null>(null);
  const from = picked ?? others.find((s) => s.as_of < current.as_of)?.state_id ?? others[0]?.state_id ?? null;
  const diff = useStateDiff(from, current.state_id);
  const [showAll, setShowAll] = useState(false);

  if (history.isPending) return <Loading label="Loading snapshots"><Skeleton h={120} /></Loading>;
  if (history.isError) return <ErrorState error={history.error} what="the snapshot history" onRetry={() => void history.refetch()} />;
  if (others.length === 0) {
    return (
      <EmptyState icon="history" title="Only one snapshot so far">
        Every moment you open creates an immutable snapshot. Step to another meal, or trace the twin above, to compare
        what changed.
      </EmptyState>
    );
  }
  const changes = (diff.data?.changes ?? []).filter((c) => !HIDDEN.some((re) => re.test(c.path)));
  const key = changes.filter((c) => LABELS.some(([re]) => re.test(c.path)));
  const list = showAll ? changes : key;
  return (
    <div className="diff">
      <label className="field diff__pick">
        <span className="field__label">Compare the current state with</span>
        <select className="select" value={from ?? ""} onChange={(e) => setPicked(e.target.value)}>
          {others.map((s) => (
            <option key={s.state_id} value={s.state_id}>
              {fmtDateTime(parseNaive(s.as_of))} · {PHASE_LABEL[s.lifecycle_phase]} · risk {fmtPct(s.probability)}
            </option>
          ))}
        </select>
      </label>
      {diff.isPending ? (
        <Skeleton h={120} />
      ) : diff.isError ? (
        <ErrorState error={diff.error} what="the comparison" onRetry={() => void diff.refetch()} />
      ) : (
        <div className="diff__body" key={`${from}-${current.state_id}`}>
          <ul className="diff__why">
            {diff.data.explanations.map((e) => (
              <li key={e} className="changed">
                <Icon name="arrowRight" size={12} /> {tidyNumbers(e)}
              </li>
            ))}
            {diff.data.explanations.length === 0 && <li className="muted">No meaningful change between these snapshots.</li>}
          </ul>
          <table className="table diff__table">
            <caption className="sr-only">Fields that changed between the two snapshots</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col" className="right">Before</th>
                <th scope="col" className="right">After</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c, i) => (
                <tr key={c.path} className="changed" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
                  <td>{label(c.path)}</td>
                  <td className="right mono muted">{show(c.before)}</td>
                  <td className="right mono">{show(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {changes.length > key.length && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((s) => !s)} aria-expanded={showAll}>
              <Icon name={showAll ? "chevronDown" : "chevronRight"} size={14} />
              {showAll ? "Key fields only" : `All ${changes.length} changed fields`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}


export function Evolution(props: { patientId: number; outcomes: MealOutcome[]; current: TwinState; onSelect: (mealId: string, asOf: string) => void }) {
  return (
    <div className="evolution">
      <div className="evolution__block">
        <h3 className="evolution__title">
          Learning curve <Tag tone="quiet">one snapshot per meal</Tag>
        </h3>
        <Tracer {...props} />
      </div>
      <div className="evolution__block">
        <h3 className="evolution__title">What changed</h3>
        <Diff patientId={props.patientId} current={props.current} />
      </div>
      <p className="xsmall muted">
        Current: <span className="mono">{fmtDateTime(parseNaive(props.current.as_of))}</span> ·{" "}
        <Tag tone={PHASE_TONE[props.current.lifecycle.phase]}>{PHASE_LABEL[props.current.lifecycle.phase]}</Tag>
      </p>
    </div>
  );
}
