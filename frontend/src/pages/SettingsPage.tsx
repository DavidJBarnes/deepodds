import { type ReactNode, useEffect, useState } from "react";
import ConfirmModal from "@/components/ConfirmModal";
import BacktestPreview from "@/components/BacktestPreview";
import * as settingsApi from "@/api/settings";
import * as botApi from "@/api/bot";

function ConfigField({
  label,
  description,
  prefix,
  suffix,
  value,
  onChange,
  onBlur,
  step,
  min,
  max,
  children,
}: {
  label: string;
  description: string;
  prefix?: string;
  suffix?: string;
  value: number;
  onChange: (v: number) => void;
  onBlur?: () => void;
  step: number;
  min: number;
  max: number;
  children?: ReactNode;
}) {
  const [showTip, setShowTip] = useState(false);
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1">
        <label className="text-sm text-slate-400">{label}</label>
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowTip(!showTip)}
            onBlur={() => setShowTip(false)}
            className="text-slate-600 hover:text-slate-400 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
              <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM8.94 6.94a.75.75 0 1 1-1.061-1.061 3 3 0 1 1 2.871 5.026v.345a.75.75 0 0 1-1.5 0v-.5c0-.72.57-1.172 1.081-1.287A1.5 1.5 0 1 0 8.94 6.94ZM10 15a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clipRule="evenodd" />
            </svg>
          </button>
          {showTip && (
            <div className="absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-300 shadow-xl">
              {description}
              <div className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 bg-slate-800 border-r border-b border-slate-700 rotate-45 -mt-1" />
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {prefix && <span className="text-slate-500 text-sm">{prefix}</span>}
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          onBlur={onBlur}
          step={step}
          min={min}
          max={max}
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
        />
        {suffix && <span className="text-slate-500 text-sm whitespace-nowrap">{suffix}</span>}
      </div>
      {children && <div className="text-xs text-slate-500 mt-1">{children}</div>}
    </div>
  );
}

export default function SettingsPage() {
  const [kalshiKeysStatus, setKalshiKeysStatus] = useState<settingsApi.KalshiKeysStatus | null>(null);
  const [kalshiKeyId, setKalshiKeyId] = useState("");
  const [kalshiPem, setKalshiPem] = useState("");
  const [savingKalshiKeys, setSavingKalshiKeys] = useState(false);
  const [kalshiKeysMessage, setKalshiKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [kalshiConfig, setKalshiConfig] = useState<botApi.KalshiConfig | null>(null);
  const [savingKalshi, setSavingKalshi] = useState(false);
  const [kalshiConfigMessage, setKalshiConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [kalshiModeModal, setKalshiModeModal] = useState<"paper" | "live" | null>(null);

  const [pairConfigs, setPairConfigs] = useState<botApi.PairConfig[]>([]);
  const [showOverrides, setShowOverrides] = useState(false);

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKalshiKeysStatus);
    botApi.getKalshiConfig().then(setKalshiConfig);
    botApi.getPairConfigs().then(setPairConfigs);
  }, []);

  async function handleSaveKalshiKeys(e: React.FormEvent) {
    e.preventDefault();
    setSavingKalshiKeys(true);
    setKalshiKeysMessage(null);
    try {
      const result = await settingsApi.updateKalshiKeys(kalshiKeyId, kalshiPem);
      setKalshiKeysStatus(result);
      setKalshiKeyId("");
      setKalshiPem("");
      setKalshiKeysMessage({ type: "success", text: "Kalshi keys saved." });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to save keys";
      setKalshiKeysMessage({ type: "error", text: detail });
    } finally {
      setSavingKalshiKeys(false);
    }
  }

  async function handleDeleteKalshiKeys() {
    const result = await settingsApi.deleteKalshiKeys();
    setKalshiKeysStatus(result);
    setKalshiKeysMessage({ type: "success", text: "Kalshi keys removed." });
  }

  async function saveKalshiConfig(updates: Partial<botApi.KalshiConfig>) {
    setSavingKalshi(true);
    setKalshiConfigMessage(null);
    try {
      const result = await botApi.updateKalshiConfig(updates);
      setKalshiConfig(result);
      setKalshiConfigMessage({ type: "success", text: "Saved." });
      setTimeout(() => setKalshiConfigMessage(null), 2000);
    } catch {
      setKalshiConfigMessage({ type: "error", text: "Failed to save." });
    } finally {
      setSavingKalshi(false);
    }
  }

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Kalshi Strategy Settings */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Kalshi Event Contracts</h3>
          {savingKalshi && <span className="text-xs text-amber-400">Saving...</span>}
          {kalshiConfigMessage && (
            <span className={`text-xs ${kalshiConfigMessage.type === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {kalshiConfigMessage.text}
            </span>
          )}
        </div>

        {kalshiConfig && (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Mode:</label>
                <button
                  onClick={() => setKalshiModeModal(kalshiConfig.mode === "paper" ? "live" : "paper")}
                  className={`text-xs font-bold px-3 py-1 rounded transition-colors ${
                    kalshiConfig.mode === "live"
                      ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                      : "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
                  }`}
                >
                  {kalshiConfig.mode.toUpperCase()}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => saveKalshiConfig({ enabled: !kalshiConfig.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    kalshiConfig.enabled ? "bg-sky-600" : "bg-slate-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                      kalshiConfig.enabled ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>

            <ConfirmModal
              open={kalshiModeModal === "live"}
              title="Switch Kalshi to Live Mode"
              confirmLabel="Switch to Live"
              confirmClass="bg-red-600 hover:bg-red-500"
              onConfirm={() => {
                saveKalshiConfig({ mode: "live" });
                setKalshiModeModal(null);
              }}
              onCancel={() => setKalshiModeModal(null)}
            >
              <p>You are about to enable <strong className="text-red-400">live trading</strong> on Kalshi:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Real orders will be placed on Kalshi using your API keys</li>
                <li>Real money will be at risk on every signal</li>
                <li>Losses are real and irreversible</li>
              </ul>
              {!kalshiKeysStatus?.has_keys && (
                <p className="text-amber-400 font-medium mt-2">
                  You have not configured Kalshi API keys yet. Live orders will fail until keys are added.
                </p>
              )}
              <p className="mt-2 text-slate-500">You can switch back to paper mode at any time.</p>
            </ConfirmModal>

            <ConfirmModal
              open={kalshiModeModal === "paper"}
              title="Switch Kalshi to Paper Mode"
              confirmLabel="Switch to Paper"
              onConfirm={() => {
                saveKalshiConfig({ mode: "paper" });
                setKalshiModeModal(null);
              }}
              onCancel={() => setKalshiModeModal(null)}
            >
              <p>Switching Kalshi to <strong className="text-amber-400">paper mode</strong> means:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>No real orders will be placed on Kalshi</li>
                <li>Fills are simulated against real market prices</li>
              </ul>
              <p className="mt-2 text-slate-500">Use this to test parameter changes without risking capital.</p>
            </ConfirmModal>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Market Filters</h4>
              <p className="text-xs text-slate-500 mb-3">
                Kalshi crypto series to scan. Markets are filtered by volume, price range, and time to expiry.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-slate-400 mb-1 block">Series Tickers</label>
                  <input
                    type="text"
                    value={kalshiConfig.series_tickers}
                    onChange={(e) => setKalshiConfig({ ...kalshiConfig, series_tickers: e.target.value })}
                    onBlur={() => saveKalshiConfig({ series_tickers: kalshiConfig.series_tickers })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono"
                    placeholder="KXBTC,KXETH"
                  />
                  <p className="text-xs text-slate-500 mt-1">Comma-separated Kalshi series (e.g. KXBTC, KXETH)</p>
                </div>
                <ConfigField
                  label="Min 24h Volume"
                  description="Only trade markets with at least this many contracts traded in the last 24 hours."
                  value={kalshiConfig.min_volume_24h}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, min_volume_24h: v })}
                  onBlur={() => saveKalshiConfig({ min_volume_24h: kalshiConfig.min_volume_24h })}
                  step={50} min={0} max={10000}
                />
                <ConfigField
                  label="Min Price"
                  description="Skip markets priced below this (in dollars, e.g. 0.15 = 15 cents). Avoids extreme long-shots."
                  prefix="$"
                  value={kalshiConfig.min_price}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, min_price: v })}
                  onBlur={() => saveKalshiConfig({ min_price: kalshiConfig.min_price })}
                  step={0.01} min={0} max={0.95}
                />
                <ConfigField
                  label="Max Price"
                  description="Skip markets priced above this. Avoids near-certainties with tiny upside."
                  prefix="$"
                  value={kalshiConfig.max_price}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, max_price: v })}
                  onBlur={() => saveKalshiConfig({ max_price: kalshiConfig.max_price })}
                  step={0.01} min={0.05} max={0.99}
                />
                <ConfigField
                  label="Min Hours to Expiry"
                  description="Skip markets expiring sooner than this. 0 = include all. Prevents buying contracts about to settle."
                  suffix="hrs"
                  value={kalshiConfig.min_hours_to_expiry}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, min_hours_to_expiry: v })}
                  onBlur={() => saveKalshiConfig({ min_hours_to_expiry: kalshiConfig.min_hours_to_expiry })}
                  step={1} min={0} max={72}
                />
              </div>
            </div>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Strategy Parameters</h4>
              <p className="text-xs text-slate-500 mb-3">
                Fair-value probability model. Buy when the model's probability exceeds the market price by the min edge. Uses realized volatility from Binance.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Min Edge"
                  description="Minimum edge (model prob - market price) to trigger a buy. 0.05 = buy when model says 5%+ more likely than the market price implies."
                  suffix="%"
                  value={Math.round(kalshiConfig.min_edge * 100)}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, min_edge: v / 100 })}
                  onBlur={() => saveKalshiConfig({ min_edge: kalshiConfig.min_edge })}
                  step={1} min={1} max={50}
                />
                <ConfigField
                  label="Exit Edge"
                  description="Sell when edge drops below this. -2% = exit when the model no longer favors the position."
                  suffix="%"
                  value={Math.round(kalshiConfig.exit_edge * 100)}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, exit_edge: v / 100 })}
                  onBlur={() => saveKalshiConfig({ exit_edge: kalshiConfig.exit_edge })}
                  step={1} min={-50} max={0}
                />
                <ConfigField
                  label="Vol Lookback"
                  description="Hours of Binance kline data used to compute realized volatility. 24 = 1 day of price history."
                  suffix="hrs"
                  value={kalshiConfig.vol_lookback_hours}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, vol_lookback_hours: v })}
                  onBlur={() => saveKalshiConfig({ vol_lookback_hours: kalshiConfig.vol_lookback_hours })}
                  step={1} min={1} max={168}
                />
                <div>
                  <label className="text-sm text-slate-400 mb-1 block">Vol Interval</label>
                  <select
                    value={kalshiConfig.vol_interval}
                    onChange={(e) => {
                      setKalshiConfig({ ...kalshiConfig, vol_interval: e.target.value });
                      saveKalshiConfig({ vol_interval: e.target.value });
                    }}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                  >
                    <option value="5m">5 min</option>
                    <option value="15m">15 min</option>
                    <option value="1h">1 hour</option>
                  </select>
                  <p className="text-xs text-slate-500 mt-1">Kline interval for volatility calculation</p>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-slate-300 mb-1">Kalshi Risk Management</h4>
              <p className="text-xs text-slate-500 mb-3">Changes save when you click away from a field.</p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Contracts per Signal"
                  description="Max contracts to buy per signal. Capped by max cost."
                  value={kalshiConfig.contracts_per_signal}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, contracts_per_signal: v })}
                  onBlur={() => saveKalshiConfig({ contracts_per_signal: kalshiConfig.contracts_per_signal })}
                  step={5} min={1} max={500}
                />
                <ConfigField
                  label="Max Cost per Signal"
                  description="Caps total cost per signal. Reduces contract count for expensive contracts."
                  prefix="$"
                  value={kalshiConfig.max_cost_per_signal}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, max_cost_per_signal: v })}
                  onBlur={() => saveKalshiConfig({ max_cost_per_signal: kalshiConfig.max_cost_per_signal })}
                  step={5} min={1} max={1000}
                />
                <ConfigField
                  label="Max Open Positions"
                  description="Maximum concurrent Kalshi positions."
                  value={kalshiConfig.max_open_positions}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, max_open_positions: v })}
                  onBlur={() => saveKalshiConfig({ max_open_positions: kalshiConfig.max_open_positions })}
                  step={1} min={1} max={20}
                />
                <ConfigField
                  label="Max Positions / Event"
                  description="Buckets within an event are mutually exclusive — only one wins."
                  value={kalshiConfig.max_positions_per_event}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, max_positions_per_event: v })}
                  onBlur={() => saveKalshiConfig({ max_positions_per_event: kalshiConfig.max_positions_per_event })}
                  step={1} min={1} max={10}
                />
                <ConfigField
                  label="Stop Loss"
                  description="Close position if unrealized loss exceeds this percentage."
                  suffix="%"
                  value={kalshiConfig.stop_loss_pct}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, stop_loss_pct: v })}
                  onBlur={() => saveKalshiConfig({ stop_loss_pct: kalshiConfig.stop_loss_pct })}
                  step={1} min={1} max={50}
                />
                <ConfigField
                  label="Daily Loss Limit"
                  description="Pauses the Kalshi bot for the day if realized losses exceed this."
                  prefix="$"
                  value={kalshiConfig.daily_loss_limit_usd}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, daily_loss_limit_usd: v })}
                  onBlur={() => saveKalshiConfig({ daily_loss_limit_usd: kalshiConfig.daily_loss_limit_usd })}
                  step={5} min={0} max={10000}
                />
                <ConfigField
                  label="Max Signals/Hour"
                  description="Rate limit on new Kalshi signals. 0 = unlimited."
                  value={kalshiConfig.max_signals_per_hour}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, max_signals_per_hour: v })}
                  onBlur={() => saveKalshiConfig({ max_signals_per_hour: kalshiConfig.max_signals_per_hour })}
                  step={1} min={0} max={20}
                />
                <ConfigField
                  label="Min Hold Time"
                  description="Minimum minutes to hold before edge_lost exit can fire. Stop loss and approaching-expiry exits ignore this."
                  value={kalshiConfig.min_hold_minutes}
                  onChange={(v) => setKalshiConfig({ ...kalshiConfig, min_hold_minutes: v })}
                  onBlur={() => saveKalshiConfig({ min_hold_minutes: kalshiConfig.min_hold_minutes })}
                  suffix="min"
                  step={5} min={0} max={480}
                />
              </div>
            </div>
          </>
        )}
      </section>

      {/* Per-Pair Overrides */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <button
          onClick={() => setShowOverrides(!showOverrides)}
          className="flex items-center gap-2 w-full text-left"
        >
          <span className={`text-slate-500 transition-transform ${showOverrides ? "rotate-90" : ""}`}>&#9654;</span>
          <h3 className="text-lg font-semibold text-white">Per-Series Overrides</h3>
          <span className="text-xs text-slate-500 ml-2">
            {pairConfigs.length > 0 ? `${pairConfigs.length} active` : "None set"}
          </span>
        </button>

        {showOverrides && (
          <div className="space-y-4 pt-2">
            <p className="text-xs text-slate-500">
              Override global parameters for individual Kalshi series. Leave fields empty to use the global default. Changes auto-save on blur.
            </p>

            {kalshiConfig && (
              <>
                <h4 className="text-sm font-semibold text-sky-400">Kalshi Series</h4>
                {kalshiConfig.series_tickers.split(",").map((s) => s.trim()).filter(Boolean).map((series) => {
                  const pc = pairConfigs.find((c) => c.venue === "kalshi" && c.pair === series);
                  return (
                    <PairOverrideCard
                      key={`kalshi-${series}`}
                      venue="kalshi"
                      pair={series}
                      override={pc || null}
                      globalMinEdge={kalshiConfig.min_edge}
                      globalExitEdge={kalshiConfig.exit_edge}
                      globalStopLoss={kalshiConfig.stop_loss_pct}
                      globalContracts={kalshiConfig.contracts_per_signal}
                      volLookbackHours={kalshiConfig.vol_lookback_hours}
                      onSave={async (updates) => {
                        const result = await botApi.updatePairConfig("kalshi", series, updates);
                        setPairConfigs((prev) => {
                          const filtered = prev.filter((c) => !(c.venue === "kalshi" && c.pair === series));
                          return [...filtered, result];
                        });
                      }}
                      onClear={async () => {
                        try {
                          await botApi.deletePairConfig("kalshi", series);
                          setPairConfigs((prev) => prev.filter((c) => !(c.venue === "kalshi" && c.pair === series)));
                        } catch { /* not found is fine */ }
                      }}
                    />
                  );
                })}
              </>
            )}
          </div>
        )}
      </section>

      {/* Kalshi API Keys */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4 max-w-lg">
        <h3 className="text-lg font-semibold text-white">Kalshi API Keys</h3>
        <div className="flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-full ${kalshiKeysStatus?.valid ? "bg-emerald-500" : kalshiKeysStatus?.has_keys ? "bg-amber-500" : "bg-red-500"}`} />
          <span className="text-sm text-slate-300">
            {kalshiKeysStatus?.valid ? `Keys valid (${kalshiKeysStatus.key_preview})` : kalshiKeysStatus?.has_keys ? `Keys invalid (${kalshiKeysStatus.key_preview})` : "No keys configured"}
          </span>
          {kalshiKeysStatus?.has_keys && (
            <button onClick={handleDeleteKalshiKeys} className="ml-auto text-sm text-red-400 hover:text-red-300">
              Remove
            </button>
          )}
        </div>

        {kalshiKeysMessage && (
          <p className={`text-sm rounded-lg p-3 ${kalshiKeysMessage.type === "success" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-400/10 text-red-400"}`}>
            {kalshiKeysMessage.text}
          </p>
        )}

        <form onSubmit={handleSaveKalshiKeys} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">API Key ID</label>
            <input
              type="text"
              value={kalshiKeyId}
              onChange={(e) => setKalshiKeyId(e.target.value)}
              placeholder="kalshi-api-key-id"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Private Key (PEM)</label>
            <textarea
              value={kalshiPem}
              onChange={(e) => setKalshiPem(e.target.value)}
              placeholder="-----BEGIN RSA PRIVATE KEY-----"
              rows={4}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono resize-none"
            />
          </div>
          <button
            type="submit"
            disabled={savingKalshiKeys || !kalshiKeyId || !kalshiPem}
            className="px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
          >
            {savingKalshiKeys ? "Saving..." : "Save Kalshi Keys"}
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Create API credentials at <span className="text-slate-400">kalshi.com &rarr; Settings &rarr; API Keys</span>. You'll get an API key ID and an RSA private key (PEM format). Required for live mode.
        </p>
      </section>
    </div>
  );
}

function PairOverrideCard({
  venue,
  pair,
  override,
  globalStopLoss,
  globalContracts,
  globalMinEdge,
  globalExitEdge,
  volLookbackHours,
  onSave,
  onClear,
}: {
  venue: string;
  pair: string;
  override: botApi.PairConfig | null;
  globalStopLoss: number;
  globalContracts?: number;
  globalMinEdge?: number;
  globalExitEdge?: number;
  volLookbackHours?: number;
  onSave: (updates: Partial<botApi.PairConfig>) => Promise<void>;
  onClear: () => Promise<void>;
}) {
  const [stopLoss, setStopLoss] = useState<string>(override?.stop_loss_pct?.toString() ?? "");
  const [contracts, setContracts] = useState<string>(override?.contracts_per_signal?.toString() ?? "");
  const [minEdge, setMinEdge] = useState<string>(override?.min_edge != null ? (override.min_edge * 100).toString() : "");
  const [exitEdge, setExitEdge] = useState<string>(override?.exit_edge != null ? (override.exit_edge * 100).toString() : "");
  const [saving, setSaving] = useState(false);

  const effStopLoss = stopLoss ? parseFloat(stopLoss) : globalStopLoss;
  const effContracts = contracts ? parseInt(contracts) : (globalContracts ?? 50);
  const effMinEdge = minEdge ? parseFloat(minEdge) / 100 : (globalMinEdge ?? 0.05);
  const effExitEdge = exitEdge ? parseFloat(exitEdge) / 100 : (globalExitEdge ?? -0.02);

  const hasOverride = minEdge || exitEdge || stopLoss || contracts;

  async function handleBlur() {
    const updates: Partial<botApi.PairConfig> = {};
    if (minEdge) updates.min_edge = parseFloat(minEdge) / 100;
    if (exitEdge) updates.exit_edge = parseFloat(exitEdge) / 100;
    if (contracts) updates.contracts_per_signal = parseInt(contracts);
    if (stopLoss) updates.stop_loss_pct = parseFloat(stopLoss);

    if (Object.keys(updates).length === 0) return;

    setSaving(true);
    try { await onSave(updates); } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleClear() {
    setStopLoss("");
    setContracts("");
    setMinEdge("");
    setExitEdge("");
    await onClear();
  }

  return (
    <div className={`bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-mono text-sm font-semibold text-white`}>{pair}</span>
          {hasOverride && (
            <span className={`text-[10px] font-bold uppercase tracking-wider bg-sky-500/20 text-sky-400 px-1.5 py-0.5 rounded`}>
              Custom
            </span>
          )}
          {saving && <span className="text-[10px] text-amber-400">Saving...</span>}
        </div>
        {hasOverride && (
          <button onClick={handleClear} className="text-xs text-slate-500 hover:text-red-400 transition-colors">
            Clear overrides
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-slate-500 block mb-0.5">Min Edge % ({globalMinEdge != null ? (globalMinEdge * 100).toFixed(0) : "8"})</label>
          <input type="number" value={minEdge} onChange={(e) => setMinEdge(e.target.value)} onBlur={handleBlur}
            placeholder={(globalMinEdge != null ? (globalMinEdge * 100).toFixed(0) : "5")} step={1} min={1} max={50}
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm focus:outline-none focus:ring-1 focus:ring-sky-500 tabular-nums" />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-0.5">Exit Edge % ({globalExitEdge != null ? (globalExitEdge * 100).toFixed(0) : "-2"})</label>
          <input type="number" value={exitEdge} onChange={(e) => setExitEdge(e.target.value)} onBlur={handleBlur}
            placeholder={(globalExitEdge != null ? (globalExitEdge * 100).toFixed(0) : "-2")} step={1} min={-50} max={0}
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm focus:outline-none focus:ring-1 focus:ring-sky-500 tabular-nums" />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-0.5">Contracts ({globalContracts})</label>
          <input type="number" value={contracts} onChange={(e) => setContracts(e.target.value)} onBlur={handleBlur}
            placeholder={(globalContracts ?? 50).toString()} step={5} min={1} max={10000}
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm focus:outline-none focus:ring-1 focus:ring-sky-500 tabular-nums" />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-0.5">Stop Loss % ({globalStopLoss})</label>
          <input type="number" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} onBlur={handleBlur}
            placeholder={globalStopLoss.toString()} step={0.5} min={0.5} max={50}
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm focus:outline-none focus:ring-1 focus:ring-sky-500 tabular-nums" />
        </div>
      </div>

      <BacktestPreview
        venue={venue}
        pair={pair}
        stopLoss={effStopLoss}
        contracts={effContracts}
        minEdge={effMinEdge}
        exitEdge={effExitEdge}
        volLookbackHours={volLookbackHours}
      />
    </div>
  );
}
