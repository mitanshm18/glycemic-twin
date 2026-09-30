"use client";

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Icon } from "./Icon";

type Tone = "success" | "error";

interface ToastItem {
  id: number;
  text: string;
  tone: Tone;
  leaving: boolean;
}

type Show = (text: string, opts?: { tone?: Tone; ms?: number }) => void;

const Ctx = createContext<Show>(() => {});

export function useToast() {
  return useContext(Ctx);
}

const EXIT_MS = 180;

/**
 * Short feedback ("Copied", "Couldn't sign out"): announced politely (errors assertively), enters
 * and leaves with a small fade/lift, gone after 2.4 s (errors 5 s).
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const show = useCallback<Show>((text, opts) => {
    const id = next.current++;
    const tone = opts?.tone ?? "success";
    const ms = opts?.ms ?? (tone === "error" ? 5000 : 2400);
    setItems((xs) => [...xs.slice(-2), { id, text, tone, leaving: false }]);
    window.setTimeout(() => {
      setItems((xs) => xs.map((x) => (x.id === id ? { ...x, leaving: true } : x)));
      window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), EXIT_MS);
    }, ms);
  }, []);
  const errors = items.filter((t) => t.tone === "error");
  const infos = items.filter((t) => t.tone !== "error");
  const render = (t: ToastItem) => (
    <div key={t.id} className={cx("toast", `toast--${t.tone}`, t.leaving && "is-leaving")}>
      <Icon name={t.tone === "error" ? "alert" : "check"} size={14} />
      {t.text}
    </div>
  );
  return (
    <Ctx.Provider value={show}>
      {children}
      <div className="toasts">
        <div role="status" aria-live="polite">
          {infos.map(render)}
        </div>
        <div aria-live="assertive">
          {errors.map(render)}
        </div>
      </div>
    </Ctx.Provider>
  );
}
