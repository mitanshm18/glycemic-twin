import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import type { Tone } from "@/lib/risk";
import { Icon, type IconName } from "./Icon";

interface TagProps {
  tone?: Tone | "observed" | "quiet";
  icon?: IconName;
  children: ReactNode;
  title?: string;
  className?: string;
}

/** A status label: always text, optionally a glyph. Color only reinforces the words. */
export function Tag({ tone = "neutral", icon, children, title, className }: TagProps) {
  return (
    <span className={cx("tag", tone !== "neutral" && `tag--${tone}`, className)} title={title}>
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

/** "Measured" (observed data) vs "Model estimate": the one distinction users must never miss. */
export function Origin({ kind }: { kind: "observed" | "model" }) {
  return (
    <span className={cx("origin", `origin--${kind}`)}>
      <span className="origin__glyph" aria-hidden="true" />
      {kind === "observed" ? "Measured" : "Model estimate"}
    </span>
  );
}
