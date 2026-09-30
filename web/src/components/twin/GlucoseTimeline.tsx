"use client";

import { useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { cx } from "@/lib/cx";
import { fmtPct } from "@/lib/format";
import { THRESHOLD_MGDL } from "@/lib/risk";
import { fmtClock, type Millis } from "@/lib/time";
import { glucoseDomain, linear, linePath, nearest, timeTicks, type Pt } from "@/lib/timeline";
import { useWidth } from "@/lib/useSize";

export interface TimelineMeal {
  id: string;
  t: Millis;
  type: string | null;
  current?: boolean;
  scored?: boolean;
}

export interface TimelinePrediction {
  t0: Millis;
  probability: number | null;
  threshold: number | null;
  horizonMin: number;
}

interface Props {
  points: Pt[];
  start: Millis;
  end: Millis;
  meals: TimelineMeal[];
  /** twin mode: readings after asOf are hidden from the chart until revealed */
  asOf?: Millis;
  /** 0..1: how much of the post-asOf data is revealed (animated by the parent) */
  revealed?: number;
  prediction?: TimelinePrediction;
  height?: number;
  /** one-sentence summary for screen readers */
  summary: string;
  /** recorded peak inside the prediction window, marked once fully revealed */
  peak?: Pt | null;
  onMealSelect?: (id: string) => void;
}

const M = { top: 30, right: 14, bottom: 44, left: 42 };

export function GlucoseTimeline({
  points,
  start,
  end,
  meals,
  asOf,
  revealed = 1,
  prediction,
  height = 300,
  summary,
  onMealSelect,
  peak,
}: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);

  const cutoff = asOf === undefined ? end : asOf + (end - asOf) * revealed;
  const before = useMemo(() => points.filter((p) => asOf === undefined || p.t <= asOf), [points, asOf]);
  const after = useMemo(
    () => (asOf === undefined ? [] : points.filter((p) => p.t > asOf && p.t <= cutoff)),
    [points, asOf, cutoff],
  );
  const visible = useMemo(() => [...before, ...after], [before, after]);

  const w = Math.max(280, width);
  const x = linear([start, end], [M.left, w - M.right]);
  const y = linear(glucoseDomain(points), [height - M.bottom, M.top]);
  const plotBottom = height - M.bottom;
  const ticks = timeTicks(start, end, Math.max(3, Math.floor(w / 90)));
  const yTicks = [70, 180, 250].filter((v) => v >= y.domain[0] && v <= y.domain[1]);

  const pick = (clientX: number, rect: DOMRect) => {
    if (visible.length === 0) return;
    const t = x.invert(clientX - rect.left);
    setActive(nearest(visible, t));
  };
  const onMove = (e: PointerEvent<SVGSVGElement>) => pick(e.clientX, e.currentTarget.getBoundingClientRect());
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (visible.length === 0) return;
    const cur = active ?? visible.length - 1;
    let next = cur;
    if (e.key === "ArrowRight") next = Math.min(visible.length - 1, cur + 1);
    else if (e.key === "ArrowLeft") next = Math.max(0, cur - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = visible.length - 1;
    else if (e.key === "Escape") {
      setActive(null);
      return;
    } else return;
    e.preventDefault();
    setActive(next);
  };

  const hover = active === null ? null : (visible[active] ?? null);
  const hoverAfter = hover !== null && asOf !== undefined && hover.t > asOf;
  const win = prediction
    ? { x0: x(prediction.t0), x1: x(Math.min(end, prediction.t0 + prediction.horizonMin * 60_000)) }
    : null;
  const predTone =
    prediction?.probability != null && prediction.threshold != null
      ? prediction.probability >= prediction.threshold
        ? "risk"
        : "success"
      : "neutral";

  return (
    <div className="tl" ref={ref}>
      <svg
        width={w}
        height={height}
        viewBox={`0 0 ${w} ${height}`}
        className="tl__svg"
        role="img"
        aria-label={summary}
        aria-describedby={hover ? "tl-readout" : undefined}
        tabIndex={0}
        onPointerMove={onMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {/* 70-180 mg/dL target range */}
        <rect className="tl__band" x={M.left} width={w - M.left - M.right} y={y(180)} height={Math.max(0, y(70) - y(180))} />
        {/* grid */}
        {ticks.map((t) => (
          <line key={t} className="tl__grid" x1={x(t)} x2={x(t)} y1={M.top} y2={plotBottom} />
        ))}
        {yTicks.map((v) => (
          <g key={v}>
            <line className={cx("tl__grid", v === THRESHOLD_MGDL && "tl__threshold")} x1={M.left} x2={w - M.right} y1={y(v)} y2={y(v)} />
            <text className="tl__ylabel" x={M.left - 6} y={y(v) + 3.5} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        <text className="tl__thlabel" x={w - M.right} y={y(THRESHOLD_MGDL) - 5} textAnchor="end">
          180 mg/dL · outcome threshold
        </text>

        {/* prediction window: model-estimated event region */}
        {win && prediction && (
          <g className="tl__pred">
            <rect className="tl__window" x={win.x0} y={M.top} width={Math.max(0, win.x1 - win.x0)} height={plotBottom - M.top} />
            <line className="tl__window-edge" x1={win.x1} x2={win.x1} y1={M.top} y2={plotBottom} />
            <g transform={`translate(${Math.min(win.x0 + 6, w - M.right - 150)}, ${M.top - 22})`}>
              <rect className={cx("tl__chip", `tl__chip--${predTone}`)} width={150} height={18} rx={4} />
              <text className="tl__chip-text" x={8} y={12.5}>
                {prediction.probability == null
                  ? "No estimate for this meal"
                  : `Model: ${fmtPct(prediction.probability)} chance > 180`}
              </text>
            </g>
          </g>
        )}

        {/* observed before the twin's moment */}
        {/* drawn on when a new window appears (keyed by the window), not on every re-render */}
        <path key={`line-${start}`} className="tl__line tl__line--draw" pathLength={1} d={linePath(before, x, y)} />
        {/* observed after the moment (revealed progressively) */}
        {after.length > 0 && (
          <path className="tl__line tl__line--after" d={linePath(before.length ? [before[before.length - 1] as Pt, ...after] : after, x, y)} />
        )}

        {/* the twin's moment */}
        {asOf !== undefined && asOf >= start && asOf <= end && (
          <g>
            <line className="tl__asof" x1={x(asOf)} x2={x(asOf)} y1={M.top - 4} y2={plotBottom} />
            <text className="tl__asof-label" x={x(asOf) + 4} y={plotBottom - 6}>
              {revealed < 1 ? "twin's view ends" : "twin's moment"}
            </text>
          </g>
        )}

        {/* x axis */}
        <line className="tl__axis" x1={M.left} x2={w - M.right} y1={plotBottom} y2={plotBottom} />
        {ticks.map((t) => (
          <text
            key={t}
            className="tl__xlabel"
            x={x(t)}
            y={plotBottom + 30}
            textAnchor={x(t) > w - M.right - 18 ? "end" : x(t) < M.left + 18 ? "start" : "middle"}
          >
            {fmtClock(t)}
          </text>
        ))}

        {/* meals */}
        {meals
          .filter((m) => m.t >= start && m.t <= end)
          .map((m, i) => (
            <g
              key={m.id}
              className={cx("tl__meal", m.current && "tl__meal--current", onMealSelect && "tl__meal--link")}
              transform={`translate(${x(m.t)}, ${plotBottom + 11})`}
              onClick={onMealSelect ? () => onMealSelect(m.id) : undefined}
            >
              <title>{`${m.type ?? "Meal"} at ${fmtClock(m.t)}${m.scored === false ? " (not scored)" : ""}`}</title>
              <path className="tl__meal-mark" style={{ animationDelay: `${120 + i * 40}ms` }} d="M0,-6 L5,3 L-5,3 Z" />
            </g>
          ))}

        {/* recorded peak in the prediction window: a measurement, shown only once revealed */}
        {peak && revealed >= 1 && (
          <g className="tl__peak" transform={`translate(${x(peak.t)}, ${y(peak.v)})`} pointerEvents="none">
            <circle r={4.5} />
            <text x={0} y={-10} textAnchor="middle">
              {`peak ${Math.round(peak.v)}`}
            </text>
          </g>
        )}

        {/* crosshair */}
        {hover && (
          <g pointerEvents="none">
            <line className="tl__cross" x1={x(hover.t)} x2={x(hover.t)} y1={M.top} y2={plotBottom} />
            <circle className={cx("tl__dot", hoverAfter && "tl__dot--after")} cx={x(hover.t)} cy={y(hover.v)} r={4} />
          </g>
        )}
      </svg>

      {hover && (
        <div
          id="tl-readout"
          className="tl__tip"
          style={{
            left: Math.min(Math.max(x(hover.t), 70), w - 90),
            top: Math.max(4, y(hover.v) - 58),
          }}
        >
          <span className="mono tl__tip-time">{fmtClock(hover.t)}</span>
          <span className="tl__tip-val">
            <span className="mono">{Math.round(hover.v)}</span> mg/dL
          </span>
          <span className="tl__tip-src">{hoverAfter ? "Measured later · not seen by the twin" : "Measured · native Dexcom"}</span>
        </div>
      )}
    </div>
  );
}
