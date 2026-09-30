"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { MOTION, useAnimatedNumber } from "@/lib/motion";
import { cx } from "@/lib/cx";
import type { Tone } from "@/lib/risk";

interface Props {
  probability: number | null;
  threshold: number | null;
  tone: Tone;
  size?: number;
  /** accessible summary, e.g. "72% estimated probability, alert threshold 37%" */
  label: string;
  /** what exploring the dial shows (hover / focus); from the current state only */
  details?: ReactNode;
  /** click / Enter: lead to the explanation */
  onActivate?: () => void;
}

/** Point on the 270° track for a value in 0..1 (the track starts at 135° in SVG space). */
function onTrack(v: number, c: number, r: number) {
  const a = ((135 + 270 * Math.max(0, Math.min(1, v))) * Math.PI) / 180;
  return { x: c + r * Math.cos(a), y: c + r * Math.sin(a) };
}

/**
 * The probability as a 270° gauge with the alert threshold as a tick. Number and arc share one
 * animated value: they rise together on load and morph from the previous value when the twin
 * moves. The previous value stays briefly as a ghost mark; crossing the threshold lights the tick
 * once. Exploring it (hover / focus) shows what it means; activating it leads to "Why this risk?".
 */
export function RiskDial({ probability, threshold, tone, size = 168, label, details, onActivate }: Props) {
  const shown = useAnimatedNumber(probability === null ? null : probability * 100, MOTION.morph, 150);
  const detailsId = useId();
  const stroke = Math.max(6, Math.round(size / 18));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const arc = 0.75 * c; // 270° track
  const filled = shown === null ? 0 : arc * Math.max(0, Math.min(1, shown / 100));
  const cx0 = size / 2;
  const tick =
    threshold === null
      ? null
      : { a: onTrack(threshold, cx0, r - stroke), b: onTrack(threshold, cx0, r + stroke) };

  // the previous value, kept as a fading ghost after a change of moment
  const prev = useRef<number | null>(null);
  const [ghost, setGhost] = useState<{ v: number; n: number } | null>(null);
  useEffect(() => {
    const before = prev.current;
    prev.current = probability;
    if (before !== null && probability !== null && Math.abs(before - probability) >= 0.005) {
      setGhost((g) => ({ v: before, n: (g?.n ?? 0) + 1 }));
    }
  }, [probability]);

  // crossing the threshold while the arc moves: the tick lights once, at the moment it is passed
  const side = shown === null || threshold === null ? null : shown / 100 >= threshold;
  const lastSide = useRef<boolean | null>(null);
  const [crossed, setCrossed] = useState(0);
  useEffect(() => {
    if (side === null) return;
    if (lastSide.current !== null && lastSide.current !== side) setCrossed((n) => n + 1);
    lastSide.current = side;
  }, [side]);

  const g = ghost ? onTrack(ghost.v, cx0, r) : null;
  const body = (
    <>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="dial__track" cx={cx0} cy={cx0} r={r} strokeWidth={stroke} strokeDasharray={`${arc} ${c}`} transform={`rotate(135 ${cx0} ${cx0})`} />
        <circle
          className={cx("dial__value", `dial__value--${tone}`, probability === null && "dial__value--empty")}
          cx={cx0}
          cy={cx0}
          r={r}
          strokeWidth={stroke}
          strokeDasharray={`${filled} ${c}`}
          transform={`rotate(135 ${cx0} ${cx0})`}
        />
        {g && ghost && <circle key={ghost.n} className="dial__ghost" cx={g.x} cy={g.y} r={stroke / 2 - 0.5} />}
        {tick && <line key={`tick-${crossed}`} className={cx("dial__tick", crossed > 0 && "dial__tick--crossed")} x1={tick.a.x} y1={tick.a.y} x2={tick.b.x} y2={tick.b.y} />}
      </svg>
      <div className="dial__center">
        <span className="dial__num">
          {shown === null ? "—" : Math.round(shown)}
          {shown !== null && <span className="dial__pct">%</span>}
        </span>
      </div>
    </>
  );

  if (!onActivate) {
    return (
      <div className="dial" style={{ width: size, height: size }} role="img" aria-label={label}>
        {body}
      </div>
    );
  }
  return (
    <div className="dial-wrap">
      <button
        type="button"
        className="dial dial--explorable"
        style={{ width: size, height: size }}
        aria-label={`${label} Show what drives this estimate.`}
        aria-describedby={details ? detailsId : undefined}
        onClick={onActivate}
      >
        {body}
      </button>
      {details && (
        <div id={detailsId} className="dial-card" role="tooltip">
          {details}
        </div>
      )}
    </div>
  );
}
