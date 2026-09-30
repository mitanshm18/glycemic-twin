"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { prefersReducedMotion } from "@/lib/motion";
import { readPref, resolveTheme, writePref, type Theme, type ThemePref } from "@/lib/theme";

interface ThemeCtx {
  pref: ThemePref;
  theme: Theme;
  setPref: (p: ThemePref) => void;
}

const Ctx = createContext<ThemeCtx>({ pref: "system", theme: "light", setPref: () => {} });

export function useTheme() {
  return useContext(Ctx);
}

/**
 * The inline <head> script already applied the right theme before paint; this provider keeps it
 * in sync with the user's choice and with OS changes while "system" is selected.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>("system");
  const [theme, setTheme] = useState<Theme>("light");

  const apply = useCallback((p: ThemePref, animate: boolean) => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const t = resolveTheme(p, mq.matches);
    const root = document.documentElement;
    const commit = () => {
      root.dataset.theme = t;
      setTheme(t);
    };
    if (!animate || root.dataset.theme === t || prefersReducedMotion()) {
      commit();
      return;
    }
    // Whole-page cross-fade where supported: every pixel moves between two finished frames, so
    // nothing flashes and no component needs its own colour transition.
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    if (typeof doc.startViewTransition === "function") {
      root.classList.add("theme-vt");
      const vt = doc.startViewTransition(commit) as { ready?: Promise<unknown>; finished?: Promise<unknown> } | undefined;
      // a transition the browser skips (hidden tab, rapid second change) rejects: the theme still
      // applies (commit always runs), so the rejection is not an error
      vt?.ready?.catch(() => undefined);
      void vt?.finished?.catch(() => undefined).finally(() => root.classList.remove("theme-vt"));
      return;
    }
    root.classList.add("theme-transition");
    commit();
    window.setTimeout(() => root.classList.remove("theme-transition"), 260);
  }, []);

  useEffect(() => {
    const p = readPref();
    setPrefState(p);
    apply(p, false);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystem = () => {
      if (readPref() === "system") apply("system", true);
    };
    mq.addEventListener("change", onSystem);
    return () => mq.removeEventListener("change", onSystem);
  }, [apply]);

  const setPref = useCallback(
    (p: ThemePref) => {
      writePref(p);
      setPrefState(p);
      apply(p, true);
    },
    [apply],
  );

  return <Ctx.Provider value={{ pref, theme, setPref }}>{children}</Ctx.Provider>;
}
