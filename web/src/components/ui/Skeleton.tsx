import type { CSSProperties, ReactNode } from "react";
import { cx } from "@/lib/cx";

export function Skeleton({
  w = "100%",
  h = 14,
  className,
  style,
}: {
  w?: number | string;
  h?: number | string;
  className?: string;
  style?: CSSProperties;
}) {
  return <span aria-hidden="true" className={cx("skel", className)} style={{ width: w, height: h, ...style }} />;
}

/** Announces loading once for screen readers while skeletons are shown. */
export function Loading({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
