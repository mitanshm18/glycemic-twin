"use client";

/**
 * TanStack Query hooks: one per endpoint, one cache key scheme. Observations are retrospective and
 * twin states are deterministic (same inputs -> same state_id), so most data never goes stale in a
 * session; only session-dependent data (me, ready, history, overview) refetches.
 */

import {
  QueryClient,
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { API, ApiError, get, muteSessionExpiry, post, setCsrfToken } from "./client";
import type {
  CgmPoint,
  ClinicalField,
  Evaluation,
  Explanation,
  Lever,
  LoginOut,
  Meal,
  MealOutcome,
  ModelVersion,
  Naive,
  PatientDetail,
  PatientOverview,
  Providers,
  Ready,
  Replay,
  ReplayStep,
  ScenarioResult,
  StateDiff,
  TwinState,
  TwinStateSummary,
  User,
  WearablePoint,
} from "./types";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // Client errors (4xx) are answers, not glitches: never retry them.
        retry: (count, err) =>
          !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      },
    },
  });
}

export const keys = {
  me: ["me"] as const,
  providers: ["auth", "providers"] as const,
  ready: ["ready"] as const,
  overview: ["patients", "overview"] as const,
  patient: (id: number) => ["patient", id] as const,
  clinical: (id: number) => ["patient", id, "clinical"] as const,
  meals: (id: number) => ["patient", id, "meals"] as const,
  outcomes: (id: number) => ["patient", id, "outcomes"] as const,
  cgm: (id: number, start: Naive, end: Naive) => ["patient", id, "cgm", start, end] as const,
  wearable: (id: number, start: Naive, end: Naive) =>
    ["patient", id, "wearable", start, end] as const,
  twin: (id: number, asOf: Naive | null, mealId: string | null) =>
    ["patient", id, "twin", asOf, mealId] as const,
  history: (id: number) => ["patient", id, "history"] as const,
  diff: (a: string, b: string) => ["diff", a, b] as const,
  explanation: (stateId: string) => ["explanation", stateId] as const,
  models: ["models"] as const,
  evaluation: ["models", "evaluation"] as const,
};

const FOREVER = Number.POSITIVE_INFINITY;

/** The signed-in user. The session cookie is authoritative: this is how a reload restores it. */
export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => get<User>("/auth/me"),
    staleTime: 60_000,
    retry: false,
  });
}

/** Which sign-in methods the server offers (public; Google only when fully configured). */
export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => get<Providers>("/auth/providers"),
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

export function useReady() {
  return useQuery({
    queryKey: keys.ready,
    // /ready answers 200 or 503 with the same body; both are information, not failures.
    queryFn: async () => {
      const res = await fetch(`${API}/ready`, { credentials: "same-origin" });
      return (await res.json()) as Ready;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function usePatientsOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: () => get<PatientOverview[]>("/overview/patients"),
    staleTime: 15_000,
  });
}

export function usePatient(id: number) {
  return useQuery({
    queryKey: keys.patient(id),
    queryFn: () => get<PatientDetail>(`/patients/${id}`),
    staleTime: FOREVER,
  });
}

export function useClinical(id: number) {
  return useQuery({
    queryKey: keys.clinical(id),
    queryFn: () => get<ClinicalField[]>(`/patients/${id}/clinical`),
    staleTime: FOREVER,
  });
}

export function useMeals(id: number) {
  return useQuery({
    queryKey: keys.meals(id),
    queryFn: () => get<Meal[]>(`/patients/${id}/meals`),
    staleTime: FOREVER,
  });
}

export function useMealOutcomes(id: number) {
  return useQuery({
    queryKey: keys.outcomes(id),
    queryFn: () => get<MealOutcome[]>(`/patients/${id}/meal-outcomes`),
    staleTime: FOREVER,
  });
}

export function useCgm(id: number, start: Naive | null, end: Naive | null) {
  return useQuery({
    queryKey: keys.cgm(id, start ?? "", end ?? ""),
    queryFn: ({ signal }) =>
      get<CgmPoint[]>(`/patients/${id}/cgm`, { start, end, native_only: true }, signal),
    enabled: Boolean(start && end),
    staleTime: FOREVER,
    placeholderData: keepPreviousData,
  });
}

export function useWearable(id: number, start: Naive | null, end: Naive | null) {
  return useQuery({
    queryKey: keys.wearable(id, start ?? "", end ?? ""),
    queryFn: ({ signal }) => get<WearablePoint[]>(`/patients/${id}/wearable`, { start, end }, signal),
    enabled: Boolean(start && end),
    staleTime: FOREVER,
    placeholderData: keepPreviousData,
  });
}

export function fetchTwin(id: number, asOf: Naive | null, mealId: string | null) {
  return get<TwinState>(`/patients/${id}/twin`, { as_of: asOf, meal_id: mealId });
}

export function useTwinState(id: number, asOf: Naive | null, mealId: string | null, enabled = true) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: keys.twin(id, asOf, mealId),
    queryFn: async () => {
      const state = await fetchTwin(id, asOf, mealId);
      // A new snapshot may now exist: history and the overview are stale.
      void qc.invalidateQueries({ queryKey: keys.history(id) });
      void qc.invalidateQueries({ queryKey: keys.overview });
      return state;
    },
    enabled,
    staleTime: FOREVER,
    placeholderData: keepPreviousData,
  });
}

export function useStateHistory(id: number) {
  return useQuery({
    queryKey: keys.history(id),
    queryFn: () => get<TwinStateSummary[]>(`/patients/${id}/twin-states`, { limit: 200 }),
    staleTime: 5_000,
  });
}

export function useStateDiff(a: string | null, b: string | null) {
  return useQuery({
    queryKey: keys.diff(a ?? "", b ?? ""),
    queryFn: () => get<StateDiff>(`/twin-states/${a}/diff/${b}`),
    enabled: Boolean(a && b && a !== b),
    staleTime: FOREVER,
  });
}

export function useExplanation(stateId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: keys.explanation(stateId ?? ""),
    queryFn: () => get<Explanation>(`/twin-states/${stateId}/explanation`),
    enabled: Boolean(stateId) && enabled,
    staleTime: FOREVER,
    placeholderData: keepPreviousData,
  });
}

export function useModels() {
  return useQuery({ queryKey: keys.models, queryFn: () => get<ModelVersion[]>("/models") });
}

export function useEvaluation() {
  return useQuery({
    queryKey: keys.evaluation,
    queryFn: () => get<Evaluation>("/models/active/evaluation"),
    staleTime: FOREVER,
  });
}

export interface WhatIfInput {
  asOf: Naive;
  mealId: string | null;
  changes: Partial<Record<Lever, number>>;
}

export function useWhatIf(patientId: number) {
  return useMutation({
    mutationFn: (input: WhatIfInput) =>
      post<ScenarioResult>(`/patients/${patientId}/what-if`, {
        as_of: input.asOf,
        meal_id: input.mealId,
        changes: input.changes,
      }),
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      post<LoginOut>("/auth/login", body, { csrf: false }),
    onSuccess: (out) => {
      muteSessionExpiry(false);
      setCsrfToken(out.csrf_token);
      qc.clear(); // never show one user's cached data to the next
      qc.setQueryData(keys.me, out.user);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<void>("/auth/logout"),
    onMutate: () => muteSessionExpiry(true),
    onSuccess: () => {
      setCsrfToken(null);
      qc.clear(); // nothing from the signed-out session stays in memory
    },
    onError: () => muteSessionExpiry(false),
  });
}

// ------------------------------------------------------------------ replay (historical)

export function createReplay(input: { patientId: number; startAt: Naive; endAt: Naive; stepMinutes: number }) {
  return post<Replay>("/replays", {
    patient_id: input.patientId,
    start_at: input.startAt,
    end_at: input.endAt,
    step_minutes: input.stepMinutes,
  });
}

export function stepReplay(id: number) {
  return post<ReplayStep>(`/replays/${id}/step`);
}
