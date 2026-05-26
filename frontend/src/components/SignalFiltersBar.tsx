export type VenueFilter = "all" | "crypto" | "kalshi";
export type StatusFilter =
  | "all"
  | "signaled"
  | "placed"
  | "filled"
  | "settled_win"
  | "settled_loss"
  | "settled_breakeven"
  | "cancelled";

interface Props {
  venue: VenueFilter;
  status: StatusFilter;
  onChange: (next: { venue: VenueFilter; status: StatusFilter }) => void;
  totalShown?: number;
  totalMatching?: number;
}

const VENUE_OPTIONS: { value: VenueFilter; label: string }[] = [
  { value: "all", label: "All venues" },
  { value: "crypto", label: "Crypto" },
  { value: "kalshi", label: "Kalshi" },
];

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "signaled", label: "Signaled" },
  { value: "placed", label: "Placed" },
  { value: "filled", label: "Filled" },
  { value: "settled_win", label: "Settled win" },
  { value: "settled_loss", label: "Settled loss" },
  { value: "settled_breakeven", label: "Settled breakeven" },
  { value: "cancelled", label: "Cancelled" },
];

export default function SignalFiltersBar({
  venue,
  status,
  onChange,
  totalShown,
  totalMatching,
}: Props) {
  const hasActiveFilters = venue !== "all" || status !== "all";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center gap-3 flex-wrap">
      <label className="flex items-center gap-2 text-xs text-slate-400">
        <span>Venue</span>
        <select
          value={venue}
          onChange={(e) => onChange({ venue: e.target.value as VenueFilter, status })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {VENUE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-xs text-slate-400">
        <span>Status</span>
        <select
          value={status}
          onChange={(e) => onChange({ venue, status: e.target.value as StatusFilter })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>

      {hasActiveFilters && (
        <button
          onClick={() => onChange({ venue: "all", status: "all" })}
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
