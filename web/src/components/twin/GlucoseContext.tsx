"use client";

import { useMemo, useState, type PointerEvent } from "react";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/StateMessage";
import { useCgm } from "@/lib/api/queries";
import type { TwinState } from "@/lib/api/types";
import { fmtNum } from "@/lib/format";
import { fmtClock, fmtDuration, MINUTE, parseNaive, toNaiveIso } from "@/lib/time";
import { extent, linear, linePath, nearest, seenBy, toPoints } from "@/lib/timeline";
import { useWidth } from "@/lib/useSize";

export const CONTEXT_MIN = 90;

/**
 * The 90 minutes of native Dexcom readings that lead up to the twin's moment, opened from the
 * measured reading. Readings after `as_of` are filtered out here as well as requested away, so
 * this panel can never show the twin something it could not have seen.
 */
export function GlucoseContext({ state, id, onShowTimeline, onClose }: { state: TwinState; id: string; onShowTimeline: (t: number) => void; onClose: () => void }) {
  const asOf = parseNaive(state.as_of);
  const from = asOf - CONTEXT_MIN * MINUTE;
  const cgm = useCgm(state.patient_id, toNaiveIso(from), toNaiveIso(asOf));
  const pts = useMemo(() => seenBy(toPoints(cgm.data ?? []), asOf).filter((p) => p.t >= from), [cgm.data, asOf, from]);
  const last = pts.at(-1) ?? null;
  const ext = extent(pts);
  const phys = state.current_physiology;

  const [ref, width] = useWidth<HTMLDivElement>(320);
  const h = 88;
  const m = { l: 4, r: 36, t: 10, b: 16 };
  const lo = Math.min(70, ext?.min.v ?? 70) - 5;
  const hi = Math.max(180, ext?.max.v ?? 180) + 5;
  const x = linear([from, asOf], [m.l, width - m.r]);
  const y = linear([lo, hi], [h - m.b, m.t]);
  const [idx, setIdx] = useState<number | null>(null);
  const read = idx === null ? last : (pts[idx] ?? last);
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    if (pts.length === 0) return;
    const r = e.currentTarget.getBoundingClientRect();
    setIdx(nearest(pts, x.invert(e.clientX - r.left)));
  };

  return (
    <div id={id} className="gctx" role="region" aria-label={`Native Dexcom readings in the ${CONTEXT_MIN} minutes before the twin's moment`}>
      <div className="gctx__head">
        <span className="gctx__title">
          Last {CONTEXT_MIN} min before {fmtClock(asOf)}
          <span className="gctx__src">native Dexcom · nothing after the twin&rsquo;s moment</span>
        </span>
        <button type="button" className="gctx__close" onClick={onClose} aria-label="Close surrounding readings">
          <Icon name="x" size={14} />
        </button>
      </div>

      {cgm.isPending ? (
        <Skeleton h={h} />
      ) : cgm.isError ? (
        <ErrorState error={cgm.error} what="the surrounding readings" onRetry={() => void cgm.refetch()} />
      ) : pts.length === 0 ? (
        <p className="small secondary">No native readings were recorded in this stretch.</p>
      ) : (
        <>
          <div ref={ref} className="gctx__plot">
            <svg
              width={width}
              height={h}
              viewBox={`0 0 ${width} ${h}`}
              onPointerMove={onMove}
              onPointerLeave={() => setIdx(null)}
              aria-hidden="true"
            >
              <rect className="gctx__band" x={m.l} width={width - m.l - m.r} y={y(180)} height={Math.max(0, y(70) - y(180))} />
              <path className="gctx__line" d={linePath(pts, x, y)} />
              {pts.map((p) => (
                <circle key={p.t} className="gctx__pt" cx={x(p.t)} cy={y(p.v)} r={1.6} />
              ))}
              {read && (
                <g className="gctx__read" style={{ transform: `translate(${x(read.t)}px, ${y(read.v)}px)` }}>
                  <circle r={3.5} />
                </g>
              )}
              <line className="gctx__now" x1={x(asOf)} x2={x(asOf)} y1={m.t - 4} y2={h - m.b} />
              <text className="gctx__axis" x={m.l} y={h - 3}>
                {fmtClock(from)}
              </text>
              <text className="gctx__axis" x={x(asOf)} y={h - 3} textAnchor="end">
                {fmtClock(asOf)}
              </text>
              <text className="gctx__axis" x={width - m.r + 4} y={y(180) + 3}>
                180
              </text>
              <text className="gctx__axis" x={width - m.r + 4} y={y(70) + 3}>
                70
              </text>
            </svg>
            {read && (
              <span className="gctx__readout mono" aria-hidden="true">
                {fmtClock(read.t)} · {Math.round(read.v)} mg/dL
              </span>
            )}
          </div>
          <dl className="gctx__facts">
            <div>
              <dt>Latest reading</dt>
              <dd className="mono">{last ? `${Math.round(last.v)} mg/dL at ${fmtClock(last.t)}` : "—"}</dd>
            </div>
            <div>
              <dt>Reading age</dt>
              <dd className="mono">{phys.glucose_age_min === null ? "—" : `${fmtDuration(phys.glucose_age_min * MINUTE)} before ${fmtClock(asOf)}`}</dd>
            </div>
            <div>
              <dt>Trend, 15 / 30 min</dt>
              <dd className="mono">
                {fmtNum(phys.slope_15_mgdl_per_min, 1)} / {fmtNum(phys.slope_30_mgdl_per_min, 1)} mg/dL/min
              </dd>
            </div>
            <div>
              <dt>Range, {CONTEXT_MIN} min</dt>
              <dd className="mono">{ext ? `${Math.round(ext.min.v)}–${Math.round(ext.max.v)} mg/dL` : "—"}</dd>
            </div>
            <div>
              <dt>Readings</dt>
              <dd className="mono">{pts.length}</dd>
            </div>
          </dl>
          <p className="sr-only">
            {pts.length} readings from {fmtClock(pts[0]!.t)} to {fmtClock(last!.t)}, between {Math.round(ext!.min.v)} and {Math.round(ext!.max.v)} mg/dL.
          </p>
        </>
      )}

      <div className="gctx__actions">
        <button type="button" className="gctx__link" onClick={() => onShowTimeline(last?.t ?? asOf)}>
          See on full timeline <Icon name="arrowRight" size={12} />
        </button>
      </div>
    </div>
  );
}
