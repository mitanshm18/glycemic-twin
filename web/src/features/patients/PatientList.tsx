"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Segmented } from "@/components/ui/Segmented";
import { Loading, Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/StateMessage";
import { Tag } from "@/components/ui/Tag";
import { useModels, usePatientsOverview } from "@/lib/api/queries";
import type { PatientOverview, Phase } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { fmtPct } from "@/lib/format";
import { twinHref } from "@/lib/patientContext";
import { GROUP_LABEL, PHASE_LABEL, PHASE_TONE, riskView } from "@/lib/risk";
import { fmtDate, fmtDateTime, fmtRelative, parseNaive } from "@/lib/time";

type Group = "all" | "target" | "healthy";
type EstimateFilter = "all" | "above" | "below" | "none";
type SortKey = "ref" | "group" | "meals" | "risk" | "activity" | "data";

const TARGET = new Set(["prediabetes", "T2D"]);

function sortValue(p: PatientOverview, k: SortKey): string | number {
  switch (k) {
    case "ref":
      return p.id;
    case "group":
      return p.glycemic_group;
    case "meals":
      return p.eligible_meals;
    case "risk":
      return p.latest_state?.risk_status === "scored" ? (p.latest_state.probability ?? -1) : -1;
    case "activity":
      return p.latest_state?.created_at ?? "";
    case "data":
      return p.data_to ?? "";
  }
}

function SortHeader({
  k,
  label,
  sort,
  onSort,
  align,
}: {
  k: SortKey;
  label: string;
  sort: { key: SortKey; dir: 1 | -1 };
  onSort: (k: SortKey) => void;
  align?: "right";
}) {
  const active = sort.key === k;
  return (
    <th scope="col" className={align} aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-btn" data-active={active} onClick={() => onSort(k)}>
        {label}
        <Icon name={active ? (sort.dir === 1 ? "sortAsc" : "sortDesc") : "sortNone"} />
      </button>
    </th>
  );
}

export function PatientList() {
  const q = usePatientsOverview();
  const models = useModels();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState<Group>("target");
  const [phase, setPhase] = useState<Phase | "all" | "none">("all");
  const [estimate, setEstimate] = useState<EstimateFilter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "ref", dir: 1 });
  const searchRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  // each estimate is judged against the threshold of the model version that produced it
  const thresholdOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const v of models.data ?? []) m.set(v.model_version, v.threshold);
    return m;
  }, [models.data]);
  const status = (p: PatientOverview): "above" | "below" | "none" => {
    const st = p.latest_state;
    if (!st || st.risk_status !== "scored" || st.probability === null) return "none";
    const thr = st.model_version ? thresholdOf.get(st.model_version) : undefined;
    if (thr === undefined) return "none";
    return st.probability >= thr ? "above" : "below";
  };

  // "/" focuses search (not while typing elsewhere)
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const all = useMemo(() => q.data ?? [], [q.data]);
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    const out = all.filter((p) => {
      if (group === "target" && !TARGET.has(p.glycemic_group)) return false;
      if (group === "healthy" && p.glycemic_group !== "healthy") return false;
      if (s && !`${p.external_ref} ${p.id} ${GROUP_LABEL[p.glycemic_group] ?? ""}`.toLowerCase().includes(s)) return false;
      const st = p.latest_state;
      if (phase === "none" && st) return false;
      if (phase !== "all" && phase !== "none" && st?.lifecycle_phase !== phase) return false;
      if (estimate !== "all" && status(p) !== estimate) return false;
      return true;
    });
    return out.sort((a, b) => {
      const va = sortValue(a, sort.key);
      const vb = sortValue(b, sort.key);
      return (va < vb ? -1 : va > vb ? 1 : a.id - b.id) * sort.dir;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, search, group, phase, estimate, sort, thresholdOf]);

  const onSort = (k: SortKey) =>
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === 1 ? -1 : 1 } : { key: k, dir: k === "risk" || k === "activity" ? -1 : 1 }));

  const counts = useMemo(
    () => ({
      all: all.length,
      target: all.filter((p) => TARGET.has(p.glycemic_group)).length,
      healthy: all.filter((p) => p.glycemic_group === "healthy").length,
      computed: all.filter((p) => p.latest_state).length,
    }),
    [all],
  );

  const filtered = search.trim() !== "" || phase !== "all" || estimate !== "all";
  const clear = () => {
    setSearch("");
    setPhase("all");
    setEstimate("all");
  };

  // Arrow keys move between rows (each row's name link is its focus target); Enter opens it.
  const onRowKeys = (e: KeyboardEvent<HTMLTableSectionElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const links = Array.from(bodyRef.current?.querySelectorAll<HTMLAnchorElement>("a.plist__name") ?? []);
    const i = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (i < 0) return;
    e.preventDefault();
    const next = e.key === "Home" ? 0 : e.key === "End" ? links.length - 1 : Math.max(0, Math.min(links.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
    links[next]?.focus();
  };

  return (
    <div className="patients">
      <PageHeader
        title="Patients"
        meta={
          q.data ? (
            <span>
              {counts.all} participants · {counts.target} with prediabetes or type 2 diabetes · twin computed for {counts.computed}
            </span>
          ) : (
            <Skeleton w={300} />
          )
        }
      />

      <div className="toolbar" role="search" aria-label="Filter patients">
        <label className="search toolbar__search">
          <Icon name="search" size={14} />
          <span className="sr-only">Search patients</span>
          <input
            ref={searchRef}
            className="input"
            placeholder="Search participants"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setSearch("")}
            aria-keyshortcuts="/"
          />
          <kbd className="search__kbd" aria-hidden="true">
            /
          </kbd>
        </label>
        <Segmented<Group>
          label="Population"
          value={group}
          onChange={setGroup}
          options={[
            { value: "target", label: <>Prediabetes + T2D <span className="seg__count">{counts.target}</span></> },
            { value: "healthy", label: <>Normoglycemic <span className="seg__count">{counts.healthy}</span></> },
            { value: "all", label: <>All <span className="seg__count">{counts.all}</span></> },
          ]}
        />
        <label className="toolbar__select">
          <span className="sr-only">Twin lifecycle</span>
          <select className="select" value={phase} onChange={(e) => setPhase(e.target.value as Phase | "all" | "none")}>
            <option value="all">Any lifecycle</option>
            <option value="COLD_START">Cold start</option>
            <option value="WARMING">Warming up</option>
            <option value="PERSONALIZED">Personalized</option>
            <option value="none">Twin not computed</option>
          </select>
        </label>
        <label className="toolbar__select toolbar__sort">
          <span className="sr-only">Sort by</span>
          <select
            className="select"
            value={`${sort.key}:${sort.dir}`}
            onChange={(e) => {
              const [key, dir] = e.target.value.split(":");
              setSort({ key: key as SortKey, dir: Number(dir) === -1 ? -1 : 1 });
            }}
          >
            <option value="ref:1">Sort: participant</option>
            <option value="risk:-1">Sort: highest estimate first</option>
            <option value="meals:-1">Sort: most scorable meals</option>
            <option value="meals:1">Sort: fewest scorable meals</option>
            <option value="activity:-1">Sort: most recent twin</option>
            <option value="data:-1">Sort: latest data</option>
          </select>
        </label>
        <label className="toolbar__select">
          <span className="sr-only">Last model estimate</span>
          <select className="select" value={estimate} onChange={(e) => setEstimate(e.target.value as EstimateFilter)}>
            <option value="all">Any estimate</option>
            <option value="above">At or above threshold</option>
            <option value="below">Below threshold</option>
            <option value="none">No scored estimate</option>
          </select>
        </label>
      </div>

      {q.data && all.length > 0 && (
        <p className="plist__count xsmall secondary" aria-live="polite">
          Showing {rows.length} of {group === "all" ? counts.all : group === "target" ? counts.target : counts.healthy}
          {filtered && (
            <Button size="sm" variant="ghost" onClick={clear}>
              <Icon name="x" size={12} /> Clear filters
            </Button>
          )}
        </p>
      )}

      {q.isPending ? (
        <Loading label="Loading patients">
          <div className="stack plist-skeleton">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} h={40} />
            ))}
          </div>
        </Loading>
      ) : q.isError ? (
        <ErrorState error={q.error} what="the patient list" onRetry={() => void q.refetch()} />
      ) : all.length === 0 ? (
        <EmptyState icon="patients" title="No patients ingested yet">
          The database has no participants. Load the processed CGMacros data with <code>make m5</code>, then reload.
        </EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState icon="search" title="No patients match these filters" actions={<Button size="sm" onClick={clear}>Clear filters</Button>}>
          Nothing matches the current search and filters.
        </EmptyState>
      ) : (
        <div className="table-wrap enter">
          <table className="table table--interactive plist">
            <caption className="sr-only">
              Participants. Use the arrow keys to move between rows and Enter to open a participant&rsquo;s twin.
            </caption>
            <thead>
              <tr>
                <SortHeader k="ref" label="Participant" sort={sort} onSort={onSort} />
                <SortHeader k="group" label="Group" sort={sort} onSort={onSort} />
                <SortHeader k="meals" label="Scorable meals" sort={sort} onSort={onSort} align="right" />
                <th scope="col">Twin</th>
                <SortHeader k="risk" label="Last model estimate" sort={sort} onSort={onSort} />
                <SortHeader k="data" label="Data through" sort={sort} onSort={onSort} />
                <th scope="col" className="plist__go-col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody ref={bodyRef} onKeyDown={onRowKeys}>
              {rows.map((p) => {
                const st = p.latest_state;
                const s = status(p);
                const view = st ? riskView(st.risk_status, st.probability, null) : null;
                const href = twinHref(p.id);
                return (
                  <tr key={p.id} onClick={() => router.push(href)}>
                    <td data-label="Participant">
                      <Link href={href} className="plist__name" onClick={(e) => e.stopPropagation()}>
                        {p.external_ref}
                      </Link>
                    </td>
                    <td data-label="Group">
                      <span className={cx("group-dot", `group-dot--${p.glycemic_group}`)} aria-hidden="true" />
                      {GROUP_LABEL[p.glycemic_group] ?? p.glycemic_group}
                    </td>
                    <td data-label="Scorable meals" className="right mono">
                      {p.eligible_meals}
                      <span className="muted"> / {p.meals}</span>
                    </td>
                    <td data-label="Twin">
                      {st ? (
                        <Tag tone={PHASE_TONE[st.lifecycle_phase]}>{PHASE_LABEL[st.lifecycle_phase]}</Tag>
                      ) : (
                        <span className="muted xsmall">Not computed yet</span>
                      )}
                    </td>
                    <td data-label="Last model estimate">
                      {st && st.risk_status === "scored" ? (
                        <span className="plist__est">
                          <span className="plist__pct mono">{fmtPct(st.probability)}</span>
                          {s !== "none" && (
                            <Tag tone={s === "above" ? "risk" : "success"} icon={s === "above" ? "arrowUp" : "arrowDown"}>
                              {s === "above" ? "Above threshold" : "Below threshold"}
                            </Tag>
                          )}
                          <span className="plist__when xsmall muted">{fmtDateTime(parseNaive(st.as_of))}</span>
                        </span>
                      ) : st ? (
                        <span className="muted xsmall">{view?.short}</span>
                      ) : (
                        <span className="muted xsmall">—</span>
                      )}
                    </td>
                    <td data-label="Data through" className="plist__fresh">
                      {p.data_to ? <span className="mono xsmall">{fmtDate(parseNaive(p.data_to))}</span> : <span className="muted xsmall">no time series</span>}
                      {st && <span className="xsmall muted">twin {fmtRelative(st.created_at)}</span>}
                    </td>
                    <td className="plist__go" aria-hidden="true">
                      <Icon name="chevronRight" size={14} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="xsmall muted plist__foot">
        Groups come from baseline HbA1c and are not a diagnosis. The last model estimate is the most recent twin snapshot, judged
        against its own model&rsquo;s alert threshold. CGMacros is a retrospective study, so &ldquo;data through&rdquo; is when
        that participant&rsquo;s recording ends; freshness at any moment is shown inside the twin.
      </p>
    </div>
  );
}
