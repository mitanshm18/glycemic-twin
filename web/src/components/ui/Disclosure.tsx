"use client";

import { useId, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

/** "Show details" pattern: button with aria-expanded, height animated via grid rows. */
export function Disclosure({ label, children, defaultOpen = false }: { label: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button type="button" className="disclosure__btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Icon name="chevronRight" size={14} />
        {label}
      </button>
      <div id={id} className="disclosure__panel" data-open={open}>
        <div>{open && <div style={{ paddingTop: "var(--s-3)" }}>{children}</div>}</div>
      </div>
    </div>
  );
}
