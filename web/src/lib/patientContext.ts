/**
 * Keeps the clinician's place while moving between a patient's pages (in memory, this tab only):
 * returning from the clinical record to the Twin reopens the same moment.
 */
const lastMoment = new Map<number, string>();

export function rememberMoment(patientId: number, search: string): void {
  if (search && search !== "?") lastMoment.set(patientId, search.startsWith("?") ? search : `?${search}`);
}

export function twinHref(patientId: number): string {
  return `/patients/${patientId}${lastMoment.get(patientId) ?? ""}`;
}

export function recordHref(patientId: number, day?: string | null): string {
  return `/patients/${patientId}/record${day ? `?day=${encodeURIComponent(day)}` : ""}`;
}
