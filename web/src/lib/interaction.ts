"use client";

import { useEffect, useState } from "react";

/** A media query's current value (false on the server and before hydration). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const on = () => setMatches(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}

/**
 * True when the primary input can hover precisely (mouse, trackpad). Pointer-proximity effects run
 * only then; touch gets the same information through taps.
 */
export function usePointerFine(): boolean {
  return useMediaQuery("(hover: hover) and (pointer: fine)");
}
