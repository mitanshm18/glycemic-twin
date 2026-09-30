/**
 * Theme preference: "light" | "dark" | "system". Stored in localStorage (per browser convenience
 * only). The inline script below runs in <head> before first paint, so there is no flash.
 */

export type ThemePref = "light" | "dark" | "system";
export type Theme = "light" | "dark";

export const THEME_KEY = "twin-theme";

export function resolveTheme(pref: ThemePref, systemDark: boolean): Theme {
  return pref === "system" ? (systemDark ? "dark" : "light") : pref;
}

export function readPref(): ThemePref {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function writePref(pref: ThemePref): void {
  try {
    window.localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
}

/** Serialized into <head>; keep it tiny and dependency-free. */
export const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem("${THEME_KEY}");if(p!=="light"&&p!=="dark")p=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=p;}catch(e){document.documentElement.dataset.theme="light";}})();`;
