/**
 * CGMacros timestamps are local wall-clock times with no time zone (ADR-018). The API sends them
 * as naive ISO strings ("2021-06-05T13:20:00"). To keep them exactly as recorded, the frontend
 * treats every naive timestamp as UTC internally and formats with UTC getters, so the browser's
 * own time zone can never shift a reading.
 */

export type Millis = number;

const NAIVE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$/;

export function parseNaive(s: string): Millis {
  const m = NAIVE.exec(s.trim());
  if (!m) throw new Error(`not a naive ISO timestamp: ${s}`);
  const [, y, mo, d, h, mi, se, frac] = m;
  const ms = frac ? Math.round(Number(`0.${frac}`) * 1000) : 0;
  return Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(se ?? 0), ms);
}

export function toNaiveIso(t: Millis): string {
  return new Date(t).toISOString().slice(0, 19);
}

export const MINUTE = 60_000;
export const HOUR = 60 * MINUTE;
export const DAY = 24 * HOUR;

const pad = (n: number) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** 13:05 */
export function fmtClock(t: Millis): string {
  const d = new Date(t);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** 5 Jun 2021 */
export function fmtDate(t: Millis): string {
  const d = new Date(t);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** Sat 5 Jun */
export function fmtDay(t: Millis): string {
  const d = new Date(t);
  return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** 5 Jun 2021, 13:05 */
export function fmtDateTime(t: Millis): string {
  return `${fmtDate(t)}, ${fmtClock(t)}`;
}

/** Start of the (naive) day containing t. */
export function dayStart(t: Millis): Millis {
  return Math.floor(t / DAY) * DAY;
}

/** "4 min", "2 h 10 min", "3 d" — for ages and durations. */
export function fmtDuration(ms: number): string {
  const min = Math.round(Math.abs(ms) / MINUTE);
  if (min < 1) return "< 1 min";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const rem = min % 60;
  if (h < 48) return rem ? `${h} h ${rem} min` : `${h} h`;
  return `${Math.round(h / 24)} d`;
}

/** Relative wall-clock time for system events (these do carry a real time zone). */
export function fmtRelative(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = now - t;
  if (diff < MINUTE) return "just now";
  return `${fmtDuration(diff)} ago`;
}
