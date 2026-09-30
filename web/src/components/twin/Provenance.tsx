"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Disclosure } from "@/components/ui/Disclosure";
import { Icon } from "@/components/ui/Icon";
import { Ident } from "@/components/ui/Ident";
import { Sheet } from "@/components/ui/Sheet";
import type { TwinState } from "@/lib/api/types";
import { fmtPct, modelLabel } from "@/lib/format";
import { fmtDateTime, parseNaive } from "@/lib/time";

function ts(v: string | null) {
  return v ? <span className="mono">{fmtDateTime(parseNaive(v))}</span> : <span className="muted">—</span>;
}

export function Provenance({ state }: { state: TwinState }) {
  const [open, setOpen] = useState(false);
  const p = state.provenance;
  const m = p.model;
  return (
    <div className="prov">
      <dl className="prov__strip">
        <div>
          <dt>State</dt>
          <dd>
            <Ident value={state.state_id} label="State ID" />
          </dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{m ? <Ident value={m.model_version} label="Model version" short={22} /> : <span className="muted">none</span>}</dd>
        </div>
        <div>
          <dt>Source data</dt>
          <dd>
            <Ident value={p.record_sha256} label="Source record hash" />
          </dd>
        </div>
        <div>
          <dt>Latest source time</dt>
          <dd>{ts(p.max_source_ts)}</dd>
        </div>
      </dl>
      <p className="xsmall secondary">
        Built from {p.cgm_native_readings_used.toLocaleString()} native CGM readings, {p.wearable_minutes_used.toLocaleString()} wearable
        minutes and {p.meals_logged_used} logged meals, all at or before {fmtDateTime(parseNaive(state.as_of))}. The ID is a hash of the
        whole state: the same data and moment always give the same ID.
      </p>
      <div>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Icon name="fingerprint" size={14} /> View provenance
        </Button>
      </div>

      <Sheet open={open} onClose={() => setOpen(false)} title="Provenance">
        <dl className="kv">
          <dt className="kv__group">Twin state</dt>
          <dd hidden />
          <dt>State ID</dt>
          <dd><Ident value={state.state_id} label="State ID" short={0} /></dd>
          <dt>Schema / engine</dt>
          <dd className="mono">{state.schema_version} · engine {p.engine_version}</dd>
          <dt>Moment (as_of)</dt>
          <dd>{ts(state.as_of)}</dd>
          <dt>Latest source time</dt>
          <dd>{ts(p.max_source_ts)}</dd>

          <dt className="kv__group">Source data</dt>
          <dd hidden />
          <dt>Source</dt>
          <dd>{p.source}</dd>
          <dt>Record hash</dt>
          <dd><Ident value={p.record_sha256} label="Record hash" short={0} /></dd>
          <dt>CGM readings</dt>
          <dd className="mono">{p.cgm_native_readings_used.toLocaleString()} native · last {ts(state.freshness.last_cgm_native_at)}</dd>
          <dt>Wearable minutes</dt>
          <dd className="mono">{p.wearable_minutes_used.toLocaleString()} · last {ts(state.freshness.last_wearable_at)}</dd>
          <dt>Meals</dt>
          <dd className="mono">{p.meals_logged_used} logged · current {p.current_meal_id ?? "none"}</dd>
          <dt>Personal evidence</dt>
          <dd>
            {p.closed_meal_ids_used.length} closed meal windows
            {p.closed_meal_ids_used.length > 0 && (
              <Disclosure label="Show meal IDs">
                <p className="mono xsmall secondary">{p.closed_meal_ids_used.join(", ")}</p>
              </Disclosure>
            )}
          </dd>

          <dt className="kv__group">Model</dt>
          <dd hidden />
          {m ? (
            <>
              <dt>Model</dt>
              <dd>{modelLabel(m.model_name, m.feature_set)} · {m.n_columns} inputs · threshold {fmtPct(m.threshold, 1)}</dd>
              <dt>Version</dt>
              <dd><Ident value={m.model_version} label="Model version" short={0} /></dd>
              <dt>Contract</dt>
              <dd>v{m.contract_version} · <Ident value={m.contract_sha256} label="Contract hash" /></dd>
              <dt>Features / labels</dt>
              <dd>
                <Ident value={m.features_sha256} label="features.v1 hash" /> <Ident value={m.labels_sha256} label="labels.v1 hash" />
              </dd>
              <dt>Training data</dt>
              <dd>
                {m.dataset_label ?? "—"}
                {m.dataset_content_sha256 && (
                  <>
                    <br />
                    <Ident value={m.dataset_content_sha256} label="Training data hash" />
                  </>
                )}
              </dd>
              <dt>Bundle created</dt>
              <dd className="mono">{m.created_utc ?? "—"}</dd>
            </>
          ) : (
            <>
              <dt>Model</dt>
              <dd className="muted">No model produced this state.</dd>
            </>
          )}

          <dt className="kv__group">Configuration</dt>
          <dd hidden />
          {Object.entries(p.config_sha256).map(([k, v]) => (
            <FragmentRow key={k} name={`${k} config`} value={v} />
          ))}
        </dl>
        <p className="xsmall muted prov__disclaimer">{state.disclaimer}</p>
      </Sheet>
    </div>
  );
}

function FragmentRow({ name, value }: { name: string; value: string }) {
  return (
    <>
      <dt>{name}</dt>
      <dd>
        <Ident value={value} label={name} />
      </dd>
    </>
  );
}
