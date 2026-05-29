import { type ReactNode, useEffect, useState } from "react";
import ConfirmModal from "@/components/ConfirmModal";
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

  const [cryptoConfig, setCryptoConfig] = useState<botApi.CryptoConfig | null>(null);
  const [savingKalshi, setSavingKalshi] = useState(false);
  const [cryptoConfigMessage, setCryptoConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [cryptoModeModal, setCryptoModeModal] = useState<"paper" | "live" | null>(null);

  const [climateConfig, setClimateConfig] = useState<botApi.ClimateConfig | null>(null);
  const [savingClimate, setSavingClimate] = useState(false);
  const [climateConfigMessage, setClimateConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [climateModeModal, setClimateModeModal] = useState<"paper" | "live" | null>(null);

  const [dangerModal, setDangerModal] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [dangerMessage, setDangerMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [retraining, setRetraining] = useState(false);
  const [retrainResult, setRetrainResult] = useState<{ type: "success" | "error"; text: string } | null>(null);

  async function handleRetrainModel() {
    setRetraining(true);
    setRetrainResult(null);
    try {
      const res = await botApi.triggerRetrain();
      if (res.success) {
        setRetrainResult({ type: "success", text: `${res.message} (${res.model_file_size_kb} KB)` });
      } else {
        setRetrainResult({ type: "error", text: res.message });
      }
    } catch {
      setRetrainResult({ type: "error", text: "Manual retraining request failed." });
    } finally {
      setRetraining(false);
    }
  }

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKalshiKeysStatus);
    botApi.getCryptoConfig().then(setCryptoConfig);
    botApi.getClimateConfig().then(setClimateConfig);
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

  async function saveCryptoConfig(updates: Partial<botApi.CryptoConfig>) {
    setSavingKalshi(true);
    setCryptoConfigMessage(null);
    try {
      const result = await botApi.updateCryptoConfig(updates);
      setCryptoConfig(result);
      setCryptoConfigMessage({ type: "success", text: "Saved." });
      setTimeout(() => setCryptoConfigMessage(null), 2000);
    } catch {
      setCryptoConfigMessage({ type: "error", text: "Failed to save." });
    } finally {
      setSavingKalshi(false);
    }
  }

  async function saveClimateConfig(updates: Partial<botApi.ClimateConfig>) {
    setSavingClimate(true);
    setClimateConfigMessage(null);
    try {
      const result = await botApi.updateClimateConfig(updates);
      setClimateConfig(result);
      setClimateConfigMessage({ type: "success", text: "Saved." });
      setTimeout(() => setClimateConfigMessage(null), 2000);
    } catch {
      setClimateConfigMessage({ type: "error", text: "Failed to save." });
    } finally {
      setSavingClimate(false);
    }
  }

  async function handleResetData() {
    setResetting(true);
    setDangerMessage(null);
    try {
      const result = await settingsApi.resetData();
      setDangerMessage({ type: "success", text: `Cleared ${result.cleared.join(", ")}.` });
      setDangerModal(false);
    } catch {
      setDangerMessage({ type: "error", text: "Failed to clear data." });
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Kalshi Strategy Settings */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Kalshi Crypto Settings</h3>
          {savingKalshi && <span className="text-xs text-amber-400">Saving...</span>}
          {cryptoConfigMessage && (
            <span className={`text-xs ${cryptoConfigMessage.type === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {cryptoConfigMessage.text}
            </span>
          )}
        </div>

        {cryptoConfig && (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Mode:</label>
                <button
                  onClick={() => setCryptoModeModal(cryptoConfig.mode === "paper" ? "live" : "paper")}
                  className={`text-xs font-bold px-3 py-1 rounded transition-colors ${
                    cryptoConfig.mode === "live"
                      ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                      : "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
                  }`}
                >
                  {cryptoConfig.mode.toUpperCase()}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => saveCryptoConfig({ enabled: !cryptoConfig.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    cryptoConfig.enabled ? "bg-sky-600" : "bg-slate-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                      cryptoConfig.enabled ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>

            <ConfirmModal
              open={cryptoModeModal === "live"}
              title="Switch Kalshi to Live Mode"
              confirmLabel="Switch to Live"
              confirmClass="bg-red-600 hover:bg-red-500"
              onConfirm={() => {
                saveCryptoConfig({ mode: "live" });
                setCryptoModeModal(null);
              }}
              onCancel={() => setCryptoModeModal(null)}
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
              open={cryptoModeModal === "paper"}
              title="Switch Kalshi to Paper Mode"
              confirmLabel="Switch to Paper"
              onConfirm={() => {
                saveCryptoConfig({ mode: "paper" });
                setCryptoModeModal(null);
              }}
              onCancel={() => setCryptoModeModal(null)}
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
                    value={cryptoConfig.series_tickers}
                    onChange={(e) => setCryptoConfig({ ...cryptoConfig, series_tickers: e.target.value })}
                    onBlur={() => saveCryptoConfig({ series_tickers: cryptoConfig.series_tickers })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono"
                    placeholder="KXBTC,KXETH"
                  />
                  <p className="text-xs text-slate-500 mt-1">Comma-separated Kalshi series (e.g. KXBTC, KXETH)</p>
                </div>
                <ConfigField
                  label="Min 24h Volume"
                  description="Only trade markets with at least this many contracts traded in the last 24 hours."
                  value={cryptoConfig.min_volume_24h}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, min_volume_24h: v })}
                  onBlur={() => saveCryptoConfig({ min_volume_24h: cryptoConfig.min_volume_24h })}
                  step={50} min={0} max={10000}
                />
                <ConfigField
                  label="Min Price"
                  description="Skip markets priced below this (in dollars, e.g. 0.15 = 15 cents). Avoids extreme long-shots."
                  prefix="$"
                  value={cryptoConfig.min_price}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, min_price: v })}
                  onBlur={() => saveCryptoConfig({ min_price: cryptoConfig.min_price })}
                  step={0.01} min={0} max={0.95}
                />
                <ConfigField
                  label="Max Price"
                  description="Skip markets priced above this. Avoids near-certainties with tiny upside."
                  prefix="$"
                  value={cryptoConfig.max_price}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, max_price: v })}
                  onBlur={() => saveCryptoConfig({ max_price: cryptoConfig.max_price })}
                  step={0.01} min={0.05} max={0.99}
                />
                <ConfigField
                  label="Min Hours to Expiry"
                  description="Skip markets expiring sooner than this. 0 = include all. Prevents buying contracts about to settle."
                  suffix="hrs"
                  value={cryptoConfig.min_hours_to_expiry}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, min_hours_to_expiry: v })}
                  onBlur={() => saveCryptoConfig({ min_hours_to_expiry: cryptoConfig.min_hours_to_expiry })}
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
                  value={Math.round(cryptoConfig.min_edge * 100)}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, min_edge: v / 100 })}
                  onBlur={() => saveCryptoConfig({ min_edge: cryptoConfig.min_edge })}
                  step={1} min={1} max={50}
                />
                <ConfigField
                  label="Exit Edge"
                  description="Sell when the model's perceived edge drops to this level. -2% = exit when model no longer favors the position. -50% disables (hold to resolution)."
                  suffix="%"
                  value={Math.round(cryptoConfig.exit_edge * 100)}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, exit_edge: v / 100 })}
                  onBlur={() => saveCryptoConfig({ exit_edge: cryptoConfig.exit_edge })}
                  step={1} min={-50} max={0}
                />
              </div>
            </div>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Crypto Risk Management</h4>
              <p className="text-xs text-slate-500 mb-3">Changes save when you click away from a field.</p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Contracts per Signal"
                  description="Max contracts to buy per signal. Capped by max cost."
                  value={cryptoConfig.contracts_per_signal}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, contracts_per_signal: v })}
                  onBlur={() => saveCryptoConfig({ contracts_per_signal: cryptoConfig.contracts_per_signal })}
                  step={5} min={1} max={500}
                />
                <ConfigField
                  label="Max Cost per Signal"
                  description="Caps total cost per signal. Reduces contract count for expensive contracts."
                  prefix="$"
                  value={cryptoConfig.max_cost_per_signal}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, max_cost_per_signal: v })}
                  onBlur={() => saveCryptoConfig({ max_cost_per_signal: cryptoConfig.max_cost_per_signal })}
                  step={5} min={1} max={1000}
                />
                <ConfigField
                  label="Max Open Positions"
                  description="Maximum concurrent Kalshi positions."
                  value={cryptoConfig.max_open_positions}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, max_open_positions: v })}
                  onBlur={() => saveCryptoConfig({ max_open_positions: cryptoConfig.max_open_positions })}
                  step={1} min={1} max={20}
                />
                <ConfigField
                  label="Max Positions / Event"
                  description="Buckets within an event are mutually exclusive — only one wins."
                  value={cryptoConfig.max_positions_per_event}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, max_positions_per_event: v })}
                  onBlur={() => saveCryptoConfig({ max_positions_per_event: cryptoConfig.max_positions_per_event })}
                  step={1} min={1} max={10}
                />
                <ConfigField
                  label="Stop Loss"
                  description="Close position if unrealized loss exceeds this percentage. 0 disables both stop-loss and catastrophic-stop — positions hold to resolution. Recommended for paper mode on binary/range markets where bid-ask noise can trigger premature exits."
                  suffix="%"
                  value={cryptoConfig.stop_loss_pct}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, stop_loss_pct: v })}
                  onBlur={() => saveCryptoConfig({ stop_loss_pct: cryptoConfig.stop_loss_pct })}
                  step={1} min={0} max={50}
                />
                <ConfigField
                  label="Take Profit"
                  description="Close position when unrealized gain reaches this percentage. 0 disables early exits on gains — lets the position ride to resolution. Pair with Stop Loss = 0 for full hold-to-resolution mode."
                  suffix="%"
                  value={cryptoConfig.take_profit_pct}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, take_profit_pct: v })}
                  onBlur={() => saveCryptoConfig({ take_profit_pct: cryptoConfig.take_profit_pct })}
                  step={1} min={0} max={500}
                />
                <ConfigField
                  label="Daily Loss Limit"
                  description="Pauses the Kalshi bot for the day if realized losses exceed this."
                  prefix="$"
                  value={cryptoConfig.daily_loss_limit_usd}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, daily_loss_limit_usd: v })}
                  onBlur={() => saveCryptoConfig({ daily_loss_limit_usd: cryptoConfig.daily_loss_limit_usd })}
                  step={5} min={0} max={10000}
                />
                <ConfigField
                  label="Max Signals/Hour"
                  description="Rate limit on new Kalshi signals. 0 = unlimited."
                  value={cryptoConfig.max_signals_per_hour}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, max_signals_per_hour: v })}
                  onBlur={() => saveCryptoConfig({ max_signals_per_hour: cryptoConfig.max_signals_per_hour })}
                  step={1} min={0} max={20}
                />
                <ConfigField
                  label="Min Hold Time"
                  description="Minimum minutes to hold before edge_lost exit can fire. Stop loss and approaching-expiry exits ignore this."
                  value={cryptoConfig.min_hold_minutes}
                  onChange={(v) => setCryptoConfig({ ...cryptoConfig, min_hold_minutes: v })}
                  onBlur={() => saveCryptoConfig({ min_hold_minutes: cryptoConfig.min_hold_minutes })}
                  suffix="min"
                  step={5} min={0} max={480}
                />
              </div>
            </div>
          </>
        )}
      </section>

      {/* SOTA ML Model — applies to both crypto and climate */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">SOTA Machine Learning Model</h3>
            <p className="text-xs text-slate-500">Synthetic Training on Binance (crypto) + Open-Meteo (climate)</p>
          </div>
          <span className="bg-emerald-500/20 text-emerald-400 text-[10px] font-bold px-2 py-0.5 rounded">
            ACTIVE
          </span>
        </div>

        <div className="grid grid-cols-3 gap-3 text-xs">
          <div className="bg-slate-950/40 p-3 rounded border border-slate-800/50">
            <span className="text-slate-500 block mb-0.5">Model Type</span>
            <span className="text-white font-mono font-medium">XGBoost Binary</span>
          </div>
          <div className="bg-slate-950/40 p-3 rounded border border-slate-800/50">
            <span className="text-slate-500 block mb-0.5">Auto-Retrain</span>
            <span className="text-white font-medium">Weekly (Sun 12 AM)</span>
          </div>
          <div className="bg-slate-950/40 p-3 rounded border border-slate-800/50">
            <span className="text-slate-500 block mb-0.5">Features</span>
            <span className="text-white font-medium">13 (crypto) · 29 (climate)</span>
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            onClick={handleRetrainModel}
            disabled={retraining}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-900 disabled:text-slate-600 text-xs font-medium text-white rounded border border-slate-700 transition-colors"
          >
            {retraining ? "Retraining Boosters..." : "Retrain Models Now"}
          </button>
          {retrainResult && (
            <span className={`text-[11px] font-medium ${retrainResult.type === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {retrainResult.text}
            </span>
          )}
        </div>
      </section>

      {/* Climate Bot Settings */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Kalshi Climate Settings</h3>
          {savingClimate && <span className="text-xs text-amber-400">Saving...</span>}
          {climateConfigMessage && (
            <span className={`text-xs ${climateConfigMessage.type === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {climateConfigMessage.text}
            </span>
          )}
        </div>

        {climateConfig && (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Mode:</label>
                <button
                  onClick={() => setClimateModeModal(climateConfig.mode === "paper" ? "live" : "paper")}
                  className={`text-xs font-bold px-3 py-1 rounded transition-colors ${
                    climateConfig.mode === "live"
                      ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                      : "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
                  }`}
                >
                  {climateConfig.mode.toUpperCase()}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => saveClimateConfig({ enabled: !climateConfig.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    climateConfig.enabled ? "bg-sky-600" : "bg-slate-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                      climateConfig.enabled ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>

            <ConfirmModal
              open={climateModeModal === "live"}
              title="Switch Climate to Live Mode"
              confirmLabel="Switch to Live"
              confirmClass="bg-red-600 hover:bg-red-500"
              onConfirm={() => {
                saveClimateConfig({ mode: "live" });
                setClimateModeModal(null);
              }}
              onCancel={() => setClimateModeModal(null)}
            >
              <p>You are about to enable <strong className="text-red-400">live trading</strong> on Climate markets:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Real orders will be placed on Kalshi using your API keys</li>
                <li>Real money will be at risk on every signal</li>
              </ul>
            </ConfirmModal>

            <ConfirmModal
              open={climateModeModal === "paper"}
              title="Switch Climate to Paper Mode"
              confirmLabel="Switch to Paper"
              onConfirm={() => {
                saveClimateConfig({ mode: "paper" });
                setClimateModeModal(null);
              }}
              onCancel={() => setClimateModeModal(null)}
            >
              <p>Switching Climate to <strong className="text-amber-400">paper mode</strong>. No real orders will be placed.</p>
            </ConfirmModal>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Market Filters</h4>
              <p className="text-xs text-slate-500 mb-3">
                Kalshi climate series to scan. Temperature, precipitation, and other weather markets.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-slate-400 mb-1 block">Series Tickers</label>
                  <input
                    type="text"
                    value={climateConfig.series_tickers}
                    onChange={(e) => setClimateConfig({ ...climateConfig, series_tickers: e.target.value })}
                    onBlur={() => saveClimateConfig({ series_tickers: climateConfig.series_tickers })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono"
                    placeholder="KXHITEMP-NYC,KXHITEMP-CHI"
                  />
                  <p className="text-xs text-slate-500 mt-1">Comma-separated Kalshi climate series</p>
                </div>
                <ConfigField
                  label="Min 24h Volume"
                  description="Only trade markets with at least this many contracts traded in the last 24 hours."
                  value={climateConfig.min_volume_24h}
                  onChange={(v) => setClimateConfig({ ...climateConfig, min_volume_24h: v })}
                  onBlur={() => saveClimateConfig({ min_volume_24h: climateConfig.min_volume_24h })}
                  step={10} min={0} max={10000}
                />
                <ConfigField
                  label="Min Price"
                  description="Skip markets priced below this."
                  prefix="$"
                  value={climateConfig.min_price}
                  onChange={(v) => setClimateConfig({ ...climateConfig, min_price: v })}
                  onBlur={() => saveClimateConfig({ min_price: climateConfig.min_price })}
                  step={0.01} min={0} max={0.95}
                />
                <ConfigField
                  label="Max Price"
                  description="Skip markets priced above this."
                  prefix="$"
                  value={climateConfig.max_price}
                  onChange={(v) => setClimateConfig({ ...climateConfig, max_price: v })}
                  onBlur={() => saveClimateConfig({ max_price: climateConfig.max_price })}
                  step={0.01} min={0.05} max={0.99}
                />
                <ConfigField
                  label="Min Hours to Expiry"
                  description="Skip markets expiring sooner than this."
                  suffix="hrs"
                  value={climateConfig.min_hours_to_expiry}
                  onChange={(v) => setClimateConfig({ ...climateConfig, min_hours_to_expiry: v })}
                  onBlur={() => saveClimateConfig({ min_hours_to_expiry: climateConfig.min_hours_to_expiry })}
                  step={1} min={0} max={72}
                />
              </div>
            </div>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Strategy Parameters</h4>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Min Edge"
                  description="Minimum edge to trigger a buy."
                  suffix="%"
                  value={Math.round(climateConfig.min_edge * 100)}
                  onChange={(v) => setClimateConfig({ ...climateConfig, min_edge: v / 100 })}
                  onBlur={() => saveClimateConfig({ min_edge: climateConfig.min_edge })}
                  step={1} min={1} max={50}
                />
                <ConfigField
                  label="Exit Edge"
                  description="Sell when the model's perceived edge drops to this level. -2% = exit when model no longer favors the position. -50% disables (hold to resolution)."
                  suffix="%"
                  value={Math.round(climateConfig.exit_edge * 100)}
                  onChange={(v) => setClimateConfig({ ...climateConfig, exit_edge: v / 100 })}
                  onBlur={() => saveClimateConfig({ exit_edge: climateConfig.exit_edge })}
                  step={1} min={-50} max={0}
                />
              </div>
            </div>

            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-sky-400 mb-1">Climate Risk Management</h4>
              <p className="text-xs text-slate-500 mb-3">Changes save when you click away from a field.</p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Contracts per Signal"
                  description="Max contracts to buy per signal."
                  value={climateConfig.contracts_per_signal}
                  onChange={(v) => setClimateConfig({ ...climateConfig, contracts_per_signal: v })}
                  onBlur={() => saveClimateConfig({ contracts_per_signal: climateConfig.contracts_per_signal })}
                  step={5} min={1} max={500}
                />
                <ConfigField
                  label="Max Cost per Signal"
                  description="Caps total cost per signal."
                  prefix="$"
                  value={climateConfig.max_cost_per_signal}
                  onChange={(v) => setClimateConfig({ ...climateConfig, max_cost_per_signal: v })}
                  onBlur={() => saveClimateConfig({ max_cost_per_signal: climateConfig.max_cost_per_signal })}
                  step={5} min={1} max={1000}
                />
                <ConfigField
                  label="Max Open Positions"
                  description="Maximum concurrent climate positions."
                  value={climateConfig.max_open_positions}
                  onChange={(v) => setClimateConfig({ ...climateConfig, max_open_positions: v })}
                  onBlur={() => saveClimateConfig({ max_open_positions: climateConfig.max_open_positions })}
                  step={1} min={1} max={20}
                />
                <ConfigField
                  label="Max Positions / Event"
                  description="Max positions per climate event."
                  value={climateConfig.max_positions_per_event}
                  onChange={(v) => setClimateConfig({ ...climateConfig, max_positions_per_event: v })}
                  onBlur={() => saveClimateConfig({ max_positions_per_event: climateConfig.max_positions_per_event })}
                  step={1} min={1} max={10}
                />
                <ConfigField
                  label="Stop Loss"
                  description="Close position if unrealized loss exceeds this percentage. 0 disables both stop-loss and catastrophic-stop — positions hold to resolution. Recommended for paper mode on daily-extreme markets where intraday price noise can trigger premature exits."
                  suffix="%"
                  value={climateConfig.stop_loss_pct}
                  onChange={(v) => setClimateConfig({ ...climateConfig, stop_loss_pct: v })}
                  onBlur={() => saveClimateConfig({ stop_loss_pct: climateConfig.stop_loss_pct })}
                  step={1} min={0} max={50}
                />
                <ConfigField
                  label="Take Profit"
                  description="Close position when unrealized gain reaches this percentage. 0 disables early exits on gains — lets the position ride to resolution. Pair with Stop Loss = 0 for full hold-to-resolution mode."
                  suffix="%"
                  value={climateConfig.take_profit_pct}
                  onChange={(v) => setClimateConfig({ ...climateConfig, take_profit_pct: v })}
                  onBlur={() => saveClimateConfig({ take_profit_pct: climateConfig.take_profit_pct })}
                  step={1} min={0} max={500}
                />
                <ConfigField
                  label="Daily Loss Limit"
                  description="Pauses the climate bot for the day if losses exceed this."
                  prefix="$"
                  value={climateConfig.daily_loss_limit_usd}
                  onChange={(v) => setClimateConfig({ ...climateConfig, daily_loss_limit_usd: v })}
                  onBlur={() => saveClimateConfig({ daily_loss_limit_usd: climateConfig.daily_loss_limit_usd })}
                  step={5} min={0} max={10000}
                />
                <ConfigField
                  label="Max Signals/Hour"
                  description="Rate limit on new climate signals. 0 = unlimited."
                  value={climateConfig.max_signals_per_hour}
                  onChange={(v) => setClimateConfig({ ...climateConfig, max_signals_per_hour: v })}
                  onBlur={() => saveClimateConfig({ max_signals_per_hour: climateConfig.max_signals_per_hour })}
                  step={1} min={0} max={20}
                />
                <ConfigField
                  label="Min Hold Time"
                  description="Minimum minutes to hold before edge_lost exit can fire."
                  value={climateConfig.min_hold_minutes}
                  onChange={(v) => setClimateConfig({ ...climateConfig, min_hold_minutes: v })}
                  onBlur={() => saveClimateConfig({ min_hold_minutes: climateConfig.min_hold_minutes })}
                  suffix="min"
                  step={5} min={0} max={480}
                />
              </div>
            </div>
          </>
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

      {/* Danger Zone */}
      <section className="bg-slate-900 border border-red-900/50 rounded-xl p-6 space-y-4 max-w-lg">
        <h3 className="text-lg font-semibold text-red-400">Danger Zone</h3>
        <p className="text-sm text-slate-400">
          Permanently delete all signal records from the database. This cannot be undone.
        </p>

        {dangerMessage && (
          <p className={`text-sm rounded-lg p-3 ${dangerMessage.type === "success" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-400/10 text-red-400"}`}>
            {dangerMessage.text}
          </p>
        )}

        <button
          onClick={() => setDangerModal(true)}
          disabled={resetting}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
        >
          {resetting ? "Clearing..." : "Clear All Signals"}
        </button>

        <ConfirmModal
          open={dangerModal}
          title="Clear All Signals"
          confirmLabel="Clear All Signals"
          confirmClass="bg-red-600 hover:bg-red-500"
          onConfirm={handleResetData}
          onCancel={() => setDangerModal(false)}
        >
          <p>This will permanently delete <strong className="text-red-400">all signal records</strong> from the database.</p>
          <ul className="list-disc list-inside space-y-1 text-slate-400">
            <li>All P&L history will be lost</li>
            <li>Dashboard charts will reset to zero</li>
            <li>This cannot be undone</li>
          </ul>
        </ConfirmModal>
      </section>
    </div>
  );
}
