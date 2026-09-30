"use client";

import { useToast } from "./Toast";
import { Icon } from "./Icon";

/** A technical identifier (hash, version) shown short, copied in full. */
export function Ident({ value, label, short = 12 }: { value: string; label: string; short?: number }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      toast(`${label} copied`);
    } catch {
      toast("Copy is not available in this browser");
    }
  };
  return (
    <span className="ident">
      <code title={value}>{short > 0 && value.length > short ? `${value.slice(0, short)}…` : value}</code>
      <button type="button" onClick={copy} aria-label={`Copy ${label}`}>
        <Icon name="copy" size={13} />
      </button>
    </span>
  );
}
