"use client";

import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { errorCopy } from "@/lib/errors";
import { Button } from "./Button";
import { Icon, type IconName } from "./Icon";

interface EmptyProps {
  icon?: IconName;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  center?: boolean;
  tone?: "empty" | "notice";
}

export function EmptyState({ icon = "info", title, children, actions, center, tone = "empty" }: EmptyProps) {
  return (
    <div className={cx("state", center && "state--center", tone === "notice" && "state--notice")}>
      <Icon name={icon} size={20} className="state__icon" />
      <p className="state__title">{title}</p>
      {children && <div className="state__body">{children}</div>}
      {actions && <div className="state__actions">{actions}</div>}
    </div>
  );
}

interface ErrorProps {
  error: unknown;
  /** what was being loaded, e.g. "the patient list" */
  what: string;
  onRetry?: () => void;
  center?: boolean;
}

export function ErrorState({ error, what, onRetry, center }: ErrorProps) {
  const copy = errorCopy(error, what);
  return (
    <div role="alert" className={cx("state", "state--error", center && "state--center")}>
      <Icon name="alert" size={20} className="state__icon" />
      <p className="state__title">{copy.title}</p>
      <p className="state__body">{copy.body}</p>
      {copy.code && <p className="state__code mono">{copy.code}</p>}
      {copy.retryable && onRetry && (
        <div className="state__actions">
          <Button size="sm" onClick={onRetry}>
            <Icon name="rotate" size={14} /> Retry
          </Button>
        </div>
      )}
    </div>
  );
}
