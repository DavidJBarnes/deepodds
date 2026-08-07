// Small formatting + time helpers used across pages.

export function parseTs(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? null : ms;
}

/** Duration between two ISO timestamps in seconds (b - a), or null. */
export function durationSeconds(
  a: string | null | undefined,
  b: string | null | undefined,
): number | null {
  const ma = parseTs(a);
  const mb = parseTs(b);
  if (ma == null || mb == null) return null;
  return (mb - ma) / 1000;
}

export function formatMs(sec: number | null): string {
  if (sec == null) return '—';
  const ms = sec * 1000;
  if (Math.abs(ms) < 1000) return `${ms.toFixed(0)} ms`;
  return `${sec.toFixed(2)} s`;
}

export function formatSeconds(sec: number | null): string {
  if (sec == null) return '—';
  return `${sec.toFixed(2)}s`;
}

export function formatTime(ts: string | null | undefined): string {
  const ms = parseTs(ts);
  if (ms == null) return '—';
  return new Date(ms).toLocaleTimeString();
}

export function formatDateTime(ts: string | null | undefined): string {
  const ms = parseTs(ts);
  if (ms == null) return '—';
  return new Date(ms).toLocaleString();
}

/** Human countdown from now to a deadline, e.g. "2h 05m" or "past". */
export function countdown(deadlineUtc: string | null, nowMs: number): string {
  const target = parseTs(deadlineUtc);
  if (target == null) return '—';
  let diff = Math.floor((target - nowMs) / 1000);
  if (diff <= 0) return 'past';
  const d = Math.floor(diff / 86400);
  diff -= d * 86400;
  const h = Math.floor(diff / 3600);
  diff -= h * 3600;
  const m = Math.floor(diff / 60);
  const s = diff - m * 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

/** Age of a timestamp relative to now, in seconds. */
export function ageSeconds(ts: string | null | undefined, nowMs: number): number | null {
  const ms = parseTs(ts);
  if (ms == null) return null;
  return (nowMs - ms) / 1000;
}

export function centsToPrice(v: number | null): string {
  if (v == null) return '—';
  return `${v}¢`;
}

export function clsx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
