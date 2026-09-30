"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { PatientTabs } from "@/components/shell/PatientTabs";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Section } from "@/components/ui/Section";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Origin, Tag } from "@/components/ui/Tag";
import { CurrentState } from "@/components/twin/CurrentState";
import { Evolution } from "@/components/twin/Evolution";
import { GlucoseTimeline } from "@/components/twin/GlucoseTimeline";
import { PersonalResponse } from "@/components/twin/PersonalResponse";
import { Provenance } from "@/components/twin/Provenance";
import { WhatIf } from "@/components/twin/WhatIf";
import { WhyRisk, WhyRiskAside } from "@/components/twin/WhyRisk";
import { ReplayDock } from "@/components/twin/ReplayDock";
import { TwinRail } from "@/components/twin/TwinRail";
import { useCgm, useMealOutcomes, useMeals, usePatient, useStateDiff, useTwinState } from "@/lib/api/queries";
import type { Meal, MealOutcome, PatientDetail, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtPct, readableChange } from "@/lib/format";
import { MOTION, prefersReducedMotion } from "@/lib/motion";
import { rememberMoment } from "@/lib/patientContext";
import { GROUP_LABEL, HORIZON_MIN, PHASE_LABEL, PHASE_TONE } from "@/lib/risk";
import { fmtClock, fmtDate, fmtDay, HOUR, MINUTE, parseNaive, toNaiveIso } from "@/lib/time";
import { evidenceRange, evidenceText } from "@/lib/evidence";
import { featureInfo } from "@/lib/features";
import { toPoints, VERDICT_TEXT, verdict, windowOutcome, type Pt } from "@/lib/timeline";
import { TwinFocusProvider, useTwinFocus } from "@/lib/twinFocus";

const SECTIONS = [
  { id: "now", label: "Now" },
  { id: "why", label: "Why" },
  { id: "timeline", label: "Timeline" },
  { id: "personal", label: "Personal" },
  { id: "what-if", label: "What-if" },
  { id: "evolution", label: "Evolution" },
  { id: "provenance", label: "Provenance" },
];

/* ------------------------------------------------------------------ moment (URL state) */

interface Moment {
  asOf: string | null;
  mealId: string | null;
}

function useMoment(outcomes: MealOutcome[] | undefined) {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const fromUrl: Moment | null = params.get("at")
    ? { asOf: params.get("at"), mealId: params.get("meal") }
    : params.get("latest") === "1"
      ? { asOf: null, mealId: null }
      : null;
  // Default: the start of the most recent scorable meal, so the twin opens on a real prediction.
  const fallback = useMemo<Moment | null>(() => {
    if (!outcomes) return null;
    const last = [...outcomes].filter((o) => o.eligible).sort((a, b) => a.started_at.localeCompare(b.started_at)).at(-1);
    return last ? { asOf: last.started_at, mealId: last.meal_id } : { asOf: null, mealId: null };
  }, [outcomes]);
  const moment = fromUrl ?? fallback;
  const pid = Number(path.split("/")[2]);
  const search = params.toString();
  useEffect(() => {
    if (Number.isInteger(pid) && search) rememberMoment(pid, search);
  }, [pid, search]);
  const set = useCallback(
    (m: Moment) => {
      const q = new URLSearchParams();
      if (m.asOf) {
        q.set("at", m.asOf);
        if (m.mealId) q.set("meal", m.mealId);
      } else q.set("latest", "1");
      router.replace(`${path}?${q.toString()}`, { scroll: false });
    },
    [router, path],
  );
  return [moment, set] as const;
}

/* ------------------------------------------------------------------ moment picker */

function MomentPicker({ meals, outcomes, moment, onChange }: { meals: Meal[]; outcomes: MealOutcome[]; moment: Moment; onChange: (m: Moment) => void }) {
  const eligible = useMemo(() => new Set(outcomes.filter((o) => o.eligible).map((o) => o.meal_id)), [outcomes]);
  const sorted = useMemo(() => [...meals].sort((a, b) => a.started_at.localeCompare(b.started_at)), [meals]);
  const idx = sorted.findIndex((m) => m.meal_id === moment.mealId);
  const step = (d: number) => {
    // between meals (e.g. a replayed step), previous / next are the meals either side of the moment
    const seen = moment.asOf ? sorted.filter((m) => m.started_at <= moment.asOf!).length : sorted.length;
    const at = idx >= 0 ? idx + d : d > 0 ? seen : seen - 1;
    const next = sorted[at];
    if (next) onChange({ asOf: next.started_at, mealId: next.meal_id });
  };
  const byDay = useMemo(() => {
    const groups = new Map<string, Meal[]>();
    for (const m of sorted) {
      const d = fmtDay(parseNaive(m.started_at));
      groups.set(d, [...(groups.get(d) ?? []), m]);
    }
    return [...groups.entries()];
  }, [sorted]);
  return (
    <div className="moment">
      <Button icon size="md" aria-label="Previous meal" onClick={() => step(-1)} disabled={idx === 0 || (idx < 0 && !moment.asOf)}>
        <Icon name="chevronLeft" />
      </Button>
      <label className="moment__select">
        <span className="sr-only">Moment the twin is viewed at</span>
        <select
          className="select"
          value={moment.mealId ?? (moment.asOf ? "" : "latest")}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "latest") onChange({ asOf: null, mealId: null });
            else {
              const m = sorted.find((x) => x.meal_id === v);
              if (m) onChange({ asOf: m.started_at, mealId: m.meal_id });
            }
          }}
        >
          <option value="latest">Latest data (end of recording)</option>
          {/* a moment between meals (a replayed step, or a shared link): shown as itself */}
          {moment.asOf && !moment.mealId && (
            <option value="">
              {fmtDay(parseNaive(moment.asOf))} {fmtClock(parseNaive(moment.asOf))} · between meals
            </option>
          )}
          {byDay.map(([day, ms]) => (
            <optgroup key={day} label={day}>
              {ms.map((m) => (
                <option key={m.meal_id} value={m.meal_id}>
                  {fmtClock(parseNaive(m.started_at))} · {m.meal_type ?? "meal"}
                  {eligible.has(m.meal_id) ? "" : " (not scored)"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <Button icon size="md" aria-label="Next meal" onClick={() => step(1)} disabled={idx >= sorted.length - 1 || (idx < 0 && !moment.asOf)}>
        <Icon name="chevronRight" />
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------ section nav */

function SectionNav() {
  const [active, setActive] = useState("now");
  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return (
    <nav className="secnav" aria-label="Twin sections">
      <ul>
        {SECTIONS.map((s) => (
          <li key={s.id}>
            <a href={`#${s.id}`} className={cx("secnav__link", active === s.id && "is-active")} aria-current={active === s.id ? "location" : undefined}>
              {s.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/* ------------------------------------------------------------------ timeline + reveal */

const REVEAL_MS = MOTION.dataReveal;

function TimelineSection({ patient, state, meals, outcomes, onMeal }: { patient: PatientDetail; state: TwinState; meals: Meal[]; outcomes: MealOutcome[]; onMeal: (id: string) => void }) {
  const focus = useTwinFocus();
  const asOf = parseNaive(state.as_of);
  const meal = state.current_meal;
  const t0 = meal ? parseNaive(meal.started_at) : asOf;
  const start = t0 - 4 * HOUR;
  const end = t0 + 3 * HOUR;
  const cgm = useCgm(state.patient_id, toNaiveIso(start), toNaiveIso(end));
  const points = useMemo(() => toPoints(cgm.data ?? []), [cgm.data]);
  const dataEnd = patient.data_to ? parseNaive(patient.data_to) : asOf;
  const outcome = outcomes.find((o) => o.meal_id === meal?.meal_id);
  const windowEnd = t0 + HORIZON_MIN * MINUTE;
  const canReveal = Boolean(meal && state.risk.status === "scored" && outcome?.frozen_usable && windowEnd <= dataEnd && windowEnd > asOf);

  // reveal, in minutes after the twin's moment: 0 = the twin's view, span = the 120-min window closed
  const span = Math.max(0, Math.round((windowEnd - asOf) / MINUTE));
  const [minutes, setMinutes] = useState(0);
  const [started, setStarted] = useState(false);
  const [scrubbing, setScrubbing] = useState(false);
  const [peakHot, setPeakHot] = useState(false);
  const raf = useRef(0);
  useEffect(() => {
    cancelAnimationFrame(raf.current);
    setMinutes(0);
    setStarted(false);
  }, [state.state_id]);
  const play = () => {
    cancelAnimationFrame(raf.current);
    setStarted(true);
    if (prefersReducedMotion()) {
      setMinutes(span);
      return;
    }
    const from = minutes >= span ? 0 : minutes;
    const began = performance.now();
    const dur = REVEAL_MS * ((span - from) / Math.max(1, span));
    const tick = (now: number) => {
      const k = Math.min(1, (now - began) / Math.max(1, dur));
      setMinutes(from + (span - from) * k);
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  };
  const scrub = (m: number) => {
    cancelAnimationFrame(raf.current);
    setStarted(true);
    setMinutes(m);
  };
  const reset = () => {
    cancelAnimationFrame(raf.current);
    setMinutes(0);
    setStarted(false);
  };
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const done = started && minutes >= span;
  const cutoffT = asOf + minutes * MINUTE;
  // the chart's `revealed` is a share of everything after the moment; a closed window shows it all
  const reveal = done ? 1 : end > asOf ? (minutes * MINUTE) / (end - asOf) : 0;

  const out = meal ? windowOutcome(points, t0, HORIZON_MIN, outcome) : null;
  const v =
    done && out?.label != null && state.risk.probability !== null && state.risk.threshold !== null
      ? verdict(state.risk.probability, state.risk.threshold, out.label)
      : null;

  const tlMeals = meals.map((m) => {
    const o = outcomes.find((x) => x.meal_id === m.meal_id);
    return {
      id: m.meal_id,
      t: parseNaive(m.started_at),
      type: m.meal_type,
      current: m.meal_id === meal?.meal_id,
      scored: o?.eligible ?? false,
      carbs_g: m.carbs_g,
      fiber_g: m.fiber_g,
      protein_g: m.protein_g,
      fat_g: m.fat_g,
      calories_kcal: m.calories_kcal,
      macrosValid: m.macro_validity === "valid",
    };
  });
  const atStart = points.filter((p) => p.t <= asOf).at(-1);
  const summary = `Native Dexcom glucose from ${fmtClock(start)} to ${fmtClock(end)} on ${fmtDate(t0)}${atStart ? `; ${Math.round(atStart.v)} mg/dL at ${fmtClock(atStart.t)}` : ""}. ${
    meal ? `Prediction window ${fmtClock(t0)} to ${fmtClock(windowEnd)}.` : ""
  } ${done && out?.peak ? `Revealed peak ${Math.round(out.peak.v)} mg/dL at ${fmtClock(out.peak.t)}.` : "Readings after the twin's moment are hidden."} Use arrow keys to read values.`;

  // evidence for a model input, shown as the stretch of time it is computed from
  const ev = focus.evidence;
  const evRange = ev && meal ? evidenceRange(ev, t0) : null;
  const tlFocus = ev && evRange ? { ...evRange, meals: ev.kind === "prior-meals", label: `${featureInfo(ev.feature).label}: ${evidenceText(ev)}` } : null;

  // while a new window loads, keep drawing the one we have (no flash of old data on a new axis)
  const shown = useRef<{ start: number; end: number; asOf: number; points: Pt[] } | null>(null);
  if (!cgm.isPlaceholderData && cgm.data) shown.current = { start, end, asOf, points };
  const view = shown.current ?? { start, end, asOf, points };

  return (
    <div className="timeline">
      {cgm.isPending ? (
        <Loading label="Loading glucose"><Skeleton h={300} /></Loading>
      ) : cgm.isError ? (
        <ErrorState error={cgm.error} what="glucose readings" onRetry={() => void cgm.refetch()} />
      ) : view.points.length === 0 ? (
        <EmptyState icon="pulse" title="No native CGM readings in this window">The sensor recorded nothing between {fmtClock(start)} and {fmtClock(end)}.</EmptyState>
      ) : (
        <GlucoseTimeline
          points={view.points}
          start={view.start}
          end={view.end}
          meals={tlMeals}
          asOf={view.asOf}
          revealed={view.start === start ? reveal : 0}
          prediction={meal && view.start === start ? { t0, probability: state.risk.probability, threshold: state.risk.threshold, horizonMin: HORIZON_MIN } : undefined}
          summary={summary}
          onMealSelect={onMeal}
          peak={done ? out?.peak : null}
          peakEmphasis={peakHot}
          scrubbing={started && !done}
          focus={tlFocus}
          onClearFocus={() => focus.showEvidence(null, true)}
          pin={focus.pin}
        />
      )}
      <div className="timeline__legend xsmall">
        <span><span className="lg lg--observed" /> Measured (native Dexcom, 5-min)</span>
        <span><span className="lg lg--after" /> Measured later, hidden from the twin</span>
        <span><span className="lg lg--window" /> Prediction window, 120 min</span>
        <span><span className="lg lg--band" /> 70–180 mg/dL</span>
        <span><span className="lg lg--meal" /> Meal</span>
      </div>

      <div className="reveal">
        {!meal ? (
          <p className="small secondary">No meal has an open prediction window at this moment.</p>
        ) : !canReveal ? (
          <p className="small secondary">
            {state.risk.status !== "scored"
              ? "This meal was not scored, so there is no prediction to compare."
              : !outcome?.frozen_usable
                ? "This meal has no usable frozen outcome (overlapping meal or low CGM coverage)."
                : windowEnd > dataEnd
                  ? "The recording ends before this meal's window closes."
                  : "The twin is viewing this meal after its window closed; step to the meal start to replay it."}
          </p>
        ) : (
          <>
            {!started ? (
              <div className="reveal__cta">
                <div>
                  <p className="reveal__q">What actually happened after {fmtClock(t0)}?</p>
                  <p className="xsmall secondary">
                    The twin predicted {fmtPct(state.risk.probability)} using only data up to {fmtClock(asOf)}. Reveal the next 120 minutes of
                    recorded glucose to compare, or drag through them.
                  </p>
                </div>
                <Button onClick={play}>
                  <Icon name="play" size={13} /> Reveal what happened
                </Button>
              </div>
            ) : (
              <div className="scrub">
                <label className="scrub__label" htmlFor="reveal-scrub">
                  <span className="mono scrub__clock">{fmtClock(cutoffT)}</span>
                  <span className="xsmall secondary">
                    {Math.round(minutes)} of {span} min after the twin&rsquo;s moment
                  </span>
                </label>
                <input
                  id="reveal-scrub"
                  className="scrub__range lever__range"
                  type="range"
                  min={0}
                  max={span}
                  step={5}
                  value={Math.round(minutes)}
                  style={{ "--k": `${(minutes / Math.max(1, span)) * 100}%` } as CSSProperties}
                  onChange={(e) => scrub(Number(e.target.value))}
                  onPointerDown={() => setScrubbing(true)}
                  onPointerUp={() => setScrubbing(false)}
                  onBlur={() => setScrubbing(false)}
                  aria-valuetext={`${Math.round(minutes)} minutes revealed, until ${fmtClock(cutoffT)}`}
                  aria-describedby="reveal-scrub-help"
                  data-scrubbing={scrubbing || undefined}
                />
                <span id="reveal-scrub-help" className="sr-only">
                  Reveals recorded glucose after the twin&rsquo;s moment, 5 minutes per step.
                </span>
                {!done && (
                  <Button size="sm" variant="ghost" onClick={play}>
                    <Icon name="play" size={12} /> Play
                  </Button>
                )}
              </div>
            )}
            {done && (
              <div className={cx("reveal__result", v && `reveal__result--${VERDICT_TEXT[v].tone}`)} role="status">
                <div className="reveal__facts">
                  <div className="reveal__step" style={{ animationDelay: "0ms" }}>
                    <span className="reveal__k">
                      <Origin kind="model" /> Predicted at {fmtClock(asOf)}
                    </span>
                    <span className="reveal__v mono">{fmtPct(state.risk.probability)}</span>
                    <span className="xsmall muted">threshold {fmtPct(state.risk.threshold)}</span>
                  </div>
                  <Icon name="arrowRight" className="muted reveal__step" style={{ animationDelay: "120ms" }} />
                  <div
                    className="reveal__step reveal__step--peak"
                    style={{ animationDelay: "160ms" }}
                    tabIndex={out?.peak ? 0 : undefined}
                    onPointerEnter={() => setPeakHot(true)}
                    onPointerLeave={() => setPeakHot(false)}
                    onFocus={() => setPeakHot(true)}
                    onBlur={() => setPeakHot(false)}
                    aria-label={out?.peak ? `Highest reading in 2 hours: ${Math.round(out.peak.v)} mg/dL at ${fmtClock(out.peak.t)}, marked on the chart` : undefined}
                  >
                    <span className="reveal__k">
                      <Origin kind="observed" /> Highest reading in 2 h
                    </span>
                    <span className="reveal__v mono">{out?.peak ? Math.round(out.peak.v) : "—"} mg/dL</span>
                    <span className="xsmall muted">
                      {out?.peak ? `at ${fmtClock(out.peak.t)} · ` : ""}
                      {out?.firstAbove ? `first above 180 at ${fmtClock(out.firstAbove.t)}` : "no native reading above 180"}
                    </span>
                  </div>
                  <Icon name="arrowRight" className="muted reveal__step" style={{ animationDelay: "280ms" }} />
                  <div className="reveal__step" style={{ animationDelay: "320ms" }}>
                    <span className="reveal__k">Outcome (labels.v1)</span>
                    <span className="reveal__v">{out?.label === 1 ? "Above 180" : "Stayed ≤ 180"}</span>
                    <span className="xsmall muted">frozen label, 1-minute series</span>
                  </div>
                </div>
                {v && (
                  <p className="reveal__verdict reveal__step" style={{ animationDelay: "480ms" }}>
                    <strong>{VERDICT_TEXT[v].title}.</strong> {VERDICT_TEXT[v].body}
                  </p>
                )}
              </div>
            )}
            {started && (
              <div className="row">
                <Button size="sm" variant="ghost" onClick={reset}>
                  <Icon name="rotate" size={13} /> Back to the twin&rsquo;s view
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ what changed */

/** After a move in time: what the engine says changed between the previous and this state. */
function WhatChanged({ state }: { state: TwinState }) {
  const prev = useRef<{ id: string; asOf: string; patient: number } | null>(null);
  const [from, setFrom] = useState<{ id: string; asOf: string } | null>(null);
  useEffect(() => {
    const p = prev.current;
    prev.current = { id: state.state_id, asOf: state.as_of, patient: state.patient_id };
    setFrom(p && p.id !== state.state_id && p.patient === state.patient_id ? { id: p.id, asOf: p.asOf } : null);
  }, [state.state_id, state.as_of, state.patient_id]);
  const diff = useStateDiff(from?.id ?? null, from ? state.state_id : null);
  if (!from || diff.isError) return null;
  const items = (diff.data?.explanations ?? [])
    .map(readableChange)
    .filter((c): c is { text: string; rank: number } => c !== null)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 4)
    .map((c) => c.text);
  return (
    <div key={state.state_id} className="changes" role="status" aria-live="polite">
      <span className="changes__k">
        <Icon name="history" size={13} /> Since {fmtDay(parseNaive(from.asOf))} {fmtClock(parseNaive(from.asOf))}
      </span>
      {diff.isPending ? (
        <span className="muted">Comparing with the previous moment…</span>
      ) : items.length === 0 ? (
        <span className="secondary">No meaningful change in the twin&rsquo;s state.</span>
      ) : (
        <ul className="changes__list">
          {items.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <span className="changes__actions">
        <a href="#evolution" className="changes__link">
          Full comparison
        </a>
        <button type="button" className="changes__close" aria-label="Dismiss what changed" onClick={() => setFrom(null)}>
          <Icon name="x" size={12} />
        </button>
      </span>
    </div>
  );
}

/** A move in time puts away evidence chosen for the previous moment. */
function ResetFocusOnMove({ stateId }: { stateId: string }) {
  const { showEvidence } = useTwinFocus();
  useEffect(() => showEvidence(null, true), [stateId, showEvidence]);
  return null;
}

/* ------------------------------------------------------------------ workspace */

function Header({ patient, state, moment }: { patient: PatientDetail; state: TwinState | undefined; moment: ReactNode }) {
  return (
    <PageHeader
      crumbs={[{ label: "Patients", href: "/patients" }, { label: patient.external_ref }, { label: "Twin" }]}
      title={`Participant ${patient.external_ref}`}
      meta={
        <>
          <Tag tone="observed" title="Derived from baseline HbA1c; not a diagnosis">
            {GROUP_LABEL[patient.glycemic_group] ?? patient.glycemic_group}
          </Tag>
          {state && <Tag tone={PHASE_TONE[state.lifecycle.phase]}>{PHASE_LABEL[state.lifecycle.phase]}</Tag>}
          {patient.data_from && patient.data_to && (
            <span className="mono xsmall">
              {fmtDate(parseNaive(patient.data_from))} – {fmtDate(parseNaive(patient.data_to))}
            </span>
          )}
        </>
      }
      actions={moment}
      below={<PatientTabs patientId={patient.id} current="twin" day={state ? state.as_of.slice(0, 10) : null} />}
    />
  );
}

export function TwinWorkspace({ patientId }: { patientId: number }) {
  const patient = usePatient(patientId);
  const outcomes = useMealOutcomes(patientId);
  const meals = useMeals(patientId);
  const [moment, setMoment] = useMoment(outcomes.data);
  const twin = useTwinState(patientId, moment?.asOf ?? null, moment?.mealId ?? null, Boolean(moment) && patient.isSuccess);
  const [replayOpen, setReplayOpen] = useState(false);

  if (patient.isError) return <ErrorState error={patient.error} what="this patient" onRetry={() => void patient.refetch()} center />;
  if (patient.isPending || outcomes.isPending || meals.isPending)
    return (
      <Loading label="Loading the patient's twin">
        <div className="stack">
          <Skeleton w={260} h={28} />
          <Skeleton h={220} />
          <Skeleton h={300} />
        </div>
      </Loading>
    );
  if (outcomes.isError || meals.isError)
    return <ErrorState error={outcomes.error ?? meals.error} what="this patient's meals" onRetry={() => { void outcomes.refetch(); void meals.refetch(); }} />;

  const state = twin.data;
  const replayEntry =
    state && !replayOpen ? (
      <Button size="sm" variant="ghost" onClick={() => setReplayOpen(true)}>
        <Icon name="history" size={13} /> Replay history
      </Button>
    ) : null;
  const picker = moment ? <MomentPicker meals={meals.data} outcomes={outcomes.data} moment={moment} onChange={setMoment} /> : null;
  const selectMeal = (id: string) => {
    const m = meals.data.find((x) => x.meal_id === id);
    if (m) setMoment({ asOf: m.started_at, mealId: m.meal_id });
  };

  return (
    <TwinFocusProvider>
      <div className={cx("workspace", replayOpen && "has-replay")}>
        <Header patient={patient.data} state={state} moment={picker} />
        {moment && (
          <TwinRail
            patientId={patientId}
            meals={meals.data}
            outcomes={outcomes.data}
            dataFrom={patient.data.data_from}
            dataTo={patient.data.data_to}
            state={state}
            moment={moment}
            onSelect={setMoment}
            action={replayEntry}
          />
        )}
        <SectionNav />
        {twin.isError ? (
          <ErrorState error={twin.error} what="the twin state" onRetry={() => void twin.refetch()} />
        ) : !state ? (
          <Loading label="Building the twin state"><Skeleton h={240} /></Loading>
        ) : (
          <div className={cx("workspace__body", twin.isFetching && "is-refreshing")} aria-busy={twin.isFetching}>
            <section id="now" className="section section--hero" aria-label="Current twin state">
              <div className="now__head">
                <span className="section__eyebrow">Current twin state</span>
              </div>
              <CurrentState state={state} />
              <WhatChanged state={state} />
              <ResetFocusOnMove stateId={state.state_id} />
            </section>

            <Section id="why" eyebrow="Explanation" title="Why this risk?" description="Which inputs moved this estimate up or down, as computed by the served model for this exact prediction." aside={<WhyRiskAside />}>
              <WhyRisk state={state} />
            </Section>

            <Section id="timeline" eyebrow="Observed" title="Glucose and meals" description="Native Dexcom readings around the meal. The twin sees only what was recorded before its moment; reveal the rest to compare prediction with reality.">
              <TimelineSection patient={patient.data} state={state} meals={meals.data} outcomes={outcomes.data} onMeal={selectMeal} />
            </Section>

            <Section id="personal" eyebrow="Learning" title="Personal response" description="How much the twin has learned about this person from meals whose two-hour windows have closed.">
              <PersonalResponse state={state} />
            </Section>

            <Section id="what-if" eyebrow="Simulation" title="What if this meal were different?" description="Change the logged macros of the current meal and see how the model's estimate would move. Bounded to the range the model was trained on.">
              <WhatIf state={state} />
            </Section>

            <Section id="evolution" eyebrow="History" title="Twin evolution" description="Every state is an immutable snapshot. See how the twin learned across meals, and exactly what changed between two snapshots.">
              <Evolution patientId={patientId} outcomes={outcomes.data} current={state} onSelect={(mealId, asOf) => setMoment({ asOf, mealId })} />
            </Section>

            <Section id="provenance" eyebrow="Traceability" title="Provenance" description="What this state was computed from, and by which model.">
              <Provenance state={state} />
            </Section>
          </div>
        )}
        {replayOpen && state && (
          <ReplayDock
            patientId={patientId}
            state={state}
            dataTo={patient.data.data_to}
            onMoment={(asOf) => setMoment({ asOf, mealId: null })}
            onExit={() => setReplayOpen(false)}
          />
        )}
      </div>
    </TwinFocusProvider>
  );
}
