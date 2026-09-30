"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ToastProvider } from "@/components/ui/Toast";
import { SESSION_EXPIRED_EVENT } from "@/lib/api/client";
import { loginHref } from "@/lib/auth";
import { makeQueryClient } from "@/lib/api/queries";
import { ThemeProvider } from "./ThemeProvider";

function SessionWatcher() {
  const router = useRouter();
  useEffect(() => {
    // Mid-session expiry (the server answered 401 to a request): back to sign-in, then here.
    const onExpired = () => {
      if (window.location.pathname.startsWith("/login")) return;
      router.replace(loginHref(window.location.pathname + window.location.search, "expired"));
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [router]);
  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <SessionWatcher />
          {children}
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
