"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
import { useCgm, useMealOutcomes, useMeals, usePatient, useTwinState } from "@/lib/api/queries";
import type { Meal, MealOutcome, PatientDetail, TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtPct } from "@/lib/format";
import { prefersReducedMotion } from "@/lib/motion";
import { rememberMoment } from "@/lib/patientContext";
import { GROUP_LABEL, HORIZON_MIN, PHASE_LABEL, PHASE_TONE } from "@/lib/risk";
import { fmtClock, fmtDate, fmtDay, HOUR, MINUTE, parseNaive, toNaiveIso } from "@/lib/time";
import { toPoints, VERDICT_TEXT, verdict, windowOutcome } from "@/lib/timeline";

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
    const next = sorted[(idx < 0 ? sorted.length : idx) + d];
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
      <Button icon size="md" aria-label="Previous meal" onClick={() => step(-1)} disabled={idx <= 0}>
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
      <Button icon size="md" aria-label="Next meal" onClick={() => step(1)} disabled={idx < 0 || idx >= sorted.length - 1}>
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

function TimelineSection({ patient, state, meals, outcomes, onMeal }: { patient: PatientDetail; state: TwinState; meals: Meal[]; outcomes: MealOutcome[]; onMeal: (id: string) => void }) {
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

  // reveal: 0 = the twin's view; animates to 1 = everything recorded afterwards
  const [reveal, setReveal] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    cancelAnimationFrame(raf.current);
    setReveal(0);
  }, [state.state_id]);
  const play = () => {
    cancelAnimationFrame(raf.current);
    if (prefersReducedMotion()) {
      setReveal(1);
      return;
    }
    const began = performance.now();
    const dur = 2000; // a data reveal: slower than UI motion, still brief
    const tick = (now: number) => {
      const k = Math.min(1, (now - began) / dur);
      setReveal(k);
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  };
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const out = meal ? windowOutcome(points, t0, HORIZON_MIN, outcome) : null;
  const done = reveal >= 1;
  const v =
    done && out?.label != null && state.risk.probability !== null && state.risk.threshold !== null
      ? verdict(state.risk.probability, state.risk.threshold, out.label)
      : null;

  const tlMeals = meals.map((m) => {
    const o = outcomes.find((x) => x.meal_id === m.meal_id);
    return { id: m.meal_id, t: parseNaive(m.started_at), type: m.meal_type, current: m.meal_id === meal?.meal_id, scored: o?.eligible ?? false };
  });
  const atStart = points.filter((p) => p.t <= asOf).at(-1);
  const summary = `Native Dexcom glucose from ${fmtClock(start)} to ${fmtClock(end)} on ${fmtDate(t0)}${atStart ? `; ${Math.round(atStart.v)} mg/dL at ${fmtClock(atStart.t)}` : ""}. ${
    meal ? `Prediction window ${fmtClock(t0)} to ${fmtClock(windowEnd)}.` : ""
  } ${done && out?.peak ? `Revealed peak ${Math.round(out.peak.v)} mg/dL at ${fmtClock(out.peak.t)}.` : "Readings after the twin's moment are hidden."} Use arrow keys to read values.`;

  return (
    <div className="timeline">
      {cgm.isPending ? (
        <Loading label="Loading glucose"><Skeleton h={300} /></Loading>
      ) : cgm.isError ? (
        <ErrorState error={cgm.error} what="glucose readings" onRetry={() => void cgm.refetch()} />
      ) : points.length === 0 ? (
        <EmptyState icon="pulse" title="No native CGM readings in this window">The sensor recorded nothing between {fmtClock(start)} and {fmtClock(end)}.</EmptyState>
      ) : (
        <GlucoseTimeline
          points={points}
          start={start}
          end={end}
          meals={tlMeals}
          asOf={asOf}
          revealed={reveal}
          prediction={meal ? { t0, probability: state.risk.probability, threshold: state.risk.threshold, horizonMin: HORIZON_MIN } : undefined}
          summary={summary}
          onMealSelect={onMeal}
          peak={done ? out?.peak : null}
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
        ) : !done ? (
          <div className="reveal__cta">
            <div>
              <p className="reveal__q">What actually happened after {fmtClock(t0)}?</p>
              <p className="xsmall secondary">
                The twin predicted {fmtPct(state.risk.probability)} using only data up to {fmtClock(asOf)}. Reveal the next 120 minutes of
                recorded glucose to compare.
              </p>
            </div>
            {reveal > 0 ? (
              <p className="reveal__progress mono" role="status" aria-live="off">
                <span className="reveal__clock">{fmtClock(asOf + (end - asOf) * reveal)}</span>
                <span className="reveal__bar" aria-hidden="true">
                  <span style={{ transform: `scaleX(${reveal})` }} />
                </span>
              </p>
            ) : (
              <Button onClick={play}>
                <Icon name="play" size={13} /> Reveal what happened
              </Button>
            )}
          </div>
        ) : (
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
              <div className="reveal__step" style={{ animationDelay: "160ms" }}>
                <span className="reveal__k">
                  <Origin kind="observed" /> Highest reading in 2 h
                </span>
                <span className="reveal__v mono">{out?.peak ? Math.round(out.peak.v) : "—"} mg/dL</span>
                <span className="xsmall muted">
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
            <Button size="sm" variant="ghost" onClick={() => setReveal(0)}>
              <Icon name="rotate" size={13} /> Back to the twin&rsquo;s view
            </Button>
          </div>
        )}
      </div>
    </div>
  );
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
  const picker = moment ? <MomentPicker meals={meals.data} outcomes={outcomes.data} moment={moment} onChange={setMoment} /> : null;
  const selectMeal = (id: string) => {
    const m = meals.data.find((x) => x.meal_id === id);
    if (m) setMoment({ asOf: m.started_at, mealId: m.meal_id });
  };

  return (
    <div className="workspace">
      <Header patient={patient.data} state={state} moment={picker} />
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
    </div>
  );
}
