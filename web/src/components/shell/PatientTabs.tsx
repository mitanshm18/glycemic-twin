"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { cx } from "@/lib/cx";
import { recordHref, twinHref } from "@/lib/patientContext";

/** The patient's two views, always in the same place; the current one is marked for AT too. */
export function PatientTabs({ patientId, current, day }: { patientId: number; current: "twin" | "record"; day?: string | null }) {
  const tabs = [
    { key: "twin" as const, label: "Twin", icon: "pulse" as const, href: twinHref(patientId) },
    { key: "record" as const, label: "Clinical record", icon: "record" as const, href: recordHref(patientId, day) },
  ];
  return (
    <nav className="ptabs" aria-label="Patient views">
      {tabs.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={cx("ptabs__tab", current === t.key && "is-active")}
          aria-current={current === t.key ? "page" : undefined}
        >
          <Icon name={t.icon} size={14} />
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
