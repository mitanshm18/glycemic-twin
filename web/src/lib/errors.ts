/**
 * Context-specific wording for failures. The API's error code decides the message; the caller
 * says what it was trying to show. Never "Something went wrong".
 */

import { ApiError, NetworkError } from "./api/client";

export interface ErrorCopy {
  title: string;
  body: string;
  code?: string;
  retryable: boolean;
}

const BY_CODE: Record<string, (what: string) => Omit<ErrorCopy, "code">> = {
  PATIENT_NOT_FOUND: () => ({
    title: "Patient not found",
    body: "This participant is not in the ingested dataset. Check the link or return to the patient list.",
    retryable: false,
  }),
  NOT_FOUND: (what) => ({ title: `${what} not available`, body: "The server has no record of it.", retryable: false }),
  UNAUTHENTICATED: () => ({
    title: "Your session has ended",
    body: "Sign in again to continue. Nothing you were viewing has changed.",
    retryable: false,
  }),
  FORBIDDEN: (what) => ({ title: "Not permitted", body: `Your role cannot view ${what}.`, retryable: false }),
  MODEL_UNAVAILABLE: () => ({
    title: "Model unavailable",
    body: "No compatible model is active on the server, so the twin cannot score risk. An admin can register and activate one (make register-models).",
    retryable: true,
  }),
  MODEL_INCOMPATIBLE: () => ({
    title: "Model does not match this data",
    body: "The active model was trained under a different contract or dataset than this request needs, so the server refused to use it.",
    retryable: false,
  }),
  DATA_OUT_OF_RANGE: () => ({
    title: "No data at that moment",
    body: "The requested time is outside this participant's recording period.",
    retryable: false,
  }),
  INVALID_TIMESTAMP: () => ({ title: "Invalid time", body: "That timestamp could not be used.", retryable: false }),
  NO_CURRENT_MEAL: () => ({
    title: "No meal to predict",
    body: "No logged meal has an open prediction window at this moment.",
    retryable: false,
  }),
  WHAT_IF_UNSUPPORTED: () => ({
    title: "Scenario not supported",
    body: "The twin only simulates bounded changes to this meal's macros or recorded pre-meal activity.",
    retryable: false,
  }),
  NOT_EXPLAINABLE: () => ({
    title: "No explanation for this state",
    body: "Contributions exist only for scored predictions made by the currently active model.",
    retryable: false,
  }),
};

export function errorCopy(err: unknown, what: string): ErrorCopy {
  if (err instanceof NetworkError) {
    return {
      title: "Backend unreachable",
      body: "The API server did not respond. Check that it is running (make api), then retry.",
      retryable: true,
    };
  }
  if (err instanceof ApiError) {
    const known = BY_CODE[err.code];
    if (known) return { ...known(what), code: err.code };
    if (err.status >= 500) {
      return { title: `Could not load ${what}`, body: "The server failed while answering. Retry, and check the API logs if it persists.", code: err.code, retryable: true };
    }
    return { title: `Could not load ${what}`, body: err.message, code: err.code, retryable: false };
  }
  return { title: `Could not load ${what}`, body: "An unexpected error occurred in the browser.", retryable: true };
}
