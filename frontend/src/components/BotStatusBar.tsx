import type { BotStatus } from "@/api/bot";

export default function BotStatusBar({ status }: { status: BotStatus }) {
  const exposurePct = status.max_exposure_cents > 0
    ? Math.min(100, (status.current_exposure_cents / status.max_exposure_cents) * 100)
    : 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-bold px-2.5 py-1 rounded ${
              status.mode === "live"
                ? "bg-red-500/20 text-red-400"
                : "bg-amber-500/20 text-amber-400"
            }`}
          >
            {status.mode.toUpperCase()}
          </span>
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              status.enabled ? "bg-emerald-500 animate-pulse" : "bg-slate-600"
            }`}
          />
          <span className="text-sm text-slate-400">
            {status.enabled ? "Running" : "Paused"}
          </span>
        </div>

        <div className="h-4 w-px bg-slate-700" />

        <div className="flex-1 min-w-48">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>Exposure</span>
            <span>
              ${(status.current_exposure_cents / 100).toFixed(2)} / ${(status.max_exposure_cents / 100).toFixed(2)}
            </span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                exposurePct > 90 ? "bg-red-500" : exposurePct > 70 ? "bg-amber-500" : "bg-emerald-500"
              }`}
              style={{ width: `${exposurePct}%` }}
            />
          </div>
        </div>

        <div className="h-4 w-px bg-slate-700" />

        <div className="flex gap-4 text-sm">
          <div>
            <span className="text-slate-500">Today: </span>
            <span className="text-white font-medium">{status.signals_today}</span>
          </div>
          <div>
            <span className="text-slate-500">Active: </span>
            <span className="text-white font-medium">{status.active_signals}</span>
          </div>
          {status.daily_budget_cents > 0 && (
            <div>
              <span className="text-slate-500">Budget: </span>
              <span className="text-white font-medium">
                ${(status.daily_spent_cents / 100).toFixed(0)}/${(status.daily_budget_cents / 100).toFixed(0)}
              </span>
            </div>
          )}
          {status.spot_enabled && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Spot: </span>
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                status.spot_mode === "live"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-amber-500/20 text-amber-400"
              }`}>
                {status.spot_mode.toUpperCase()}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
