"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "@/lib/cx";

export interface SegOption<T extends string> {
  value: T;
  label: ReactNode;
  /** accessible name when the label is only an icon */
  ariaLabel?: string;
}

interface Props<T extends string> {
  value: T;
  options: SegOption<T>[];
  onChange: (v: T) => void;
  label: string;
  className?: string;
  iconsOnly?: boolean;
}

/** A radio group styled as a segmented control (roving tabindex, arrow keys move and select). */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  className,
  iconsOnly,
}: Props<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const idx = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );
  const move = (e: KeyboardEvent, delta: number) => {
    e.preventDefault();
    const next = (idx + delta + options.length) % options.length;
    const opt = options[next];
    if (!opt) return;
    onChange(opt.value);
    refs.current[next]?.focus();
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx("seg", iconsOnly && "seg--icons", className)}
    >
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          aria-label={o.ariaLabel}
          title={o.ariaLabel}
          tabIndex={o.value === value ? 0 : -1}
          className="seg__opt"
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowDown") move(e, 1);
            else if (e.key === "ArrowLeft" || e.key === "ArrowUp") move(e, -1);
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
