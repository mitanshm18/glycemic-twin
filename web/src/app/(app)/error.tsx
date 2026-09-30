"use client";

import { ErrorState } from "@/components/ui/StateMessage";

/** Unexpected render errors inside the app shell (API errors are handled where they occur). */
export default function AppError({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorState error={error} what="this page" onRetry={reset} center />;
}
