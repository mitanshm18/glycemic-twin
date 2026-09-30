"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { isApiError, sessionExpiryMuted } from "@/lib/api/client";
import { useMe } from "@/lib/api/queries";
import { loginHref } from "@/lib/auth";

/**
 * Restores the signed-in state on every full page load (reload, deep link, new tab).
 *
 * The HttpOnly session cookie is authoritative and only the server can read it, so the gate asks
 * `/auth/me` and renders the page only once the answer is known:
 * - pending  -> a quiet placeholder in the page area (never the sign-in form, never a redirect);
 * - 200      -> the page;
 * - 401      -> the sign-in page, returning here afterwards;
 * - network  -> an explanation with a retry (the session may be fine; do not sign anyone out).
 * No timers: the decision waits for the server's answer.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const unauthenticated = isApiError(me.error, "UNAUTHENTICATED");

  useEffect(() => {
    if (!unauthenticated) return;
    const here = window.location.pathname + window.location.search;
    router.replace(loginHref(here, sessionExpiryMuted() ? "signed_out" : "expired"));
  }, [unauthenticated, router]);

  if (me.isSuccess) return <>{children}</>;

  if (me.isError && !unauthenticated) {
    return (
      <div className="gate" role="alert">
        <Icon name="alert" size={20} className="gate__icon" />
        <p className="gate__title">Can’t confirm your session</p>
        <p className="gate__body">
          The server did not answer, so your session could not be checked. You have not been signed out.
        </p>
        <Button size="sm" onClick={() => void me.refetch()}>
          <Icon name="rotate" size={14} /> Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="gate gate--restoring" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{unauthenticated ? "Session ended. Opening sign-in…" : "Restoring your session…"}</span>
      <div className="gate__skeleton" aria-hidden="true">
        <Skeleton w={220} h={26} />
        <Skeleton w={320} h={14} />
        <Skeleton h={180} style={{ marginTop: 24 }} />
        <Skeleton h={120} />
      </div>
    </div>
  );
}
