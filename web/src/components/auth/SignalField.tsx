"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { cx } from "@/lib/cx";
import { usePointerFine } from "@/lib/interaction";
import { useReducedMotion } from "@/lib/motion";
import { ANCHORS, pointAt, toPath, tracePoints, WINDOW_U, xOf, yOf, type Frame, type Pointer, type SignalAnchor } from "@/lib/signal";
import { useBox } from "@/lib/useSize";

const DRAWN_AT = 1250; // ms: when the entrance has finished and the signal becomes interactive
const NEAR_PX = 80; // the pointer affects the trace only when this close to it

const CHIP_W = 232; // px: the chip's max width (14.5rem)

/** Above the point, unless that would cover the text above the signal: then beside it. */
function chipSide([x, y]: [number, number], f: Frame): "above" | "right" | "left" {
  if (y > f.height * 0.45) return "above";
  return x + 16 + CHIP_W < f.width ? "right" : "left";
}

function chipStyle(at: [number, number], f: Frame) {
  const [x, y] = at;
  const side = chipSide(at, f);
  if (side === "above") return { left: Math.min(Math.max(x, CHIP_W / 2), f.width - CHIP_W / 2), top: y - 16 };
  return { left: side === "right" ? x + 16 : x - 16, top: y };
}

/**
 * The sign-in signal: one glucose-style trace over the 70–180 band, drawn in once, then still.
 * It responds to the pointer (the nearby trace leans toward it and a reading cursor follows) and
 * three sparse points explain, in the product's own words, what the twin looks at. A brand motif,
 * not patient data: no values, no axes, hidden from assistive technology (the page text says the
 * same things).
 */
export function SignalField({ compact = false }: { compact?: boolean }) {
  // size comes from CSS (a taller band beside the form, a short strip on narrow screens)
  const [ref, { width, height }] = useBox<HTMLDivElement>({ width: 640, height: 188 });
  const reduced = useReducedMotion();
  const fine = usePointerFine();
  const f: Frame = useMemo(() => ({ width, height, top: 14, bottom: compact ? 10 : 26 }), [width, height, compact]);

  const [ready, setReady] = useState(false);
  const [active, setActive] = useState<SignalAnchor["id"] | null>(null);
  const [ptr, setPtr] = useState<Pointer | null>(null);
  const [explored, setExplored] = useState(false);

  // the signal becomes explorable once it has drawn in (at once under reduced motion)
  useEffect(() => {
    if (reduced) {
      setReady(true);
      return;
    }
    const t = window.setTimeout(() => setReady(true), DRAWN_AT);
    return () => window.clearTimeout(t);
  }, [reduced]);

  // pointer proximity: the strength eases toward 1 near the trace and back to 0 away from it
  const target = useRef<{ x: number; y: number; want: number }>({ x: 0, y: 0, want: 0 });
  const strength = useRef(0);
  const loop = useRef(0);
  const run = useCallback(() => {
    if (loop.current) return;
    const step = () => {
      const t = target.current;
      strength.current += (t.want - strength.current) * 0.18;
      // settled: draw this frame and stop until the pointer moves again (no idle animation loop)
      const settled = Math.abs(t.want - strength.current) < 0.01;
      if (settled) strength.current = t.want;
      setPtr(strength.current === 0 ? null : { x: t.x, y: t.y, strength: strength.current });
      loop.current = settled ? 0 : requestAnimationFrame(step);
    };
    loop.current = requestAnimationFrame(step);
  }, []);
  useEffect(() => () => cancelAnimationFrame(loop.current), []);

  const interactive = ready && !compact;
  const proximity = interactive && fine && !reduced;
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!proximity || e.pointerType !== "mouse") return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const [, ty] = pointAt(x, f, null);
    target.current = { x, y, want: Math.abs(y - ty) < NEAR_PX ? 1 : 0 };
    run();
  };
  const onLeave = () => {
    target.current = { ...target.current, want: 0 };
    if (proximity) run();
  };

  // one explanation at a time; Esc or a click elsewhere puts it away
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setActive(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  const d = toPath(tracePoints(f, ptr));
  const meal = ANCHORS[0] as SignalAnchor;
  const plotBottom = f.height - f.bottom;
  const band = { y0: yOf(180, f), y1: yOf(70, f) };
  const w0 = xOf(meal.u, f);
  const w1 = xOf(meal.u + WINDOW_U, f);
  const cursor = ptr ? pointAt(ptr.x, f, ptr) : null;
  const shown = ANCHORS.find((a) => a.id === active) ?? null;
  const chipAt = shown ? pointAt(xOf(shown.u, f), f, ptr) : null;

  return (
    <div
      ref={ref}
      className={cx("signal", compact && "signal--compact", !reduced && "signal--enter", ptr && "is-reading")}
      aria-hidden="true"
      onPointerMove={onMove}
      onPointerLeave={onLeave}
    >
      <svg width={f.width} height={f.height} viewBox={`0 0 ${f.width} ${f.height}`} onClick={() => setActive(null)}>
        <defs>
          <linearGradient id="signal-glint" gradientUnits="userSpaceOnUse" x1={(ptr?.x ?? 0) - 70} x2={(ptr?.x ?? 0) + 70} y1="0" y2="0">
            <stop offset="0" stopColor="currentColor" stopOpacity="0" />
            <stop offset="0.5" stopColor="currentColor" stopOpacity="1" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        <rect className="signal__band" x={0} y={band.y0} width={f.width} height={Math.max(0, band.y1 - band.y0)} />
        <line className={cx("signal__th", active === "above" && "is-on")} x1={0} x2={f.width} y1={band.y0} y2={band.y0} />

        {/* the 2-hour window, shown when the meal or the window is being explained */}
        <rect
          className={cx("signal__window", (active === "window" || active === "meal") && "is-on")}
          x={w0}
          y={f.top}
          width={w1 - w0}
          height={plotBottom - f.top}
        />
        {!compact && (
          <g className={cx("signal__bracket", active === "window" && "is-on")}>
            <path d={`M${w0},${plotBottom + 6}v4H${w1}v-4`} />
          </g>
        )}
        {!compact && (
          <line className={cx("signal__drop", active === "meal" && "is-on")} x1={w0} x2={w0} y1={pointAt(w0, f, ptr)[1]} y2={plotBottom} />
        )}

        <path className="signal__trace" pathLength={1} d={d} />
        {ptr && <path className="signal__glint" d={d} stroke="url(#signal-glint)" style={{ opacity: ptr.strength }} />}

        {/* meal marks, in the same shape as the app's charts */}
        {!compact &&
          [0.1, meal.u].map((u, i) => (
            <g key={u} transform={`translate(${xOf(u, f)}, ${plotBottom + 2})`}>
              <path
                className={cx("signal__meal", u === meal.u && active === "meal" && "is-on")}
                style={{ animationDelay: `${900 + i * 80}ms` }}
                d="M0,-5 L4.5,3 L-4.5,3 Z"
              />
            </g>
          ))}

        {/* reading cursor: follows the pointer along the trace, carries no value */}
        {cursor && ptr && (
          <g className="signal__cursor" style={{ opacity: ptr.strength }} pointerEvents="none">
            <line x1={cursor[0]} x2={cursor[0]} y1={f.top} y2={plotBottom} />
            <circle cx={cursor[0]} cy={cursor[1]} r={3.5} />
          </g>
        )}

        {interactive &&
          ANCHORS.map((a) => {
            const [ax, ay] = pointAt(xOf(a.u, f), f, ptr);
            return (
              <g
                key={a.id}
                className={cx("signal__anchor", a.id === "above" && "signal__anchor--above", active === a.id && "is-on")}
                transform={`translate(${ax}, ${ay})`}
                onClick={(e) => {
                  e.stopPropagation();
                  setExplored(true);
                  setActive((cur) => (cur === a.id ? null : a.id));
                }}
              >
                <circle className="signal__hit" r={16} />
                <circle className="signal__ring" r={4} />
              </g>
            );
          })}
      </svg>

      {shown && chipAt && (
        <div
          key={shown.id}
          className={cx("signal__chip", shown.id === "above" && "signal__chip--above", `signal__chip--${chipSide(chipAt, f)}`)}
          style={chipStyle(chipAt, f)}
        >
          <span className="signal__chip-title">{shown.title}</span>
          <span className="signal__chip-body">{shown.body}</span>
        </div>
      )}
      {/* a quiet hint that the points can be explored; gone once one has been opened */}
      {interactive && (
        <span className={cx("signal__hint", explored && "is-gone")}>{fine ? "Click a point on the signal" : "Tap a point on the signal"}</span>
      )}
    </div>
  );
}
