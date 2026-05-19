function formatTime(d: Date) {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface Props {
  refreshing: boolean;
  lastRefreshed: Date | null;
  countdown: number;
  onRefresh: () => void;
}

export default function RefreshBar({ refreshing, lastRefreshed, countdown, onRefresh }: Props) {
  return (
    <div className="flex items-center justify-between text-xs text-slate-500">
      <div className="flex items-center gap-2">
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
          <span>Updated {formatTime(lastRefreshed)}</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="tabular-nums">
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
