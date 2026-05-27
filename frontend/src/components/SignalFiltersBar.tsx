import { getTodayISO } from "@/utils/date";

const STATUS_OPTIONS = [
  { value: "signaled", label: "Signaled" },
  { value: "placed", label: "Placed" },
  { value: "filled", label: "Filled" },
  { value: "settled_win", label: "Settled win" },
  { value: "settled_loss", label: "Settled loss" },
  { value: "settled_breakeven", label: "Settled breakeven" },
  { value: "cancelled", label: "Cancelled" },
] as const;

const STATUS_COLORS: Record<string, string> = {
  signaled: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  placed: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  filled: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  settled_win: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  settled_loss: "bg-red-500/20 text-red-400 border-red-500/30",
  settled_breakeven: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  cancelled: "bg-slate-500/20 text-slate-400 border-slate-500/30",
};

interface Props {
  date: string;
  statuses: string[];
  onChange: (next: { date: string; statuses: string[] }) => void;
  totalShown?: number;
  totalMatching?: number;
}

export default function SignalFiltersBar({
  date,
  statuses,
  onChange,
  totalShown,
  totalMatching,
}: Props) {
  const safeStatuses = statuses ?? [];
  const hasActiveFilters = date !== getTodayISO() || safeStatuses.length > 0;

  function toggleStatus(value: string) {
    const next = safeStatuses.includes(value)
      ? safeStatuses.filter((s) => s !== value)
      : [...safeStatuses, value];
    onChange({ date, statuses: next });
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center gap-3 flex-wrap">
      <label className="flex items-center gap-2 text-xs text-slate-400">
        <span>Date</span>
        <input
          type="date"
          value={date}
          onChange={(e) => onChange({ date: e.target.value, statuses: safeStatuses })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-emerald-500"
        />
      </label>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-xs text-slate-400">Status</span>
        {STATUS_OPTIONS.map((o) => {
          const active = safeStatuses.includes(o.value);
          return (
            <button
              key={o.value}
              onClick={() => toggleStatus(o.value)}
              className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                active
                  ? STATUS_COLORS[o.value]
                  : "bg-slate-800 text-slate-500 border-slate-700 hover:text-slate-300"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>

      {hasActiveFilters && (
        <button
          onClick={() => onChange({ date: getTodayISO(), statuses: [] })}
          className="text-xs text-slate-500 hover:text-white"
        >
          Clear
        </button>
      )}

      <div className="ml-auto text-xs text-slate-500 tabular-nums">
        {totalShown != null && totalMatching != null && (
          <span>{totalShown} of {totalMatching} shown</span>
        )}
      </div>
    </div>
  );
}
