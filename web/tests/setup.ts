import "@testing-library/jest-dom/vitest";

/*
 * jsdom has no matchMedia, ResizeObserver or IntersectionObserver. Minimal stand-ins; a test can
 * switch reduced motion or the OS colour scheme with setMedia().
 */
const media: Record<string, boolean> = {
  "(prefers-reduced-motion: reduce)": false,
  "(prefers-color-scheme: dark)": false,
};

export function setMedia(query: keyof typeof media | string, matches: boolean): void {
  media[query] = matches;
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    get matches() {
      return media[query] ?? false;
    },
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
});

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
if (!("ResizeObserver" in window)) Object.assign(window, { ResizeObserver: NoopObserver });
if (!("IntersectionObserver" in window)) Object.assign(window, { IntersectionObserver: NoopObserver });

afterEach(() => {
  for (const k of Object.keys(media)) media[k] = false;
});
