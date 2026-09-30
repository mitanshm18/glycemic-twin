import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

interface Props {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  model?: boolean;
  className?: string;
}

/** One labelled number. `model` marks a model-estimated value (colored, and labelled by caller). */
export function Metric({ label, value, unit, sub, model, className }: Props) {
  return (
    <div className={cx("metric", model && "metric--model", className)}>
      <dt className="metric__label">{label}</dt>
      <dd className="metric__value">
        {value}
        {unit && <span className="metric__unit">{unit}</span>}
      </dd>
      {sub && <dd className="metric__sub">{sub}</dd>}
    </div>
  );
}
