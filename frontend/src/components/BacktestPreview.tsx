import { useEffect, useRef, useState } from "react";
import { runBacktestPreview, type BacktestResult } from "@/api/bot";

interface Props {
  venue: string;
  pair: string;
  entryZ?: number;
  exitZ?: number;
  stopLoss: number;
  positionSize?: number;
  contracts?: number;
  lookback?: number;
  minEdge?: number;
  exitEdge?: number;
  volLookbackHours?: number;
}

export default function BacktestPreview({ venue, pair, entryZ, exitZ, stopLoss, positionSize, contracts, lookback, minEdge, exitEdge, volLookbackHours }: Props) {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setLoading(true);
      setError(false);
      try {
        const data = await runBacktestPreview({
          venue,
          pair,
          entry_z_score: entryZ,
          exit_z_score: exitZ,
          stop_loss_pct: stopLoss,
          position_size_usd: positionSize,
          contracts_per_signal: contracts,
          lookback_periods: lookback,
          min_edge: minEdge,
          exit_edge: exitEdge,
          vol_lookback_hours: volLookbackHours,
        });
        setResult(data);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }, 1000);
    return () => clearTimeout(timer.current);
  }, [venue, pair, entryZ, exitZ, stopLoss, positionSize, contracts, lookback, minEdge, exitEdge, volLookbackHours]);

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg p-3 text-center">
        <span className="text-xs text-slate-500 animate-pulse">Running backtest...</span>
      </div>
    );
  }

  if (error || !result || result.data_points === 0) {
    return (
      <div className="bg-slate-800/50 rounded-lg p-3 text-center">
        <span className="text-xs text-slate-600">{error ? "Backtest failed" : "No data available"}</span>
      </div>
    );
  }

  const pnlColor = result.total_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400";
  const wrColor = result.win_rate >= 50 ? "text-emerald-400" : result.win_rate >= 30 ? "text-amber-400" : "text-red-400";

  return (
    <div className={`rounded-lg p-3 border ${result.total_pnl_usd >= 0 ? "bg-emerald-500/5 border-emerald-500/20" : "bg-red-500/5 border-red-500/20"}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Backtest Preview</span>
        <span className="text-[10px] text-slate-600">{result.data_points} bars</span>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className="text-xs text-slate-500">Signals</div>
          <div className="text-sm font-medium text-white tabular-nums">{result.signals_count}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Win Rate</div>
          <div className={`text-sm font-medium tabular-nums ${wrColor}`}>{result.win_rate}%</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Avg P&L</div>
          <div className={`text-sm font-medium tabular-nums ${result.avg_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            ${result.avg_pnl_usd.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Total P&L</div>
          <div className={`text-sm font-medium tabular-nums ${pnlColor}`}>
            ${result.total_pnl_usd.toFixed(2)}
          </div>
        </div>
      </div>
      {result.signals_count > 0 && (
        <div className="mt-2 text-[10px] text-slate-600 text-center">
          {result.wins}W / {result.losses}L &middot; avg hold {result.avg_hold_bars.toFixed(0)} bars
        </div>
      )}
    </div>
  );
}
