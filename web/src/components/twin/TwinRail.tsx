"use client";

import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { Tag } from "@/components/ui/Tag";
import { Tip } from "@/components/ui/Tip";
import { useStateHistory } from "@/lib/api/queries";
import type { Meal, MealOutcome, Phase, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { PHASE_HELP, PHASE_LABEL, PHASE_TONE } from "@/lib/risk";
import { DAY, fmtClock, fmtDay, parseNaive, type Millis } from "@/lib/time";

export interface RailMoment {
  asOf: string | null;
  mealId: string | null;
}

interface Props {
  patientId: number;
  meals: Meal[];
  outcomes: MealOutcome[];
  dataFrom: string | null;
  dataTo: string | null;
  /** the state being shown (may lag the requested moment while it loads) */
  state: TwinState | undefined;
  moment: RailMoment;
  onSelect: (m: RailMoment) => void;
  /** an action beside the rail's title (the replay entry point) */
  action?: ReactNode;
}

type Kind = "learned" | "seen" | "future";

/**
 * The patient's whole recording as one line of real meal times, with the twin's moment on it.
 * Left of the moment is what the twin can see; meals it has learned from (closed windows it used)
 * are filled, later meals are hollow: it has not seen them yet. Moving the moment is choosing a
 * meal: click, drag, or arrow keys. Snapshots already built are dotted underneath by phase.
 */
export function TwinRail({ patientId, meals, outcomes, dataFrom, dataTo, state, moment, onSelect, action }: Props) {
  const history = useStateHistory(patientId);
  const sorted = useMemo(() => [...meals].sort((a, b) => a.started_at.localeCompare(b.started_at)).map((m) => ({ m, t: parseNaive(m.started_at) })), [meals]);
  const eligible = useMemo(() => new Set(outcomes.filter((o) => o.eligible).map((o) => o.meal_id)), [outcomes]);
  const learned = useMemo(() => new Set(state?.provenance.closed_meal_ids_used ?? []), [state]);

  const t0 = dataFrom ? parseNaive(dataFrom) : (sorted[0]?.t ?? 0);
  const t1 = dataTo ? parseNaive(dataTo) : (sorted.at(-1)?.t ?? t0 + DAY);
  const pct = (t: Millis) => (t1 === t0 ? 0 : Math.max(0, Math.min(100, ((t - t0) / (t1 - t0)) * 100)));
  const asOf = state ? parseNaive(state.as_of) : moment.asOf ? parseNaive(moment.asOf) : t1;
  const idx = sorted.findIndex((s) => s.m.meal_id === moment.mealId);

  const days = useMemo(() => {
    const out: Millis[] = [];
    for (let d = Math.ceil(t0 / DAY) * DAY; d < t1; d += DAY) out.push(d);
    return out;
  }, [t0, t1]);

  const trackRef = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const dragging = useRef(false);
  const nearestAt = (clientX: number) => {
    const r = trackRef.current?.getBoundingClientRect();
    if (!r || sorted.length === 0) return null;
    const t = t0 + ((clientX - r.left) / r.width) * (t1 - t0);
    let best = 0;
    for (let i = 1; i < sorted.length; i++) if (Math.abs((sorted[i] as { t: number }).t - t) < Math.abs((sorted[best] as { t: number }).t - t)) best = i;
    return best;
  };
  const choose = (i: number) => {
    const s = sorted[i];
    if (s && s.m.meal_id !== moment.mealId) onSelect({ asOf: s.m.started_at, mealId: s.m.meal_id });
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    setPreview(nearestAt(e.clientX));
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "mouse" || dragging.current) setPreview(nearestAt(e.clientX));
  };
  const onUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    dragging.current = false;
    const i = nearestAt(e.clientX);
    if (i !== null) choose(i);
    if (e.pointerType !== "mouse") setPreview(null);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    // between meals (e.g. a replayed step), "next" and "previous" are the meals either side of it
    const seen = sorted.filter((m) => m.t <= asOf).length;
    const cur = idx >= 0 ? idx : moment.asOf ? seen - 0.5 : sorted.length;
    let next: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") next = Math.min(sorted.length - 1, Math.floor(cur + 1));
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = Math.max(0, Math.ceil(cur - 1));
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = sorted.length - 1;
    if (next === null) return;
    e.preventDefault();
    choose(next);
  };

  const kindOf = (id: string, t: Millis): Kind => (learned.has(id) ? "learned" : t <= asOf ? "seen" : "future");
  const describe = (i: number) => {
    const s = sorted[i];
    if (!s) return "";
    const k = kindOf(s.m.meal_id, s.t);
    return `${fmtDay(s.t)} ${fmtClock(s.t)} · ${s.m.meal_type ?? "meal"}${eligible.has(s.m.meal_id) ? "" : " (not scored)"}${
      k === "learned" ? " · learned from" : k === "future" ? " · after the twin's moment" : ""
    }`;
  };
  const current = idx >= 0 ? sorted[idx] : null;
  const pv = preview === null ? null : sorted[preview];
  const snapshots = (history.data ?? []).map((h) => ({ t: parseNaive(h.as_of), phase: h.lifecycle_phase as Phase, id: h.state_id }));

  return (
    <div className="rail">
      <div className="rail__head">
        <span className="rail__title">Twin timeline</span>
        <span className="rail__now">
          {state && (
            <Tip text={PHASE_HELP[state.lifecycle.phase]} focusable label={`${PHASE_LABEL[state.lifecycle.phase]}: what this phase means`}>
              <Tag tone={PHASE_TONE[state.lifecycle.phase]}>{PHASE_LABEL[state.lifecycle.phase]}</Tag>
            </Tip>
          )}
          <span className="mono">{current ? `${fmtDay(current.t)} ${fmtClock(current.t)}` : moment.asOf ? `${fmtDay(asOf)} ${fmtClock(asOf)}` : "Latest data"}</span>
          {current && <span className="secondary">{current.m.meal_type ?? "meal"}</span>}
        </span>
        {action && <span className="rail__action">{action}</span>}
        <span className="rail__legend xsmall" aria-hidden="true">
          <span><i className="rail__key rail__key--learned" /> learned from</span>
          <span><i className="rail__key rail__key--seen" /> seen, window open</span>
          <span><i className="rail__key rail__key--future" /> not yet seen</span>
        </span>
      </div>

      <div
        ref={trackRef}
        className={cx("rail__track", preview !== null && "is-previewing")}
        role="slider"
        tabIndex={0}
        aria-label="Twin moment: the meal the twin is viewed at"
        aria-valuemin={1}
        aria-valuemax={sorted.length}
        aria-valuenow={idx >= 0 ? idx + 1 : sorted.length}
        aria-valuetext={
          idx >= 0 ? `Meal ${idx + 1} of ${sorted.length}: ${describe(idx)}` : moment.asOf ? `${fmtDay(asOf)} ${fmtClock(asOf)}, between meals` : "Latest data, end of recording"
        }
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={() => ((dragging.current = false), setPreview(null))}
        onPointerLeave={(e) => e.pointerType === "mouse" && !dragging.current && setPreview(null)}
        onKeyDown={onKey}
      >
        <span className="rail__line" aria-hidden="true" />
        <span className="rail__past" style={{ width: `${pct(asOf)}%` }} aria-hidden="true" />
        {days.map((d) => (
          <span key={d} className="rail__day" style={{ left: `${pct(d)}%` }} aria-hidden="true">
            <span className="rail__day-label">{fmtDay(d).replace(/ \w+$/, "")}</span>
          </span>
        ))}
        {sorted.map((s, i) => (
          <span
            key={s.m.meal_id}
            className={cx("rail__meal", `rail__meal--${kindOf(s.m.meal_id, s.t)}`, !eligible.has(s.m.meal_id) && "is-unscored", i === preview && "is-preview", i === idx && "is-current")}
            style={{ left: `${pct(s.t)}%` }}
            aria-hidden="true"
          />
        ))}
        {snapshots.map((h) => (
          <span key={h.id} className={cx("rail__snap", `rail__snap--${h.phase.toLowerCase()}`)} style={{ left: `${pct(h.t)}%` }} aria-hidden="true" />
        ))}
        <span className="rail__knob" style={{ left: `${pct(asOf)}%` }} aria-hidden="true" />
        {pv && (
          <span className="rail__preview" style={{ left: `${Math.min(88, Math.max(12, pct(pv.t)))}%` }} aria-hidden="true">
            {describe(preview as number)}
          </span>
        )}
      </div>
      <div className="rail__ends xsmall mono" aria-hidden="true">
        <span>{fmtDay(t0)}</span>
        <span className="rail__snap-key">
          <i className="rail__snap rail__snap--warming" /> <i className="rail__snap rail__snap--personalized" /> snapshots built, by phase
        </span>
        <span>{fmtDay(t1)}</span>
      </div>
    </div>
  );
}
