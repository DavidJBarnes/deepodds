export function getTodayISO(): string {
  const d = new Date();
  return dateToISO(d);
}

export function getDateNDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return dateToISO(d);
}

export function getDefaultDateRange(): { dateFrom: string; dateTo: string } {
  return { dateFrom: getDateNDaysAgo(7), dateTo: getTodayISO() };
}

export function secondsAgo(unixSeconds: number): number {
  return Math.max(0, Math.round(Date.now() / 1000 - unixSeconds));
}

export function formatAgo(unixSeconds: number): string {
  const s = secondsAgo(unixSeconds);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function formatUnixTime(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dateToISO(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
