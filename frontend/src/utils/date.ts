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

function dateToISO(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
