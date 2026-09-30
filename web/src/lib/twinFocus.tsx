"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Evidence } from "./evidence";
import type { Millis } from "./time";

/**
 * How the Twin page's parts point at each other (CONNECT): a model driver points at the evidence
 * it is computed from, the glucose reading points at its place on the timeline, the dial points at
 * its strongest driver. State only; each component decides how to show it.
 */
interface TwinFocus {
  /** evidence to emphasise; `sticky` survives the pointer leaving (set by an explicit action) */
  evidence: (Evidence & { sticky: boolean }) | null;
  showEvidence: (e: Evidence | null, sticky?: boolean) => void;
  /** ask the glucose timeline to pin its crosshair at a time (n changes on every request) */
  pin: { t: Millis; n: number } | null;
  pinReading: (t: Millis) => void;
  /** ask the explanation to emphasise one driver briefly */
  pulse: { feature: string; n: number } | null;
  pulseDriver: (feature: string) => void;
}

const Ctx = createContext<TwinFocus | null>(null);

export function TwinFocusProvider({ children }: { children: ReactNode }) {
  const [evidence, setEvidence] = useState<TwinFocus["evidence"]>(null);
  const [pin, setPin] = useState<TwinFocus["pin"]>(null);
  const [pulse, setPulse] = useState<TwinFocus["pulse"]>(null);
  const showEvidence = useCallback((e: Evidence | null, sticky = false) => {
    setEvidence((cur) => {
      if (e === null) return cur?.sticky && !sticky ? cur : null; // a hover ending never clears an explicit choice
      if (!sticky && cur?.sticky) return cur;
      return { ...e, sticky };
    });
  }, []);
  const pinReading = useCallback((t: Millis) => setPin((p) => ({ t, n: (p?.n ?? 0) + 1 })), []);
  const pulseDriver = useCallback((feature: string) => setPulse((p) => ({ feature, n: (p?.n ?? 0) + 1 })), []);
  const value = useMemo(() => ({ evidence, showEvidence, pin, pinReading, pulse, pulseDriver }), [evidence, showEvidence, pin, pinReading, pulse, pulseDriver]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const NOOP: TwinFocus = {
  evidence: null,
  showEvidence: () => {},
  pin: null,
  pinReading: () => {},
  pulse: null,
  pulseDriver: () => {},
};

/** Outside the Twin page (tests, other screens) the connections are simply absent. */
export function useTwinFocus(): TwinFocus {
  return useContext(Ctx) ?? NOOP;
}

/** Scroll a workspace section into view, gently unless motion is reduced. */
export function goToSection(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}
