"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import { Icon } from "@/components/ui/Icon";
import { cx } from "@/lib/cx";
import { fmtNum, fmtPct } from "@/lib/format";
import { useReducedMotion } from "@/lib/motion";
import { THRESHOLD_MGDL } from "@/lib/risk";
import { fmtClock, MINUTE, type Millis } from "@/lib/time";
import { deltaFromPrevious, glucoseDomain, linear, linePath, nearest, timeTicks, type Pt } from "@/lib/timeline";
import { useWidth } from "@/lib/useSize";

export interface TimelineMeal {
  id: string;
  t: Millis;
  type: string | null;
  current?: boolean;
  scored?: boolean;
  /** logged macros, shown as recorded (null = not logged) */
  carbs_g?: number | null;
  fiber_g?: number | null;
  protein_g?: number | null;
  fat_g?: number | null;
  calories_kcal?: number | null;
  macrosValid?: boolean;
}

export interface TimelinePrediction {
  t0: Millis;
  probability: number | null;
  threshold: number | null;
  horizonMin: number;
}

/** A stretch of time to bring forward (a meal's response window, or the evidence for an input). */
export interface TimelineFocus {
  from: Millis;
  to: Millis;
  label: string;
  /** meals inside the range are emphasised too (earlier meals as evidence) */
  meals?: boolean;
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
  /** draw attention to the peak (its step in the reveal is being explored) */
  peakEmphasis?: boolean;
  /** show the reveal's leading edge while the clinician scrubs through it */
  scrubbing?: boolean;
  /** evidence from elsewhere on the page to bring forward */
  focus?: TimelineFocus | null;
  onClearFocus?: () => void;
  /** pin the crosshair at a time (n changes on every request) */
  pin?: { t: Millis; n: number } | null;
  onMealSelect?: (id: string) => void;
}

const M = { top: 30, right: 14, bottom: 44, left: 42 };
const PAD_TOP = 8; // .tl padding-top: SVG coordinates start this far below the container's top
const RESPONSE_MIN = 120;

function mealLabel(m: TimelineMeal) {
  return `${m.type ? m.type.charAt(0).toUpperCase() + m.type.slice(1) : "Meal"} at ${fmtClock(m.t)}`;
}

/**
 * Native Dexcom glucose around a meal, as an instrument to explore: a crosshair that glides between
 * readings, meal markers that open their details and bring their two-hour response forward, and a
 * cross-fade (not a redraw) when the twin moves to another moment. Every value drawn is a recorded
 * reading; readings after the twin's moment stay hidden until revealed.
 */
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
  peakEmphasis,
  scrubbing,
  focus,
  onClearFocus,
  pin,
}: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const reduced = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const [pinned, setPinned] = useState(false);
  const [glide, setGlide] = useState(false);
  const [mealFocus, setMealFocus] = useState<string | null>(null);
  const lastPointer = useRef<string>("mouse");
  const markerRefs = useRef(new Map<string, HTMLButtonElement>());

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
  const inRange = meals.filter((m) => m.t >= start && m.t <= end).sort((a, b) => a.t - b.t);

  /* ---------------------------------------------------------------- crosshair */

  const pick = (clientX: number, rect: DOMRect) => {
    if (visible.length === 0) return;
    setActive(nearest(visible, x.invert(clientX - rect.left)));
  };
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    lastPointer.current = e.pointerType;
    if (e.pointerType === "mouse") return;
    // touch / pen: a tap pins the crosshair, a horizontal drag scrubs it
    setPinned(true);
    pick(e.clientX, e.currentTarget.getBoundingClientRect());
  };
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    if (e.pointerType === "mouse" && pinned) return;
    if (e.pointerType !== "mouse" && e.buttons === 0) return;
    pick(e.clientX, e.currentTarget.getBoundingClientRect());
  };
  const onClick = (e: MouseEvent<SVGSVGElement>) => {
    if (lastPointer.current !== "mouse") return;
    // a click keeps the reading in place so it can be read without holding the pointer still
    if (pinned) setPinned(false);
    else {
      setPinned(true);
      pick(e.clientX, e.currentTarget.getBoundingClientRect());
    }
  };
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
      setPinned(false);
      onClearFocus?.();
      return;
    } else return;
    e.preventDefault();
    setActive(next);
  };

  // pinned from elsewhere ("See on full timeline"): place the crosshair and take focus
  useEffect(() => {
    if (!pin || visible.length === 0) return;
    setActive(nearest(visible, pin.t));
    setPinned(true);
    svgRef.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin?.n]);

  // a tap anywhere else lets go of a pinned reading or meal
  useEffect(() => {
    if (!pinned && !mealFocus) return;
    const away = (e: globalThis.PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setPinned(false);
        setActive(null);
        setMealFocus(null);
      }
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [pinned, mealFocus, ref]);

  // the crosshair glides between readings once it is showing (it appears in place, never from a corner)
  const showing = active !== null;
  useEffect(() => {
    if (!showing) {
      setGlide(false);
      return;
    }
    const r = requestAnimationFrame(() => setGlide(true));
    return () => cancelAnimationFrame(r);
  }, [showing]);

  // a new window: keep the data index in range
  useEffect(() => {
    setActive(null);
    setPinned(false);
    setMealFocus(null);
  }, [start]);

  const hi = active === null ? null : Math.min(active, visible.length - 1);
  const hover = hi === null ? null : (visible[hi] ?? null);
  const hoverAfter = hover !== null && asOf !== undefined && hover.t > asOf;
  const delta = hi === null ? null : deltaFromPrevious(visible, hi);

  /* ---------------------------------------------------------------- cross-fade between windows */

  const beforeD = linePath(before, x, y);
  const afterD = after.length > 0 ? linePath(before.length ? [before[before.length - 1] as Pt, ...after] : after, x, y) : "";
  const [initialStart] = useState(start);
  const moved = useRef(false);
  const prevDrawing = useRef<{ start: Millis; d: string } | null>(null);
  const [ghost, setGhost] = useState<{ d: string; key: Millis } | null>(null);
  useEffect(() => {
    const prev = prevDrawing.current;
    let t: number | undefined;
    if (prev && prev.start !== start) moved.current = true;
    if (prev && prev.start !== start && !reduced) {
      setGhost({ d: prev.d, key: prev.start });
      t = window.setTimeout(() => setGhost(null), 420);
    }
    prevDrawing.current = { start, d: beforeD + afterD };
    return () => window.clearTimeout(t);
    // only a change of window starts a cross-fade; the reveal extending the line does not
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);
  useEffect(() => {
    if (prevDrawing.current) prevDrawing.current.d = beforeD + afterD;
  }, [beforeD, afterD]);
  const firstWindow = start === initialStart && !moved.current;

  /* ---------------------------------------------------------------- focus (meal response / evidence) */

  const focusedMeal = inRange.find((m) => m.id === mealFocus) ?? null;
  const range: TimelineFocus | null = focusedMeal
    ? { from: focusedMeal.t, to: focusedMeal.t + RESPONSE_MIN * MINUTE, label: `${mealLabel(focusedMeal)}: 2-hour response` }
    : (focus ?? null);
  const rx0 = range ? x(Math.max(start, range.from)) : 0;
  const rx1 = range ? x(Math.min(end, range.to)) : 0;
  const inFocus = (t: Millis) => !range || (t >= range.from && t <= range.to);

  const moveMeal = (id: string, d: number) => {
    const i = inRange.findIndex((m) => m.id === id);
    const next = inRange[i + d];
    if (next) markerRefs.current.get(next.id)?.focus();
  };

  const win = prediction ? { x0: x(prediction.t0), x1: x(Math.min(end, prediction.t0 + prediction.horizonMin * 60_000)) } : null;
  const predTone =
    prediction?.probability != null && prediction.threshold != null
      ? prediction.probability >= prediction.threshold
        ? "risk"
        : "success"
      : "neutral";
  const head = scrubbing && asOf !== undefined ? (after.at(-1) ?? before.at(-1) ?? null) : null;

  return (
    <div className={cx("tl", range && "is-focusing", glide && !reduced && "is-gliding", pinned && "is-pinned")} ref={ref}>
      <svg
        ref={svgRef}
        width={w}
        height={height}
        viewBox={`0 0 ${w} ${height}`}
        className="tl__svg"
        role="img"
        aria-label={summary}
        aria-describedby={hover ? "tl-readout" : undefined}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onMove}
        onPointerLeave={() => !pinned && setActive(null)}
        onClick={onClick}
        onKeyDown={onKey}
        onBlur={() => !pinned && setActive(null)}
      >
        <defs>
          <clipPath id="tl-focus-clip">
            <rect x={rx0} y={0} width={Math.max(0, rx1 - rx0)} height={height} />
          </clipPath>
        </defs>
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
                {prediction.probability == null ? "No estimate for this meal" : `Model: ${fmtPct(prediction.probability)} chance > 180`}
              </text>
            </g>
          </g>
        )}

        {/* the focused stretch: shaded, labelled; the rest of the line steps back */}
        {range && rx1 > rx0 && (
          <g className="tl__focus" pointerEvents="none">
            <rect x={rx0} y={M.top} width={rx1 - rx0} height={plotBottom - M.top} />
            <line x1={rx0} x2={rx0} y1={M.top} y2={plotBottom} />
            <line x1={rx1} x2={rx1} y1={M.top} y2={plotBottom} />
          </g>
        )}

        {/* the previous window, fading out while the new one fades in */}
        {ghost && <path key={`ghost-${ghost.key}`} className="tl__line tl__line--ghost" d={ghost.d} />}

        {/* observed before the twin's moment: drawn on the first time, cross-faded afterwards */}
        <path key={`line-${start}`} className={cx("tl__line tl__line--base", firstWindow ? "tl__line--draw" : "tl__line--fade")} pathLength={firstWindow ? 1 : undefined} d={beforeD} />
        {/* observed after the moment (revealed progressively) */}
        {afterD && <path className="tl__line tl__line--after tl__line--base" d={afterD} />}
        {range && (
          <g clipPath="url(#tl-focus-clip)" pointerEvents="none">
            <path className="tl__line tl__line--lit" d={beforeD} />
            {afterD && <path className="tl__line tl__line--after tl__line--lit" d={afterD} />}
          </g>
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
          <text key={t} className="tl__xlabel" x={x(t)} y={plotBottom + 30} textAnchor={x(t) > w - M.right - 18 ? "end" : x(t) < M.left + 18 ? "start" : "middle"}>
            {fmtClock(t)}
          </text>
        ))}

        {/* the reveal's leading edge while scrubbing: the latest recorded reading shown so far */}
        {head && (
          <g className="tl__head" pointerEvents="none">
            <line x1={x(cutoff)} x2={x(cutoff)} y1={M.top} y2={plotBottom} />
            <circle cx={x(head.t)} cy={y(head.v)} r={4} />
            <text x={x(head.t)} y={y(head.v) - 9} textAnchor="middle">
              {Math.round(head.v)}
            </text>
          </g>
        )}

        {/* recorded peak in the prediction window: a measurement, shown only once revealed */}
        {peak && revealed >= 1 && (
          <g className={cx("tl__peak", peakEmphasis && "is-emphasized")} transform={`translate(${x(peak.t)}, ${y(peak.v)})`} pointerEvents="none">
            <circle className="tl__peak-halo" r={10} />
            <circle r={4.5} />
            <text x={0} y={-12} textAnchor="middle">
              {`peak ${Math.round(peak.v)}`}
            </text>
          </g>
        )}

        {/* crosshair: glides between readings (CSS transform transition) */}
        {hover && (
          <g pointerEvents="none">
            <line className="tl__cross" style={{ transform: `translateX(${x(hover.t)}px)` }} x1={0} x2={0} y1={M.top} y2={plotBottom} />
            <circle className={cx("tl__dot", hoverAfter && "tl__dot--after")} style={{ transform: `translate(${x(hover.t)}px, ${y(hover.v)}px)` }} r={4} />
          </g>
        )}
      </svg>

      {/* meal markers: real buttons over the axis, in time order */}
      <div className="tl__meals" style={{ top: PAD_TOP + plotBottom + 2 }}>
        {inRange.map((m) => (
          <button
            key={m.id}
            ref={(el) => {
              if (el) markerRefs.current.set(m.id, el);
              else markerRefs.current.delete(m.id);
            }}
            type="button"
            className={cx("tl__meal", m.current && "tl__meal--current", mealFocus === m.id && "is-focused", range && !inFocus(m.t) && "is-quiet", range?.meals && inFocus(m.t) && "is-evidence")}
            style={{ left: x(m.t) }}
            aria-label={`${mealLabel(m)}${m.current ? ", the meal the twin is predicting" : ""}${m.scored === false ? ", not scored" : ""}${onMealSelect && !m.current ? ". Press to move the twin to this meal" : ""}`}
            aria-current={m.current ? "true" : undefined}
            aria-describedby={mealFocus === m.id ? "tl-meal-card" : undefined}
            onPointerDown={(e) => (lastPointer.current = e.pointerType)}
            onPointerEnter={(e) => e.pointerType === "mouse" && setMealFocus(m.id)}
            onPointerLeave={(e) => e.pointerType === "mouse" && document.activeElement !== e.currentTarget && setMealFocus(null)}
            onFocus={() => setMealFocus(m.id)}
            onBlur={() => lastPointer.current === "mouse" && setMealFocus((cur) => (cur === m.id ? null : cur))}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                e.preventDefault();
                moveMeal(m.id, e.key === "ArrowRight" ? 1 : -1);
              } else if (e.key === "Escape") {
                setMealFocus(null);
                svgRef.current?.focus();
              }
            }}
            onClick={(e) => {
              // touch: the first tap opens the details, the second moves the twin (keyboard: detail 0)
              if (e.detail !== 0 && lastPointer.current !== "mouse" && mealFocus !== m.id) {
                setMealFocus(m.id);
                return;
              }
              if (!m.current) onMealSelect?.(m.id);
            }}
          >
            <svg width="12" height="10" viewBox="-6 -6 12 10" aria-hidden="true">
              <path d="M0,-5.5 L5,3.5 L-5,3.5 Z" />
            </svg>
          </button>
        ))}
      </div>

      {hover && (
        <div
          id="tl-readout"
          className="tl__tip"
          role={pinned ? "status" : undefined}
          style={{ transform: `translate(${Math.min(Math.max(x(hover.t), 84), w - 84)}px, ${Math.max(4, y(hover.v) - 76) + PAD_TOP}px) translateX(-50%)` }}
        >
          <span className="mono tl__tip-time">{fmtClock(hover.t)}</span>
          <span className="tl__tip-val">
            <span className="mono">{Math.round(hover.v)}</span> mg/dL
            {delta && (
              <span className="tl__tip-delta mono">
                {delta.dv > 0 ? "↑ +" : delta.dv < 0 ? "↓ −" : "→ ±"}
                {fmtNum(Math.abs(delta.dv))} in {delta.dtMin} min
              </span>
            )}
          </span>
          <span className="tl__tip-src">{hoverAfter ? "Recorded after the twin's moment (revealed)" : "Seen by the twin · native Dexcom"}</span>
          {pinned && (
            <button
              type="button"
              className="tl__tip-close"
              aria-label="Release the reading"
              onClick={() => {
                setPinned(false);
                setActive(null);
              }}
            >
              <Icon name="x" size={12} />
            </button>
          )}
        </div>
      )}

      {/* a steady readout under the chart: the focused meal, or the evidence being shown */}
      <div className="tl__readout" aria-live="polite">
        {focusedMeal ? (
          <div id="tl-meal-card" className="tl__mealcard">
            <span className="tl__mealcard-title">
              <svg width="10" height="9" viewBox="-5 -5 10 9" aria-hidden="true">
                <path d="M0,-4.5 L4.5,3.5 L-4.5,3.5 Z" />
              </svg>
              {mealLabel(focusedMeal)}
              {focusedMeal.current ? <span className="tl__mealcard-tag">current meal</span> : focusedMeal.scored === false ? <span className="tl__mealcard-tag">not scored</span> : null}
            </span>
            <dl className="tl__macros">
              {(
                [
                  ["Carbs", focusedMeal.carbs_g, "g"],
                  ["Fiber", focusedMeal.fiber_g, "g"],
                  ["Protein", focusedMeal.protein_g, "g"],
                  ["Fat", focusedMeal.fat_g, "g"],
                  ["Energy", focusedMeal.calories_kcal, "kcal"],
                ] as const
              ).map(([k, v, u]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd className="mono">{v == null ? "—" : `${fmtNum(v)} ${u}`}</dd>
                </div>
              ))}
            </dl>
            <span className="tl__mealcard-note">
              {focusedMeal.macrosValid === false ? "Macros logged but not usable by the model. " : ""}
              Shaded: the 2 hours after it{asOf !== undefined && focusedMeal.t + RESPONSE_MIN * MINUTE > asOf && revealed < 1 ? " (readings after the twin's moment stay hidden)" : ""}.
              {!focusedMeal.current && onMealSelect && (
                <button type="button" className="tl__mealcard-go" onClick={() => onMealSelect(focusedMeal.id)}>
                  Move the twin to this meal <Icon name="arrowRight" size={12} />
                </button>
              )}
            </span>
          </div>
        ) : focus ? (
          <div className="tl__evidence">
            <span>
              <strong>Evidence:</strong> {focus.label}
            </span>
            {onClearFocus && (
              <button type="button" className="tl__evidence-clear" onClick={onClearFocus} aria-label="Stop showing this evidence">
                <Icon name="x" size={12} />
              </button>
            )}
          </div>
        ) : (
          <span className="tl__hint">
            {inRange.length > 0 ? "Point at or tab to a meal ▲ for its details and 2-hour response. " : ""}
            Tap or click the chart to hold a reading; arrow keys step through readings.
          </span>
        )}
      </div>
    </div>
  );
}
