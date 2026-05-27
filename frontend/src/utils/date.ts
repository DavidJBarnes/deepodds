export function getTodayISO(): string {
  return new Date().toISOString().slice(0, 10);
}
