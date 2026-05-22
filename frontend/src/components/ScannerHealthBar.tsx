import type { ScannerHealth } from "@/api/bot";

function timeSince(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

export default function ScannerHealthBar({ health }: { health: ScannerHealth | null }) {
  if (!health) {
    return (
      <div className="bg-slate-900 border border-red-500/30 rounded-xl p-4">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <span className="text-sm text-red-400 font-medium">Scanner offline</span>
          <span className="text-xs text-slate-500">No scan data received. Check Celery worker.</span>
        </div>
      </div>
    );
  }

  const stale = Date.now() - new Date(health.last_scan).getTime() > 120_000; // >2 min = stale
  const hasError = !!health.error;

  return (
    <div className={`bg-slate-900 border rounded-xl p-4 ${hasError ? "border-red-500/30" : stale ? "border-amber-500/30" : "border-slate-800"}`}>
      <div className="flex items-center gap-3 flex-wrap text-sm">
        <span className={`w-2.5 h-2.5 rounded-full ${hasError ? "bg-red-500" : stale ? "bg-amber-500" : "bg-emerald-500 animate-pulse"}`} />
        <span className={hasError ? "text-red-400" : stale ? "text-amber-400" : "text-emerald-400"}>
          {hasError ? "Scan failed" : stale ? "Scanner stale" : "Scanner running"}
        </span>
        <span className="text-slate-500">{timeSince(health.last_scan)}</span>
        <span className="text-slate-600">·</span>
        <span className="text-slate-400">{health.opportunities} contracts</span>
        <span className="text-slate-600">·</span>
        <span className={health.keys_valid ? "text-emerald-400" : "text-amber-400"}>
          Keys {health.keys_valid ? "valid" : "invalid"}
        </span>
      </div>
      {hasError && (
        <p className="mt-2 text-xs text-red-400/80 font-mono">{health.error}</p>
      )}
    </div>
  );
}
