import { useCallback, useEffect, useState } from "react";
import { useBotStore } from "@/stores/botStore";
import { getSignals, type KalshiFilteredMarket, type Signal } from "@/api/bot";
import BotStatusBar from "@/components/BotStatusBar";
import CountdownCell from "@/components/CountdownCell";
import SignalTable from "@/components/SignalTable";
import SignalFiltersBar from "@/components/SignalFiltersBar";
import RefreshBar from "@/components/RefreshBar";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { getTodayISO } from "@/utils/date";

const REFRESH_INTERVAL = 30;

export default function CryptoPage() {
  const { dashboard, loading, refreshing, lastRefreshed, fetchDashboard } = useBotStore();
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);
  const [tab, setTab] = useState<"signals" | "kalshi">("signals");
  const [showFiltered, setShowFiltered] = useState(false);
  const [signalFilters, setSignalFilters] = useLocalStorage<{
    date: string;
    statuses: string[];
  }>("deepodds.crypto.signals.filters.v2", { date: getTodayISO(), statuses: [] });
  const [filteredSignals, setFilteredSignals] = useState<Signal[] | null>(null);
  const [filteredTotal, setFilteredTotal] = useState<number>(0);
  const [signalsLoading, setSignalsLoading] = useState(false);

  const refresh = useCallback(() => {
    setCountdown(REFRESH_INTERVAL);
    fetchDashboard("crypto");
  }, [fetchDashboard]);

  useEffect(() => {
    if (tab !== "signals") return;
    let cancelled = false;
    setSignalsLoading(true);
    const statusList = signalFilters.statuses ?? [];
    getSignals({
      venue: "kalshi",
      date: signalFilters.date,
      tz_offset: new Date().getTimezoneOffset(),
      statuses: statusList.length ? statusList.join(",") : undefined,
      limit: 100,
    })
      .then((data) => {
        if (cancelled) return;
        setFilteredSignals(data.items);
        setFilteredTotal(data.total);
      })
      .catch(() => {
        if (cancelled) return;
        setFilteredSignals([]);
        setFilteredTotal(0);
      })
      .finally(() => {
        if (!cancelled) setSignalsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, signalFilters.date, signalFilters.statuses?.join(",") ?? "", lastRefreshed?.getTime()]);

  useEffect(() => {
    const tick = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          fetchDashboard("crypto");
          return REFRESH_INTERVAL;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  }, [fetchDashboard]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!dashboard && loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-400">Loading crypto dashboard...</p>
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

  const kalshi = dashboard.kalshi_status;

  return (
    <div className="space-y-6">
      <RefreshBar
        refreshing={refreshing}
        lastRefreshed={lastRefreshed}
        countdown={countdown}
        onRefresh={refresh}
        scannerHealth={dashboard.scanner_health}
      />

      {kalshi && kalshi.mode === "paper" && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded px-4 py-1.5 text-center">
          <span className="text-xs font-medium text-amber-400">Paper mode — no real orders will be placed</span>
        </div>
      )}

      {kalshi && (
        <BotStatusBar
          enabled={kalshi.enabled}
          openPositions={kalshi.open_positions}
          maxOpenPositions={kalshi.max_open_positions}
          hasKeysWarning={!kalshi.has_keys ? "No API keys" : undefined}
        >
          <div>
            <span className="text-slate-500">Risk: </span>
            <span className="text-white font-medium">${kalshi.current_exposure_usd.toFixed(2)}</span>
          </div>
          <div>
            <span className="text-slate-500">Max Win: </span>
            <span className="text-emerald-400 font-medium">
              +${(kalshi.max_payout_usd - kalshi.current_exposure_usd).toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-slate-500">Min Edge: </span>
            <span className="text-white font-medium">{(kalshi.min_edge * 100).toFixed(0)}%</span>
          </div>
          <div>
            <span className="text-slate-500">Exit Edge: </span>
            <span className="text-white font-medium">{(kalshi.exit_edge * 100).toFixed(0)}%</span>
          </div>
        </BotStatusBar>
      )}

      <div className="flex gap-1 border-b border-slate-800">
        <button
          onClick={() => setTab("signals")}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === "signals"
              ? "text-sky-400 border-b-2 border-sky-400"
              : "text-slate-400 hover:text-white"
          }`}
        >
          Signals ({tab === "signals" ? filteredTotal : dashboard.recent_signals.length})
        </button>
        <button
          onClick={() => setTab("kalshi")}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === "kalshi"
              ? "text-sky-400 border-b-2 border-sky-400"
              : "text-slate-400 hover:text-white"
          }`}
        >
          Opportunities ({dashboard.kalshi_markets.length}{dashboard.kalshi_filtered?.length ? ` + ${dashboard.kalshi_filtered.length} filtered` : ""})
        </button>
      </div>

      {tab === "kalshi" && (
        <div className="space-y-3">
          {dashboard.kalshi_markets.map((m) => (
            <div key={m.ticker} className={`bg-slate-900 border rounded-xl p-4 space-y-2 ${m.would_signal ? "border-sky-500/30" : m.edge > 0 ? "border-amber-500/30" : "border-slate-800"}`}>
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
                  <span className="text-slate-500">Model <span className="text-slate-400 tabular-nums">{(m.model_prob * 100).toFixed(1)}%</span></span>
                  <span className="text-slate-500">Market <span className="text-slate-400 tabular-nums">{(m.price * 100).toFixed(1)}%</span></span>
                  <span className="text-slate-500">Vol 24h <span className="text-slate-400 tabular-nums">{m.volume_24h.toLocaleString()}</span></span>
                  <span className="text-slate-500">Expires <CountdownCell target={m.expiry_time} /></span>
                  {m.floor_strike != null && m.cap_strike != null && (
                    <span className="text-slate-500">Strike <span className="text-slate-400 tabular-nums">${m.floor_strike.toLocaleString()}-${m.cap_strike.toLocaleString()}</span></span>
                  )}
                </div>
                <span className={`font-mono font-bold tabular-nums ${m.edge > 0 ? "text-emerald-400" : m.edge < -0.02 ? "text-red-400" : "text-slate-300"}`}>
                  edge {m.edge >= 0 ? "+" : ""}{(m.edge * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          ))}
          {dashboard.kalshi_markets.length === 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
              <p className="text-slate-400">No Kalshi crypto markets scanned yet.</p>
            </div>
          )}

          {dashboard.kalshi_filtered && dashboard.kalshi_filtered.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowFiltered(!showFiltered)}
                className="text-sm text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1"
              >
                <span className={`transition-transform ${showFiltered ? "rotate-90" : ""}`}>&#9654;</span>
                Filtered Markets ({dashboard.kalshi_filtered.length})
              </button>
              {showFiltered && (
                <div className="mt-2 space-y-2">
                  {dashboard.kalshi_filtered.map((f: KalshiFilteredMarket) => (
                    <div key={f.ticker} className="bg-slate-900/50 border border-slate-800/50 rounded-lg px-4 py-2 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-500">{f.ticker}</span>
                        <span className="text-xs text-slate-600 truncate max-w-xs">{f.title}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-slate-600 tabular-nums">${f.price.toFixed(2)}</span>
                        <span className="text-slate-600 tabular-nums">vol {f.volume_24h.toLocaleString()}</span>
                        <span className="bg-slate-800 text-slate-500 px-2 py-0.5 rounded text-[10px] font-medium">
                          {f.filter_reason.replace("_", " ")}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {tab === "signals" && (
        <div className="space-y-3">
          <SignalFiltersBar
            date={signalFilters.date}
            statuses={signalFilters.statuses}
            onChange={setSignalFilters}
            totalShown={filteredSignals?.length ?? 0}
            totalMatching={filteredTotal}
          />
          {signalsLoading && filteredSignals === null ? (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
              <p className="text-slate-400">Loading signals...</p>
            </div>
          ) : (
            <SignalTable signals={filteredSignals ?? dashboard.recent_signals} />
          )}
        </div>
      )}
    </div>
  );
}
