"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { NetworkError } from "@/lib/api/client";
import { useLogout, useMe, useReady } from "@/lib/api/queries";
import { cx } from "@/lib/cx";
import { loginHref } from "@/lib/auth";
import { modelLabel } from "@/lib/format";
import { ThemeSwitcher } from "./ThemeSwitcher";

const NAV: Array<{ href: string; label: string; icon: IconName }> = [
  { href: "/patients", label: "Patients", icon: "patients" },
  { href: "/model", label: "Model", icon: "model" },
];

function Brand() {
  return (
    <Link href="/patients" className="brand" aria-label="Glycemic Twin, home">
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" className="brand__mark">
        <rect x="0.75" y="0.75" width="20.5" height="20.5" rx="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M4 13.5c2-5 4-5 5.5-1.5S13 17 14.5 9.5 17 6 18 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="brand__name">Glycemic Twin</span>
    </Link>
  );
}

function Status() {
  const { data, isError } = useReady();
  let tone = "neutral";
  let text = "Checking backend…";
  if (isError) {
    tone = "risk";
    text = "Backend unreachable";
  } else if (data) {
    const name = data.active_model?.split("@")[0]?.split("__") ?? [];
    if (!data.database) {
      tone = "risk";
      text = "Database unavailable";
    } else if (!data.active_model || !data.model_compatible) {
      tone = "warning";
      text = "No compatible model";
    } else {
      tone = "success";
      text = modelLabel(name[0], name[1]);
    }
  }
  return (
    <div className="shell-status" title={data?.problems?.join("; ") || undefined}>
      <span className={cx("shell-status__dot", `shell-status__dot--${tone}`)} aria-hidden="true" />
      <span className="shell-status__text">
        <span className="sr-only">Backend status: </span>
        {text}
      </span>
    </div>
  );
}

function Account() {
  const { data: me } = useMe();
  const logout = useLogout();
  const router = useRouter();
  const toast = useToast();
  const signOut = () =>
    logout.mutate(undefined, {
      // the server revoked the session: leave at once
      onSuccess: () => router.replace(loginHref(null, "signed_out")),
      // never pretend: if the server was not reached the session is still valid
      onError: (err) =>
        toast(
          err instanceof NetworkError
            ? "Couldn’t reach the server, so you are still signed in. Try again."
            : "Sign-out failed on the server. Try again.",
          { tone: "error" },
        ),
    });
  return (
    <div className="account">
      <div className="account__who">
        <span className="account__name">{me?.username ?? "…"}</span>
        <span className="account__role">{me ? (me.role === "admin" ? "Admin" : "Clinician") : " "}</span>
      </div>
      <Button
        variant="ghost"
        icon
        size="sm"
        aria-label={logout.isPending ? "Signing out" : "Sign out"}
        title="Sign out"
        disabled={logout.isPending}
        onClick={signOut}
      >
        <Icon name="logout" />
      </Button>
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Primary">
      <ul className="nav">
        {NAV.map((n) => {
          const active = path === n.href || path.startsWith(`${n.href}/`);
          return (
            <li key={n.href}>
              <Link href={n.href} className={cx("nav__link", active && "nav__link--active")} aria-current={active ? "page" : undefined} onClick={onNavigate}>
                <Icon name={n.icon} />
                {n.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <NavList onNavigate={onNavigate} />
      <div className="sidebar__foot">
        <Status />
        <ThemeSwitcher />
        <Account />
      </div>
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Application">
        <Brand />
        <SidebarBody />
      </aside>
      <header className="mobilebar">
        <Button variant="ghost" icon aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}>
          <Icon name="menu" size={18} />
        </Button>
        <Brand />
        <span />
      </header>
      <Sheet open={open} onClose={() => setOpen(false)} title="Navigation" side="left">
        <div className="sidebar sidebar--sheet">
          <SidebarBody onNavigate={() => setOpen(false)} />
        </div>
      </Sheet>
      <main id="main" className="main" tabIndex={-1}>
        {/* keyed by route: each page enters with a short fade; query changes (?at=) do not re-enter */}
        <div key={path} className="page-enter">
          {children}
        </div>
      </main>
    </div>
  );
}

export interface Crumb {
  label: string;
  href?: string;
}

/** Page title block with breadcrumbs. One per page. */
export function PageHeader({
  crumbs,
  title,
  meta,
  actions,
  below,
}: {
  crumbs?: Crumb[];
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** e.g. the patient's view tabs */
  below?: ReactNode;
}) {
  return (
    <div className="page-head">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb">
          <ol className="crumbs">
            {crumbs.map((c, i) => (
              <li key={`${c.label}-${i}`}>
                {c.href ? (
                  <Link href={c.href}>{c.label}</Link>
                ) : (
                  <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>
                )}
                {i < crumbs.length - 1 && <Icon name="chevronRight" size={12} />}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="page-head__row">
        <div className="page-head__title">
          <h1>{title}</h1>
          {meta && <div className="page-head__meta">{meta}</div>}
        </div>
        {actions && <div className="page-head__actions">{actions}</div>}
      </div>
      {below}
    </div>
  );
}
