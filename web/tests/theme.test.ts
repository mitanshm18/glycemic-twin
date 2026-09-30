import { readPref, resolveTheme, THEME_KEY, THEME_SCRIPT, writePref } from "@/lib/theme";

describe("theme preference", () => {
  beforeEach(() => localStorage.clear());

  it("resolves system against the OS setting", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("persists and ignores junk", () => {
    expect(readPref()).toBe("system");
    writePref("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(readPref()).toBe("dark");
    localStorage.setItem(THEME_KEY, "purple");
    expect(readPref()).toBe("system");
  });

  it("the head script sets the theme before paint", () => {
    localStorage.setItem(THEME_KEY, "dark");
    new Function(THEME_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
