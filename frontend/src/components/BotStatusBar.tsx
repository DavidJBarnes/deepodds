import type { BotStatus } from "@/api/bot";

export default function BotStatusBar({ status }: { status: BotStatus }) {
  const posPct = status.max_open_positions > 0
    ? Math.min(100, (status.open_positions / status.max_open_positions) * 100)
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
          <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">
            Mean Reversion
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
            <span>Positions</span>
            <span>
              {status.open_positions} / {status.max_open_positions}
            </span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                posPct > 90 ? "bg-red-500" : posPct > 60 ? "bg-amber-500" : "bg-emerald-500"
              }`}
              style={{ width: `${posPct}%` }}
            />
          </div>
        </div>

        <div className="h-4 w-px bg-slate-700" />

        <div className="flex gap-4 text-sm">
          <div>
            <span className="text-slate-500">Entry: </span>
            <span className="text-white font-medium">&le;{status.entry_z_score}z</span>
          </div>
          <div>
            <span className="text-slate-500">Exit: </span>
            <span className="text-white font-medium">&ge;{status.exit_z_score}z</span>
          </div>
          <div>
            <span className="text-slate-500">Stop: </span>
            <span className="text-red-400 font-medium">-{status.stop_loss_pct}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}
