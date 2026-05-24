import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useBotStore } from "@/stores/botStore";
import BotStatusBar from "@/components/BotStatusBar";
import StatsCard from "@/components/StatsCard";
import SignalTable from "@/components/SignalTable";
import MarketView from "@/components/OpportunityList";
import PnLChart from "@/components/PnLChart";
import RefreshBar from "@/components/RefreshBar";

const REFRESH_INTERVAL = 60;

export default function DashboardPage() {
  const { dashboard, loading, refreshing, lastRefreshed, fetchDashboard } = useBotStore();
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);
  const [tab, setTab] = useState<"markets" | "kalshi" | "signals">("markets");

  const refresh = useCallback(() => {
    setCountdown(REFRESH_INTERVAL);
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, REFRESH_INTERVAL * 1000);
    return () => clearInterval(intervalRef.current);
  }, [refresh]);

  useEffect(() => {
    const tick = setInterval(() => {
      setCountdown((c) => (c > 0 ? c - 1 : 0));
    }, 1000);
    return () => clearInterval(tick);
  }, []);

  if (!dashboard && loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-400">Loading dashboard...</p>
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-red-400">Failed to load dashboard</p>
      </div>
    );
  }

  const status = dashboard.bot_status;
  const needsSetup = !status.enabled || !status.has_exchange_keys;

  return (
    <div className="space-y-6">
      <RefreshBar
        refreshing={refreshing}
        lastRefreshed={lastRefreshed}
        countdown={countdown}
        onRefresh={refresh}
        scannerHealth={dashboard.scanner_health}
      />

      {needsSetup && (
        <div className="bg-slate-900 border border-amber-500/30 rounded-xl p-5 space-y-3">
          <h3 className="text-sm font-semibold text-amber-400">Setup Required</h3>
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs ${status.has_exchange_keys && status.exchange_keys_valid ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-800 text-slate-500"}`}>
                {status.has_exchange_keys && status.exchange_keys_valid ? "✓" : "1"}
              </span>
              <span className={status.has_exchange_keys && status.exchange_keys_valid ? "text-slate-500 line-through" : "text-slate-300"}>
                {status.has_exchange_keys && !status.exchange_keys_valid ? "Robinhood keys are invalid — re-enter in Settings" : "Add your Robinhood API keys"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs ${status.enabled ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-800 text-slate-500"}`}>
                {status.enabled ? "✓" : "2"}
              </span>
              <span className={status.enabled ? "text-slate-500 line-through" : "text-slate-300"}>
                Review settings and enable the bot
              </span>
            </div>
          </div>
          <Link
            to="/settings"
            className="inline-block text-sm text-amber-400 hover:text-amber-300 font-medium mt-1"
          >
            Go to Settings &rarr;
          </Link>
        </div>
      )}

      <BotStatusBar status={status} />

      {dashboard.kalshi_status && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold px-2.5 py-1 rounded bg-sky-500/20 text-sky-400">KALSHI</span>
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  dashboard.kalshi_status.enabled ? "bg-sky-500 animate-pulse" : "bg-slate-600"
                }`}
              />
              <span className="text-sm text-slate-400">
                {dashboard.kalshi_status.enabled ? "Running" : "Paused"}
              </span>
              {!dashboard.kalshi_status.has_keys && (
                <span className="text-xs text-amber-400">No API keys</span>
              )}
            </div>

            <div className="h-4 w-px bg-slate-700" />

            <div className="flex-1 min-w-48">
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Positions</span>
                <span>{dashboard.kalshi_status.open_positions} / {dashboard.kalshi_status.max_open_positions}</span>
              </div>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    dashboard.kalshi_status.open_positions / dashboard.kalshi_status.max_open_positions > 0.9
                      ? "bg-red-500"
                      : dashboard.kalshi_status.open_positions / dashboard.kalshi_status.max_open_positions > 0.6
                        ? "bg-amber-500"
                        : "bg-sky-500"
                  }`}
                  style={{ width: `${Math.min(100, (dashboard.kalshi_status.open_positions / dashboard.kalshi_status.max_open_positions) * 100)}%` }}
                />
              </div>
            </div>

            <div className="h-4 w-px bg-slate-700" />

            <div className="flex gap-4 text-sm">
              <div>
                <span className="text-slate-500">Entry: </span>
                <span className="text-white font-medium">&le;{dashboard.kalshi_status.entry_z_score}z</span>
              </div>
              <div>
                <span className="text-slate-500">Exit: </span>
                <span className="text-white font-medium">&ge;{dashboard.kalshi_status.exit_z_score}z</span>
              </div>
              <div>
                <span className="text-slate-500">Series: </span>
                <span className="text-white font-medium font-mono text-xs">{dashboard.kalshi_status.series_tickers}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <StatsCard stats={dashboard.stats} />
      <PnLChart />

      <div className="flex gap-1 border-b border-slate-800">
        <button
          onClick={() => setTab("markets")}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === "markets"
              ? "text-emerald-400 border-b-2 border-emerald-400"
              : "text-slate-400 hover:text-white"
          }`}
        >
          Crypto ({dashboard.markets.length})
        </button>
        {dashboard.kalshi_markets.length > 0 && (
          <button
            onClick={() => setTab("kalshi")}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === "kalshi"
                ? "text-sky-400 border-b-2 border-sky-400"
                : "text-slate-400 hover:text-white"
            }`}
          >
            Kalshi ({dashboard.kalshi_markets.length})
          </button>
        )}
        <button
          onClick={() => setTab("signals")}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === "signals"
              ? "text-emerald-400 border-b-2 border-emerald-400"
              : "text-slate-400 hover:text-white"
          }`}
        >
          Signals ({dashboard.recent_signals.length})
        </button>
      </div>

      {tab === "markets" && <MarketView markets={dashboard.markets} entryZ={status.entry_z_score} exitZ={status.exit_z_score} />}
      {tab === "kalshi" && (
        <div className="space-y-3">
          {dashboard.kalshi_markets.map((m) => (
            <div key={m.ticker} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold text-white">{m.ticker}</span>
                  <span className="text-xs text-slate-500">{m.series}</span>
                  {m.would_signal && (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-sky-500/20 text-sky-400 px-2 py-0.5 rounded-full">
                      Buy signal
                    </span>
                  )}
                </div>
                <span className="text-sm text-white font-medium tabular-nums">
                  ${m.price.toFixed(2)}
                </span>
              </div>
              <p className="text-xs text-slate-400 truncate">{m.title}</p>
              <div className="flex items-center justify-between text-xs">
                <div className="flex gap-4">
                  <span className="text-slate-500">VWAP <span className="text-slate-400 tabular-nums">${m.vwap.toFixed(2)}</span></span>
                  <span className="text-slate-500">Vol 24h <span className="text-slate-400 tabular-nums">{m.volume_24h.toLocaleString()}</span></span>
                  <span className="text-slate-500">Expires <span className="text-slate-400 tabular-nums">{m.hours_to_expiry.toFixed(1)}h</span></span>
                </div>
                <span className={`font-mono font-bold tabular-nums ${m.z_score <= -2.5 ? "text-sky-400" : "text-slate-300"}`}>
                  z = {m.z_score.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
          {dashboard.kalshi_markets.length === 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
              <p className="text-slate-400">No Kalshi markets scanned yet.</p>
            </div>
          )}
        </div>
      )}
      {tab === "signals" && <SignalTable signals={dashboard.recent_signals} />}
    </div>
  );
}
