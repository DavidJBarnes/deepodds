import type { ScannerHealth } from "@/api/bot";

function formatTime(d: Date) {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface Props {
  refreshing: boolean;
  lastRefreshed: Date | null;
  countdown: number;
  onRefresh: () => void;
  scannerHealth: ScannerHealth | null;
}

export default function RefreshBar({ refreshing, lastRefreshed, countdown, onRefresh, scannerHealth }: Props) {
  const scannerDead = !scannerHealth;
  const scannerStale = scannerHealth && (Date.now() - new Date(scannerHealth.last_scan).getTime() > 120_000);
  const scannerError = scannerHealth?.error;

  return (
    <div className="flex items-center justify-between text-xs">
      <div className="flex items-center gap-3">
        {refreshing && (
          <span className="flex items-center gap-1.5 text-emerald-400">
            <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            Refreshing...
          </span>
        )}
        {!refreshing && lastRefreshed && (
          <span className="text-slate-500">Updated {formatTime(lastRefreshed)}</span>
        )}

        {/* Scanner health — integrated, not a separate bar */}
        {scannerDead && (
          <span className="text-red-400">Scanner offline</span>
        )}
        {scannerStale && !scannerDead && (
          <span className="text-amber-400">Scanner stale</span>
        )}
        {!scannerDead && !scannerStale && scannerHealth && (
          <span className="text-slate-500">
            {scannerHealth.opportunities} contracts
            {!scannerHealth.keys_valid && <span className="text-amber-400 ml-1">· keys invalid</span>}
          </span>
        )}
        {scannerError && (
          <span className="text-red-400 truncate max-w-xs" title={scannerError}>{scannerError}</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="tabular-nums text-slate-500">
          Next refresh in {countdown}s
        </span>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          Refresh now
        </button>
      </div>
    </div>
  );
}
