"use client";

import { useId, type ReactNode } from "react";

/**
 * A short explanation shown on hover and keyboard focus, and exposed to assistive technology as
 * the trigger's description. When the child is not focusable, pass `focusable` to wrap it in a
 * plain button so keyboard users can reach the text too.
 */
export function Tip({ text, children, focusable, label }: { text: string; children: ReactNode; focusable?: boolean; label?: string }) {
  const id = useId();
  return (
    <span className="tip">
      {focusable ? (
        <button type="button" className="tip__trigger" aria-label={label ?? "More information"} aria-describedby={id}>
          {children}
        </button>
      ) : (
        <span aria-describedby={id}>{children}</span>
      )}
      <span id={id} className="tip__bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
