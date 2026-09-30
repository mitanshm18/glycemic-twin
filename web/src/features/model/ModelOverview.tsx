"use client";

import { PageHeader } from "@/components/shell/AppShell";
import { Icon } from "@/components/ui/Icon";
import { Ident } from "@/components/ui/Ident";
import { Metric } from "@/components/ui/Metric";
import { Section } from "@/components/ui/Section";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { Tip } from "@/components/ui/Tip";
import { isApiError } from "@/lib/api/client";
import { useEvaluation, useModels } from "@/lib/api/queries";
import type { Evaluation, Interval, ModelVersion, PopulationMetrics } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { featureInfo } from "@/lib/features";
import { DASH, fmtNum, fmtPct, isNum, modelLabel } from "@/lib/format";
import { fmtRelative } from "@/lib/time";
import { linear } from "@/lib/timeline";
import { useWidth } from "@/lib/useSize";

const f3 = (v: number | null | undefined) => (isNum(v) ? v.toFixed(3) : DASH);

function ci(i: Interval | undefined, digits = 3) {
  if (!i || !isNum(i.lo) || !isNum(i.hi)) return null;
  return `95% CI ${i.lo.toFixed(digits)} – ${i.hi.toFixed(digits)}`;
}

function runLabel(run: string): string {
  const [model, fs] = run.split("__");
  return modelLabel(model, fs);
}

// ------------------------------------------------------------------ headline metrics

function Headline({ m, what }: { m: PopulationMetrics; what: string }) {
  return (
    <dl className="model-metrics">
      <Metric
        label={
          <Tip text="How well the model ranks meals that went above 180 over meals that did not. 0.5 is chance, 1.0 is perfect ranking.">
            <span className="tip-term">AUROC</span>
          </Tip>
        }
        value={f3(m.auroc)}
        sub={ci(m.ci.auroc) ?? "no interval"}
      />
      <Metric
        label={
          <Tip text="Precision–recall area. The chance level equals the share of meals that went above 180 (the prevalence).">
            <span className="tip-term">PR-AUC</span>
          </Tip>
        }
        value={f3(m.pr_auc)}
        sub={
          <>
            {ci(m.ci.pr_auc) ?? "no interval"}
            <br />
            chance level {fmtPct(m.prevalence, 1)}
          </>
        }
      />
      <Metric
        label={
          <Tip text="Mean squared error of the probabilities (lower is better). Skill compares it with always predicting the prevalence.">
            <span className="tip-term">Brier score</span>
          </Tip>
        }
        value={f3(m.brier)}
        sub={
          <>
            {ci(m.ci.brier) ?? "no interval"}
            <br />
            skill {isNum(m.brier_skill) ? m.brier_skill.toFixed(3) : DASH} vs prevalence
          </>
        }
      />
      <Metric
        label={
          <Tip text="Slope 1 and intercept 0 mean predicted probabilities match observed rates on average. ECE is the mean gap per bin.">
            <span className="tip-term">Calibration</span>
          </Tip>
        }
        value={isNum(m.calibration_slope) ? m.calibration_slope.toFixed(2) : DASH}
        unit="slope"
        sub={`intercept ${isNum(m.calibration_intercept) ? m.calibration_intercept.toFixed(2) : DASH} · ECE ${f3(m.ece)}`}
      />
      <p className="model-metrics__foot xsmall secondary">
        {what}: {fmtNum(m.meals)} meals from {fmtNum(m.participants)} participants, {fmtNum(m.positives)} went above 180 (
        {fmtPct(m.prevalence, 1)}). Out-of-fold predictions; intervals are participant bootstrap.
      </p>
    </dl>
  );
}

// ------------------------------------------------------------------ calibration

function Calibration({ bins }: { bins: Evaluation["active_calibration_curve"] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const size = Math.max(240, Math.min(420, width));
  const pad = { l: 44, r: 12, t: 12, b: 40 };
  const x = linear([0, 1], [pad.l, size - pad.r]);
  const y = linear([0, 1], [size - pad.b, pad.t]);
  const maxN = Math.max(1, ...bins.map((b) => b.n));
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const path = bins.map((b, i) => `${i ? "L" : "M"}${x(b.mean_predicted)},${y(b.observed_rate)}`).join("");
  return (
    <div className="calib" ref={ref}>
      <svg
        width={size}
        height={size}
        role="img"
        aria-label={`Calibration curve with ${bins.length} bins. ${bins
          .map((b) => `Predicted ${fmtPct(b.mean_predicted)}, observed ${fmtPct(b.observed_rate)} (${b.n} meals)`)
          .join("; ")}.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line className="calib__grid" x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} />
            <line className="calib__grid" x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} />
            <text className="calib__tick" x={x(t)} y={y(0) + 16} textAnchor="middle">
              {Math.round(t * 100)}%
            </text>
            <text className="calib__tick" x={x(0) - 8} y={y(t) + 4} textAnchor="end">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        <line className="calib__diag" x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
        <path className="calib__line" d={path} />
        {bins.map((b) => (
          <circle key={b.bin} className="calib__pt" cx={x(b.mean_predicted)} cy={y(b.observed_rate)} r={3 + 6 * Math.sqrt(b.n / maxN)}>
            <title>{`Predicted ${fmtPct(b.mean_predicted, 1)} · observed ${fmtPct(b.observed_rate, 1)} · ${b.n} meals`}</title>
          </circle>
        ))}
        <text className="calib__axis" x={(x(0) + x(1)) / 2} y={size - 6} textAnchor="middle">
          Predicted probability
        </text>
        <text className="calib__axis" transform={`translate(12 ${(y(0) + y(1)) / 2}) rotate(-90)`} textAnchor="middle">
          Observed share above 180
        </text>
      </svg>
      <p className="xsmall secondary calib__note">
        Points on the dashed diagonal would be perfectly calibrated. Point size shows how many meals fall in each bin; sparse bins are noisy.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ threshold

function AtThreshold({ t, threshold }: { t: Evaluation["active_at_threshold"]; threshold: number | null }) {
  const n = (k: string) => (isNum(t[k]) ? (t[k] as number) : null);
  return (
    <div className="thr">
      <table className="thr__matrix">
        <caption className="xsmall secondary">
          Out-of-fold decisions at threshold {fmtPct(threshold, 1)} (meals)
        </caption>
        <thead>
          <tr>
            <td />
            <th scope="col">Went above 180</th>
            <th scope="col">Stayed ≤ 180</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Flagged</th>
            <td className="thr__cell thr__cell--good">{fmtNum(n("tp"))}<span>true alerts</span></td>
            <td className="thr__cell thr__cell--warn">{fmtNum(n("fp"))}<span>false alarms</span></td>
          </tr>
          <tr>
            <th scope="row">Not flagged</th>
            <td className="thr__cell thr__cell--bad">{fmtNum(n("fn"))}<span>missed</span></td>
            <td className="thr__cell thr__cell--good">{fmtNum(n("tn"))}<span>true quiet</span></td>
          </tr>
        </tbody>
      </table>
      <dl className="thr__rates">
        <Metric label="Sensitivity" value={fmtPct(n("sensitivity"))} sub="of meals that went above, share flagged" />
        <Metric label="Specificity" value={fmtPct(n("specificity"))} sub="of meals that stayed below, share not flagged" />
        <Metric label="PPV" value={fmtPct(n("ppv"))} sub="of flags, share that went above" />
        <Metric label="NPV" value={fmtPct(n("npv"))} sub="of non-flags, share that stayed below" />
        <Metric label="Flagged" value={fmtPct(n("flagged_share"))} sub="of all meals" />
      </dl>
    </div>
  );
}

// ------------------------------------------------------------------ comparison tables

function Runs({ ev }: { ev: Evaluation }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">All evaluated models on the prediabetes and type 2 diabetes population</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col" className="right">Inputs</th>
            <th scope="col" className="right">AUROC</th>
            <th scope="col" className="right">PR-AUC</th>
            <th scope="col" className="right">Brier</th>
            <th scope="col" className="right">ECE</th>
            <th scope="col" className="right">Normoglycemic AUROC</th>
          </tr>
        </thead>
        <tbody>
          {ev.runs.map((r) => (
            <tr key={r.run} className={cx(r.run === ev.active_run && "is-active")}>
              <th scope="row">
                {runLabel(r.run)}{" "}
                {r.run === ev.active_run && <Tag tone="accent">Active</Tag>}{" "}
                {r.run === ev.primary_run && r.run !== ev.active_run && <Tag tone="quiet">Primary</Tag>}
              </th>
              <td className="right mono">{r.n_columns}</td>
              <td className="right mono">
                {f3(r.target.auroc)}
                <span className="table__ci">{ci(r.target.ci.auroc)?.replace("95% CI ", "")}</span>
              </td>
              <td className="right mono">
                {f3(r.target.pr_auc)}
                <span className="table__ci">{ci(r.target.ci.pr_auc)?.replace("95% CI ", "")}</span>
              </td>
              <td className="right mono">{f3(r.target.brier)}</td>
              <td className="right mono">{f3(r.target.ece)}</td>
              <td className="right mono secondary">{f3(r.healthy.auroc)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Comparisons({ ev }: { ev: Evaluation }) {
  const rows = ev.comparisons.filter((c) => c.ran);
  if (rows.length === 0) return <p className="small secondary">No paired comparisons were run.</p>;
  return (
    <ul className="cmp-list">
      {rows.map((c) => {
        const lo = c.pr_auc_lo;
        const hi = c.pr_auc_hi;
        const clear = isNum(lo) && isNum(hi) && (lo > 0 || hi < 0);
        return (
          <li key={c.comparison} className="cmp-list__item">
            <div className="cmp-list__head">
              <span>
                <strong>{runLabel(c.a)}</strong> vs <strong>{runLabel(c.b)}</strong>
              </span>
              <Tag tone={clear ? "accent" : "quiet"}>{clear ? "Interval excludes 0" : "Not distinguishable"}</Tag>
            </div>
            <p className="small secondary mono">
              ΔPR-AUC {isNum(c.pr_auc_difference) ? c.pr_auc_difference.toFixed(3) : DASH}
              {isNum(lo) && isNum(hi) && ` [${lo.toFixed(3)}, ${hi.toFixed(3)}]`} · ΔAUROC{" "}
              {isNum(c.auroc_difference) ? c.auroc_difference.toFixed(3) : DASH}
              {isNum(c.auroc_lo) && isNum(c.auroc_hi) && ` [${c.auroc_lo.toFixed(3)}, ${c.auroc_hi.toFixed(3)}]`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Folds({ ev }: { ev: Evaluation }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Per-fold results of the active model</caption>
        <thead>
          <tr>
            <th scope="col">Fold</th>
            <th scope="col" className="right">Participants</th>
            <th scope="col" className="right">Meals</th>
            <th scope="col" className="right">Above 180</th>
            <th scope="col" className="right">AUROC</th>
            <th scope="col" className="right">PR-AUC</th>
            <th scope="col" className="right">Brier</th>
          </tr>
        </thead>
        <tbody>
          {ev.active_per_fold.map((f) => (
            <tr key={f.fold}>
              <th scope="row" className="mono">{f.fold}</th>
              <td className="right mono">{f.participants}</td>
              <td className="right mono">{f.meals}</td>
              <td className="right mono">{f.positives}</td>
              <td className="right mono">{f3(f.auroc)}</td>
              <td className="right mono">{f3(f.pr_auc)}</td>
              <td className="right mono">{f3(f.brier)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Importance({ items }: { items: Evaluation["shap_global_importance"] }) {
  const top = items.slice(0, 12);
  const max = Math.max(...top.map((i) => i.mean_abs_shap), 1e-9);
  return (
    <ol className="imp">
      {top.map((i) => {
        const info = featureInfo(i.feature);
        return (
          <li key={i.feature} className="imp__row">
            <span className="imp__name">
              {info.label}
              <span className="imp__feat mono">{i.feature}</span>
            </span>
            <span className="imp__bar" aria-hidden="true">
              <span className="imp__fill" style={{ width: `${(i.mean_abs_shap / max) * 100}%` }} />
            </span>
            <span className="imp__val mono">{i.mean_abs_shap.toFixed(3)}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ registry

function Registry({ versions }: { versions: ModelVersion[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Registered model versions</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Version</th>
            <th scope="col" className="right">Threshold</th>
            <th scope="col">Training data</th>
            <th scope="col">What-if</th>
            <th scope="col">Registered</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id} className={cx(v.is_active && "is-active")}>
              <th scope="row">
                {modelLabel(v.model_type, v.feature_set)} {v.is_active && <Tag tone="accent">Active</Tag>}
              </th>
              <td><Ident value={v.model_version} label="Model version" short={22} /></td>
              <td className="right mono">{fmtPct(v.threshold, 1)}</td>
              <td className="small">
                {v.dataset_label ?? DASH} <Ident value={v.dataset_content_sha256} label="Training data hash" />
              </td>
              <td>{v.support_profile_id !== null ? <Tag tone="success">Support profile</Tag> : <Tag tone="quiet">Disabled</Tag>}</td>
              <td className="xsmall secondary">{fmtRelative(v.registered_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ page

export function ModelOverview() {
  const models = useModels();
  const evaluation = useEvaluation();
  const active = models.data?.find((m) => m.is_active) ?? null;
  const ev = evaluation.data;
  const activeRun = ev?.runs.find((r) => r.run === ev.active_run);

  return (
    <div className="model">
      <PageHeader
        title="Model"
        meta={
          active ? (
            <span>
              {modelLabel(active.model_type, active.feature_set)} · {active.n_columns} inputs · contract v{active.contract_version}
            </span>
          ) : models.isPending ? (
            <Skeleton w={240} />
          ) : (
            <span>No active model</span>
          )
        }
      />

      <div className="notice-banner" role="note">
        <Icon name="shield" size={18} />
        <div>
          <p className="notice-banner__title">Research prototype · not clinically validated</p>
          <p className="small">
            These numbers come from cross-validation within one small retrospective study (CGMacros). They describe how the model ranked
            and calibrated meals it had not seen, from people it had not seen. They are not evidence that it is safe or useful for care.
          </p>
        </div>
      </div>

      <Section id="predicts" eyebrow="Scope" title="What the model estimates">
        {models.isPending ? (
          <Skeleton h={96} />
        ) : models.isError ? (
          <ErrorState error={models.error} what="the model registry" onRetry={() => void models.refetch()} />
        ) : !active ? (
          <EmptyState icon="model" title="No active model">
            Register and activate a model with <code>make m5</code>. The twin still tracks measurements without one, but cannot score risk.
          </EmptyState>
        ) : (
          <div className="scope">
            <dl className="kv">
              <dt>Outcome</dt>
              <dd>Probability of Dexcom glucose above 180 mg/dL within 120 minutes of the meal start, for one logged meal.</dd>
              <dt>Population</dt>
              <dd>Meals of people with prediabetes or type 2 diabetes (by baseline HbA1c), starting at or below 180 mg/dL, with usable macros.</dd>
              <dt>Inputs</dt>
              <dd>{active.n_columns} columns, available at meal start: glucose history, the logged meal, time of day, wearable activity, baseline clinical values and the person&rsquo;s own past responses.</dd>
              <dt>Alert threshold</dt>
              <dd>
                <span className="mono">{fmtPct(active.threshold, 1)}</span>{" "}
                <span className="secondary small">chosen on training folds; above it the twin shows an elevated estimate</span>
              </dd>
              <dt>Not included</dt>
              <dd className="secondary">No insulin or medication, no diagnosis, no dosing, no post-meal information.</dd>
            </dl>
          </div>
        )}
      </Section>

      {evaluation.isPending ? (
        <Loading label="Loading evaluation">
          <Skeleton h={120} />
          <Skeleton h={320} style={{ marginTop: 16 }} />
        </Loading>
      ) : evaluation.isError ? (
        isApiError(evaluation.error, "NOT_FOUND") ? (
          <EmptyState icon="info" title="No evaluation report for the active model" tone="notice">
            The M3 report (<code>data/reports/m3_evaluation.json</code>) is not on this server. Run <code>make m3</code> to produce it.
          </EmptyState>
        ) : isApiError(evaluation.error, "MODEL_INCOMPATIBLE") ? (
          <EmptyState icon="alert" title="Evaluation withheld" tone="notice">
            The evaluation report on this server was computed on different training data than the active model, so its numbers would not
            describe this model.
          </EmptyState>
        ) : (
          <ErrorState error={evaluation.error} what="the evaluation" onRetry={() => void evaluation.refetch()} />
        )
      ) : ev && activeRun ? (
        <>
          <Section
            id="performance"
            eyebrow="Honest metrics"
            title="Performance on new participants"
            description="Grouped cross-validation: every meal was scored by a model that never saw that person."
            aside={<Tag tone="model">{runLabel(ev.active_run)}</Tag>}
          >
            <Headline m={activeRun.target} what="Prediabetes and type 2 diabetes" />
            <details className="disclosure">
              <summary>Normoglycemic participants (outside the scoring population)</summary>
              <Headline m={activeRun.healthy} what="Normoglycemic" />
            </details>
          </Section>

          <div className="model__pair">
            <Section id="calibration" eyebrow="Calibration" title="Do the probabilities mean what they say?">
              {ev.active_calibration_curve.length ? <Calibration bins={ev.active_calibration_curve} /> : <EmptyState title="No calibration bins in the report" />}
            </Section>
            <Section id="threshold" eyebrow="Decisions" title="At the alert threshold">
              <AtThreshold t={ev.active_at_threshold} threshold={active?.threshold ?? null} />
            </Section>
          </div>

          <Section id="folds" eyebrow="Stability" title="Per fold" description="Wide spread between folds is expected with so few participants; it is a reminder of how uncertain the headline numbers are.">
            <Folds ev={ev} />
          </Section>

          <Section id="runs" eyebrow="Alternatives" title="Models compared" description="Every model trained in M3 on the same folds. The active model is the one the twin uses.">
            <Runs ev={ev} />
            <h3 className="subhead">Paired differences</h3>
            <Comparisons ev={ev} />
          </Section>

          {ev.shap_global_importance.length > 0 && (
            <Section
              id="importance"
              eyebrow="Model association"
              title="Inputs the model leans on most"
              description="Mean absolute SHAP contribution across out-of-fold predictions. This shows what the model uses, not what causes glucose to rise."
              aside={<Tag tone="quiet">Not causal</Tag>}
            >
              <Importance items={ev.shap_global_importance} />
            </Section>
          )}

          <Section id="limitations" eyebrow="Read before using" title="Limitations">
            <ul className="limits">
              {ev.limitations.map((l) => (
                <li key={l}>
                  <Icon name="alert" size={14} />
                  <span>{l}</span>
                </li>
              ))}
            </ul>
            <p className="xsmall muted">
              Report data: {ev.dataset_label} · <Ident value={ev.dataset_content_sha256} label="Report data hash" />
            </p>
          </Section>
        </>
      ) : null}

      {models.data && models.data.length > 0 && (
        <Section id="registry" eyebrow="Provenance" title="Registry" description="Every model bundle registered on this server, with the hashes that pin it to its training data and contract.">
          <Registry versions={models.data} />
        </Section>
      )}
    </div>
  );
}
