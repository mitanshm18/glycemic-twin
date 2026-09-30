"use client";

import { useEffect, useRef, useState } from "react";

/** Width of an element, kept current with a ResizeObserver (charts render to real pixels). */
export function useWidth<T extends HTMLElement>(initial = 720) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth || initial);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, width] as const;
}

/** Width and height of an element (for drawings whose size is set by CSS). */
export function useBox<T extends HTMLElement>(initial: { width: number; height: number }) {
  const ref = useRef<T>(null);
  const [box, setBox] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = (w: number, h: number) =>
      setBox((b) => (b.width === Math.round(w) && b.height === Math.round(h) ? b : { width: Math.round(w), height: Math.round(h) }));
    read(el.clientWidth || initial.width, el.clientHeight || initial.height);
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r && r.width && r.height) read(r.width, r.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [ref, box] as const;
}
