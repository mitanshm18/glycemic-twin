"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { PatientTabs } from "@/components/shell/PatientTabs";
import { GlucoseTimeline, type TimelineMeal } from "@/components/twin/GlucoseTimeline";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Metric } from "@/components/ui/Metric";
import { Section } from "@/components/ui/Section";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { Tip } from "@/components/ui/Tip";
import { useCgm, useClinical, useMealOutcomes, useMeals, usePatient, useWearable } from "@/lib/api/queries";
import type { ClinicalField, Meal, MealOutcome, WearablePoint } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { DASH, fmtNum, isNum } from "@/lib/format";
import { GROUP_LABEL, THRESHOLD_MGDL } from "@/lib/risk";
import { DAY, dayStart, fmtClock, fmtDate, fmtDay, parseNaive, toNaiveIso, type Millis } from "@/lib/time";
import { twinHref } from "@/lib/patientContext";
import { toPoints } from "@/lib/timeline";

/** Display labels for the CGMacros baseline fields (names and units come from the API). */
const CLINICAL_GROUPS: Array<{ title: string; fields: Array<[string, string]> }> = [
  {
    title: "Demographics & body",
    fields: [
      ["age_years", "Age"],
      ["sex", "Sex (as recorded)"],
      ["ethnicity", "Ethnicity (self-identified)"],
      ["height_in", "Height"],
      ["body_weight_lb", "Body weight"],
      ["bmi", "BMI"],
    ],
  },
  {
    title: "Glycemic",
    fields: [
      ["hba1c_pct", "HbA1c"],
      ["glycemic_group", "Glycemic group"],
      ["fasting_glucose_mgdl", "Fasting glucose"],
      ["fasting_insulin_uu_ml", "Fasting insulin"],
    ],
  },
  {
    title: "Lipids",
    fields: [
      ["triglycerides_mgdl", "Triglycerides"],
      ["cholesterol_mgdl", "Total cholesterol"],
      ["hdl_mgdl", "HDL"],
      ["ldl_mgdl", "LDL (calculated)"],
      ["vldl_mgdl", "VLDL (calculated)"],
      ["non_hdl_mgdl", "Non-HDL"],
      ["chol_hdl_ratio", "Cholesterol / HDL"],
    ],
  },
  {
    title: "Collection",
    fields: [
      ["lab_collection_time", "Fasting labs collected"],
      ["fingerstick_1_mgdl", "Fingerstick 1"],
      ["fingerstick_1_time", "Fingerstick 1 time"],
      ["fingerstick_2_mgdl", "Fingerstick 2"],
      ["fingerstick_2_time", "Fingerstick 2 time"],
      ["fingerstick_3_mgdl", "Fingerstick 3"],
      ["fingerstick_3_time", "Fingerstick 3 time"],
    ],
  },
];

const KNOWN = new Set(CLINICAL_GROUPS.flatMap((g) => g.fields.map(([f]) => f)));

function fieldValue(f: ClinicalField): string {
  if (f.field === "glycemic_group" && f.value_text) return GROUP_LABEL[f.value_text] ?? f.value_text;
  if (f.value_text !== null && f.value_text !== "") return f.value_text;
  if (!isNum(f.value_num)) return DASH;
  return fmtNum(f.value_num, Number.isInteger(f.value_num) ? 0 : 1);
}

function ClinicalRow({ f, label }: { f: ClinicalField | undefined; label: string }) {
  if (!f) {
    return (
      <>
        <dt>{label}</dt>
        <dd className="muted">Not recorded</dd>
      </>
    );
  }
  const missing = f.value_num === null && (f.value_text === null || f.value_text === "");
  const source = f.source_column ? `${f.source_file ?? "source"} · ${f.source_column}` : (f.source_file ?? "");
  return (
    <>
      <dt>{label}</dt>
      <dd className="rec-field">
        <span className={cx("rec-field__value", missing && "muted")}>
          <span className="num">{missing ? "Not recorded" : fieldValue(f)}</span>
          {!missing && f.unit && f.unit !== "HH:MM" && <span className="rec-field__unit">{f.unit}</span>}
        </span>
        <span className="rec-field__meta">
          {f.provenance === "derived" ? (
            <Tip text={f.derivation ?? "Derived from other recorded fields."}>
              <Tag tone="model">Derived</Tag>
            </Tip>
          ) : (
            <Tip text={source ? `Recorded in ${source}` : "Recorded in the source data"}>
              <Tag tone="observed">Observed</Tag>
            </Tip>
          )}
          {f.quality_flag && (
            <Tip text={`Quality flag: ${f.quality_flag.replaceAll("_", " ")}. The source value looked like an error code and was not used.`}>
              <Tag tone="warning" icon="alert">
                Flagged
              </Tag>
            </Tip>
          )}
        </span>
      </dd>
    </>
  );
}

function Baseline({ fields }: { fields: ClinicalField[] }) {
  const byName = new Map(fields.map((f) => [f.field, f]));
  const extra = fields.filter((f) => !KNOWN.has(f.field));
  return (
    <div className="rec-baseline">
      {CLINICAL_GROUPS.map((g) => (
        <div key={g.title} className="rec-card">
          <h3 className="rec-card__title">{g.title}</h3>
          <dl className="kv kv--compact">
            {g.fields.map(([name, label]) => (
              <ClinicalRow key={name} f={byName.get(name)} label={label} />
            ))}
          </dl>
        </div>
      ))}
      {extra.length > 0 && (
        <div className="rec-card">
          <h3 className="rec-card__title">Other fields</h3>
          <dl className="kv kv--compact">
            {extra.map((f) => (
              <ClinicalRow key={f.field} f={f} label={f.field.replaceAll("_", " ")} />
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ chronology

interface DayInfo {
  t: Millis;
  key: string;
  meals: Meal[];
  scorable: number;
  positives: number;
}

function buildDays(from: string | null, to: string | null, meals: Meal[], outcomes: Map<string, MealOutcome>): DayInfo[] {
  if (!from || !to) return [];
  const first = dayStart(parseNaive(from));
  const last = dayStart(parseNaive(to));
  const days: DayInfo[] = [];
  for (let t = first; t <= last && days.length < 60; t += DAY) {
    days.push({ t, key: toNaiveIso(t).slice(0, 10), meals: [], scorable: 0, positives: 0 });
  }
  const index = new Map(days.map((d) => [d.t, d]));
  for (const m of meals) {
    const d = index.get(dayStart(parseNaive(m.started_at)));
    if (!d) continue;
    d.meals.push(m);
    const o = outcomes.get(m.meal_id);
    if (o?.eligible) {
      d.scorable += 1;
      if (o.label === 1) d.positives += 1;
    }
  }
  return days;
}

function wearableSummary(points: WearablePoint[]) {
  const hr = points.map((p) => p.hr_bpm).filter(isNum);
  const kcal = points.map((p) => p.activity_kcal).filter(isNum);
  const mets = points.map((p) => p.mets).filter(isNum);
  return {
    minutes: points.length,
    meanHr: hr.length ? hr.reduce((a, b) => a + b, 0) / hr.length : null,
    kcal: kcal.length ? kcal.reduce((a, b) => a + b, 0) : null,
    activeMin: mets.length ? mets.filter((m) => m >= 3).length : null,
  };
}

function outcomeCell(o: MealOutcome | undefined) {
  if (!o) return <span className="muted xsmall">No outcome</span>;
  if (!o.eligible) {
    return (
      <Tip text={o.note || o.waterfall_reason.replaceAll("_", " ")}>
        <span className="muted xsmall rec-excluded">Not scorable · {o.waterfall_reason.replaceAll("_", " ")}</span>
      </Tip>
    );
  }
  return o.label === 1 ? (
    <Tag tone="risk">Went above {THRESHOLD_MGDL}</Tag>
  ) : (
    <Tag tone="success">Stayed at or below {THRESHOLD_MGDL}</Tag>
  );
}

function DayDetail({ patientId, day, outcomes }: { patientId: number; day: DayInfo; outcomes: Map<string, MealOutcome> }) {
  const start = toNaiveIso(day.t);
  const end = toNaiveIso(day.t + DAY);
  const cgm = useCgm(patientId, start, end);
  const wear = useWearable(patientId, start, end);
  const points = useMemo(() => toPoints(cgm.data ?? []), [cgm.data]);
  const tlMeals: TimelineMeal[] = day.meals.map((m) => ({
    id: m.meal_id,
    t: parseNaive(m.started_at),
    type: m.meal_type,
    scored: outcomes.get(m.meal_id)?.eligible ?? false,
  }));
  const ws = wear.data ? wearableSummary(wear.data) : null;
  const glucose = points.map((p) => p.v);
  const above = glucose.filter((v) => v > THRESHOLD_MGDL).length;

  return (
    <div className="rec-day">
      <div className="rec-day__chart">
        {cgm.isPending ? (
          <Skeleton h={260} />
        ) : cgm.isError ? (
          <ErrorState error={cgm.error} what="glucose for this day" onRetry={() => void cgm.refetch()} />
        ) : points.length === 0 ? (
          <EmptyState icon="pulse" title="No native CGM readings on this day" />
        ) : (
          <GlucoseTimeline
            points={points}
            start={day.t}
            end={day.t + DAY}
            meals={tlMeals}
            height={260}
            summary={`Dexcom glucose on ${fmtDay(day.t)}: ${points.length} readings, ${above} above ${THRESHOLD_MGDL} mg/dL, ${day.meals.length} logged meals.`}
          />
        )}
      </div>

      <dl className="rec-day__stats">
        <Metric label="CGM readings" value={fmtNum(points.length)} sub="native Dexcom, 5-min" />
        <Metric
          label="Time above 180"
          value={points.length ? fmtNum((above / points.length) * 100) : DASH}
          unit={points.length ? "%" : undefined}
          sub="share of readings"
        />
        <Metric label="Wearable" value={ws ? fmtNum(ws.minutes) : DASH} unit={ws ? "min" : undefined} sub={ws?.meanHr ? `mean HR ${fmtNum(ws.meanHr)} bpm` : "no heart rate"} />
        <Metric
          label="Activity"
          value={ws?.kcal !== null && ws ? fmtNum(ws.kcal) : DASH}
          unit={ws?.kcal !== null && ws ? "kcal" : undefined}
          sub={ws?.activeMin !== null && ws ? `${ws.activeMin} min at ≥ 3 METs` : "METs not recorded"}
        />
      </dl>

      {day.meals.length === 0 ? (
        <EmptyState icon="meal" title="No meals logged on this day" />
      ) : (
        <div className="table-wrap">
          <table className="table rec-meals">
            <caption className="sr-only">Meals logged on {fmtDay(day.t)}</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Meal</th>
                <th scope="col" className="right">Carbs</th>
                <th scope="col" className="right">Protein</th>
                <th scope="col" className="right">Fat</th>
                <th scope="col" className="right">Fiber</th>
                <th scope="col" className="right">kcal</th>
                <th scope="col" className="right">Peak</th>
                <th scope="col">Observed outcome</th>
                <th scope="col"><span className="sr-only">Open in twin</span></th>
              </tr>
            </thead>
            <tbody>
              {day.meals.map((m) => {
                const o = outcomes.get(m.meal_id);
                const peak = o?.peak_native_mgdl ?? o?.peak_mgdl ?? null;
                return (
                  <tr key={m.meal_id}>
                    <td className="mono" data-label="Time">{fmtClock(parseNaive(m.started_at))}</td>
                    <td data-label="Meal">
                      {m.meal_type ?? "Meal"}
                      {m.macro_validity !== "valid" && (
                        <Tip text={m.macro_reasons ?? "Macros could not be used for this meal."}>
                          <Tag tone="warning" className="rec-meals__flag">Macros unusable</Tag>
                        </Tip>
                      )}
                    </td>
                    <td className="right mono" data-label="Carbs">{fmtNum(m.carbs_g)}</td>
                    <td className="right mono" data-label="Protein">{fmtNum(m.protein_g)}</td>
                    <td className="right mono" data-label="Fat">{fmtNum(m.fat_g)}</td>
                    <td className="right mono" data-label="Fiber">{fmtNum(m.fiber_g)}</td>
                    <td className="right mono" data-label="kcal">{fmtNum(m.calories_kcal)}</td>
                    <td className={cx("right mono", isNum(peak) && peak > THRESHOLD_MGDL && "rec-peak--high")} data-label="Peak">
                      {fmtNum(peak)}
                    </td>
                    <td data-label="Outcome">{outcomeCell(o)}</td>
                    <td className="right">
                      {o?.eligible && (
                        <Link
                          className="btn btn--ghost btn--sm"
                          href={`/patients/${patientId}?at=${encodeURIComponent(m.started_at)}&meal=${encodeURIComponent(m.meal_id)}`}
                          aria-label={`Open the twin at the ${m.meal_type ?? "meal"} of ${fmtDay(day.t)}, ${fmtClock(parseNaive(m.started_at))}`}
                        >
                          Twin <Icon name="arrowRight" size={12} />
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ClinicalRecord({ patientId }: { patientId: number }) {
  const patient = usePatient(patientId);
  const clinical = useClinical(patientId);
  const meals = useMeals(patientId);
  const outcomes = useMealOutcomes(patientId);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const outcomeMap = useMemo(() => new Map((outcomes.data ?? []).map((o) => [o.meal_id, o])), [outcomes.data]);
  const days = useMemo(
    () => buildDays(patient.data?.data_from ?? null, patient.data?.data_to ?? null, meals.data ?? [], outcomeMap),
    [patient.data, meals.data, outcomeMap],
  );
  const selectedKey = params.get("day");
  const selected = days.find((d) => d.key === selectedKey) ?? days.find((d) => d.meals.length > 0) ?? days[0];
  const selectDay = (d: DayInfo) => {
    const q = new URLSearchParams(params.toString());
    q.set("day", d.key);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  };
  const idx = selected ? days.indexOf(selected) : -1;

  if (patient.isError) {
    return <ErrorState error={patient.error} what="this patient" center />;
  }
  const p = patient.data;
  const ref = p?.external_ref ?? `Patient ${patientId}`;

  return (
    <div className="record">
      <PageHeader
        crumbs={[
          { label: "Patients", href: "/patients" },
          { label: ref, href: twinHref(patientId) },
          { label: "Clinical record" },
        ]}
        title={`Participant ${ref}`}
        meta={
          p ? (
            <>
              <Tag tone="observed" title="Derived from baseline HbA1c; not a diagnosis">
                {GROUP_LABEL[p.glycemic_group] ?? p.glycemic_group}
              </Tag>
              {p.data_from && p.data_to && (
                <span className="mono xsmall">
                  {fmtDate(parseNaive(p.data_from))} – {fmtDate(parseNaive(p.data_to))}
                </span>
              )}
              <span className="xsmall">{p.source_label}</span>
            </>
          ) : (
            <Skeleton w={260} />
          )
        }
        below={<PatientTabs patientId={patientId} current="record" day={selectedKey} />}
      />

      <dl className="record__summary">
        {p ? (
          <>
            <Metric label="Logged meals" value={fmtNum(p.meals)} sub={`${p.eligible_meals} scorable under labels v1`} />
            <Metric label="CGM readings" value={fmtNum(p.cgm_native_readings)} sub={`native · ${fmtNum(p.cgm_readings)} incl. interpolated`} />
            <Metric label="Wearable minutes" value={fmtNum(p.wearable_minutes)} sub="heart rate, METs, kcal" />
            <Metric label="Recording" value={fmtNum(days.length)} unit="days" sub="retrospective study data" />
          </>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} h={64} />)
        )}
      </dl>

      <Section id="baseline" eyebrow="Recorded once, at study start" title="Baseline" description="Values as recorded in the CGMacros source. Derived values are marked, with how they were derived.">
        {clinical.isPending ? (
          <Loading label="Loading clinical fields">
            <Skeleton h={220} />
          </Loading>
        ) : clinical.isError ? (
          <ErrorState error={clinical.error} what="clinical fields" onRetry={() => void clinical.refetch()} />
        ) : clinical.data.length === 0 ? (
          <EmptyState icon="record" title="No baseline fields for this participant" />
        ) : (
          <Baseline fields={clinical.data} />
        )}
      </Section>

      <Section
        id="chronology"
        eyebrow="Day by day"
        title="Chronology"
        description="Everything recorded on one day: native CGM, logged meals with their frozen outcome labels, and wearable totals."
      >
        {meals.isPending || outcomes.isPending || patient.isPending ? (
          <Loading label="Loading the chronology">
            <Skeleton h={48} />
            <Skeleton h={260} style={{ marginTop: 12 }} />
          </Loading>
        ) : meals.isError || outcomes.isError ? (
          <ErrorState error={meals.error ?? outcomes.error} what="meals" onRetry={() => { void meals.refetch(); void outcomes.refetch(); }} />
        ) : days.length === 0 || !selected ? (
          <EmptyState icon="clock" title="No time-series data for this participant" />
        ) : (
          <div className="chrono">
            <div className="chrono__nav">
              <Button size="sm" variant="ghost" icon aria-label="Previous day" disabled={idx <= 0} onClick={() => { const d = days[idx - 1]; if (d) selectDay(d); }}>
                <Icon name="chevronLeft" />
              </Button>
              <ol className="chrono__days" aria-label="Recording days">
                {days.map((d, i) => (
                  <li key={d.key}>
                    <button
                      type="button"
                      className={cx("chrono__day", d === selected && "is-active")}
                      aria-current={d === selected ? "date" : undefined}
                      onClick={() => selectDay(d)}
                    >
                      <span className="chrono__n">Day {i + 1}</span>
                      <span className="chrono__date">{fmtDay(d.t)}</span>
                      <span className="chrono__pips" aria-label={`${d.meals.length} meals, ${d.positives} above ${THRESHOLD_MGDL}`}>
                        {d.meals.slice(0, 6).map((m) => {
                          const o = outcomeMap.get(m.meal_id);
                          return <span key={m.meal_id} className={cx("pip", o?.eligible && (o.label === 1 ? "pip--pos" : "pip--neg"))} />;
                        })}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              <Button size="sm" variant="ghost" icon aria-label="Next day" disabled={idx >= days.length - 1} onClick={() => { const d = days[idx + 1]; if (d) selectDay(d); }}>
                <Icon name="chevronRight" />
              </Button>
            </div>
            <div className="chrono__legend xsmall secondary" aria-hidden="true">
              <span><span className="pip pip--pos" /> went above 180</span>
              <span><span className="pip pip--neg" /> stayed ≤ 180</span>
              <span><span className="pip" /> not scorable</span>
            </div>
            <h3 className="chrono__title">
              {fmtDay(selected.t)} <span className="muted">· Day {idx + 1} of {days.length}</span>
            </h3>
            <DayDetail key={selected.key} patientId={patientId} day={selected} outcomes={outcomeMap} />
          </div>
        )}
      </Section>
    </div>
  );
}
