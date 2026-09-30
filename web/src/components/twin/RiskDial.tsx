"use client";

import { useAnimatedNumber } from "@/lib/motion";
import { cx } from "@/lib/cx";
import type { Tone } from "@/lib/risk";

interface Props {
  probability: number | null;
  threshold: number | null;
  tone: Tone;
  size?: number;
  /** accessible summary, e.g. "72% estimated probability, alert threshold 37%" */
  label: string;
}

/**
 * The probability as a 270° gauge with the alert threshold as a tick. The arc animates between
 * values (CSS transition on the dash offset); the number counts up. No motion under reduced motion.
 */
export function RiskDial({ probability, threshold, tone, size = 168, label }: Props) {
  // A restrained reveal: number and arc rise together from 0 after the page settles.
  const shown = useAnimatedNumber(probability === null ? null : probability * 100, 900, 150);
  const stroke = Math.max(6, Math.round(size / 18));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const arc = 0.75 * c; // 270° track
  const filled = shown === null ? 0 : arc * Math.max(0, Math.min(1, shown / 100));
  const cx0 = size / 2;
  // threshold tick: angle measured from the start of the track (135° in SVG space)
  const tickAngle = threshold === null ? null : ((135 + 270 * threshold) * Math.PI) / 180;
  const tick =
    tickAngle === null
      ? null
      : {
          x1: cx0 + (r - stroke) * Math.cos(tickAngle),
          y1: cx0 + (r - stroke) * Math.sin(tickAngle),
          x2: cx0 + (r + stroke) * Math.cos(tickAngle),
          y2: cx0 + (r + stroke) * Math.sin(tickAngle),
        };
  return (
    <div className="dial" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          className="dial__track"
          cx={cx0}
          cy={cx0}
          r={r}
          strokeWidth={stroke}
          strokeDasharray={`${arc} ${c}`}
          transform={`rotate(135 ${cx0} ${cx0})`}
        />
        <circle
          className={cx("dial__value", `dial__value--${tone}`, probability === null && "dial__value--empty")}
          cx={cx0}
          cy={cx0}
          r={r}
          strokeWidth={stroke}
          strokeDasharray={`${filled} ${c}`}
          transform={`rotate(135 ${cx0} ${cx0})`}
        />
        {tick && <line className="dial__tick" {...tick} />}
      </svg>
      <div className="dial__center">
        <span className="dial__num">
          {shown === null ? "—" : Math.round(shown)}
          {shown !== null && <span className="dial__pct">%</span>}
        </span>
      </div>
    </div>
  );
}
