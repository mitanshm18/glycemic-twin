"use client";

import { useEffect, useRef, useState } from "react";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

export const easeOut = (t: number) => 1 - (1 - t) ** 3;

/** The same clock as the CSS tokens (tokens.css): JS-driven motion uses these, never its own. */
export const MOTION = {
  micro: 120,
  standard: 200,
  emphasis: 360,
  morph: 900,
  linger: 1800,
  settle: 600,
  /** a data reveal (prediction -> reality): slower than UI motion, still brief */
  dataReveal: 2000,
} as const;

/**
 * Interpolates from the previous value to the new one when `target` changes: a count-up from 0 the
 * first time, a smooth transition afterwards. The first frame already shows the starting value (no
 * flash of the final number). Instant under reduced motion. `delay` holds the start so a reveal can
 * follow the layout settling.
 */
export function useAnimatedNumber(target: number | null, duration = 700, delay = 0): number | null {
  const [value, setValue] = useState<number | null>(() =>
    target === null ? null : prefersReducedMotion() ? target : 0,
  );
  const from = useRef<number | null>(null);
  useEffect(() => {
    if (target === null) {
      setValue(null);
      from.current = null;
      return;
    }
    const start = from.current ?? 0;
    if (prefersReducedMotion() || start === target) {
      setValue(target);
      from.current = target;
      return;
    }
    let raf = 0;
    let t0 = 0;
    const tick = (now: number) => {
      if (!t0) t0 = now + (from.current === null ? delay : 0);
      const k = Math.max(0, Math.min(1, (now - t0) / duration));
      setValue(start + (target - start) * easeOut(k));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      from.current = target;
    };
  }, [target, duration, delay]);
  return value;
}
