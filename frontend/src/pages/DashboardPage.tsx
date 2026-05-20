import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useBotStore } from "@/stores/botStore";
import BotStatusBar from "@/components/BotStatusBar";
import StatsCard from "@/components/StatsCard";
import SignalTable from "@/components/SignalTable";
import PnLChart from "@/components/PnLChart";
import RefreshBar from "@/components/RefreshBar";
import SpotTab from "@/components/SpotTab";

const REFRESH_INTERVAL = 60;

export default function DashboardPage() {
  const { dashboard, loading, refreshing, lastRefreshed, fetchDashboard } = useBotStore();
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);
  const [tab, setTab] = useState<"signals" | "spot">("signals");

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
  const needsSetup = !status.enabled || !status.has_kalshi_keys;

  return (
    <div className="space-y-6">
      <RefreshBar
        refreshing={refreshing}
        lastRefreshed={lastRefreshed}
        countdown={countdown}
        onRefresh={refresh}
      />

      {needsSetup && (
        <div className="bg-slate-900 border border-amber-500/30 rounded-xl p-5 space-y-3">
          <h3 className="text-sm font-semibold text-amber-400">Setup Required</h3>
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs ${status.has_kalshi_keys ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-800 text-slate-500"}`}>
                {status.has_kalshi_keys ? "✓" : "1"}
              </span>
              <span className={status.has_kalshi_keys ? "text-slate-500 line-through" : "text-slate-300"}>
                Add your Kalshi API keys
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
            Go to Settings →
          </Link>
        </div>
      )}

      <BotStatusBar status={status} />
      <StatsCard stats={dashboard.stats} spotStats={dashboard.spot_stats} />
      <PnLChart />

      <div className="flex gap-1 border-b border-slate-800">
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
        <button
          onClick={() => setTab("spot")}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === "spot"
              ? "text-emerald-400 border-b-2 border-emerald-400"
              : "text-slate-400 hover:text-white"
          }`}
        >
          Spot BTC
        </button>
      </div>

      {tab === "signals" ? (
        <SignalTable signals={dashboard.recent_signals} />
      ) : (
        <SpotTab spotStats={dashboard.spot_stats} spotEnabled={status.spot_enabled} dipThreshold={dashboard.bot_status.spot_dip_pct} />
      )}
    </div>
  );
}
