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
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
        />
        {suffix && <span className="text-slate-500 text-sm whitespace-nowrap">{suffix}</span>}
      </div>
      {children && <div className="text-xs text-slate-500 mt-1">{children}</div>}
    </div>
  );
}

export default function SettingsPage() {
  const [keysStatus, setKeysStatus] = useState<settingsApi.CoinbaseKeysStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysMessage, setKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [config, setConfig] = useState<botApi.BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [configMessage, setConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [modeModal, setModeModal] = useState<"paper" | "live" | null>(null);

  useEffect(() => {
    settingsApi.getCoinbaseKeysStatus().then(setKeysStatus);
    botApi.getBotConfig().then(setConfig);
  }, []);

  async function handleSaveKeys(e: React.FormEvent) {
    e.preventDefault();
    setSavingKeys(true);
    setKeysMessage(null);
    try {
      const result = await settingsApi.updateCoinbaseKeys(apiKey, privateKey);
      setKeysStatus(result);
      setApiKey("");
      setPrivateKey("");
      setKeysMessage({ type: "success", text: "Coinbase keys saved." });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to save keys";
      setKeysMessage({ type: "error", text: detail });
    } finally {
      setSavingKeys(false);
    }
  }

  async function handleDeleteKeys() {
    const result = await settingsApi.deleteCoinbaseKeys();
    setKeysStatus(result);
    setKeysMessage({ type: "success", text: "Coinbase keys removed." });
  }

  async function saveConfig(updates: Partial<botApi.BotConfig>) {
    setSaving(true);
    setConfigMessage(null);
    try {
      const result = await botApi.updateBotConfig(updates);
      setConfig(result);
      setConfigMessage({ type: "success", text: "Saved." });
      setTimeout(() => setConfigMessage(null), 2000);
    } catch {
      setConfigMessage({ type: "error", text: "Failed to save." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Strategy Settings */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Mean Reversion Bot</h3>
          {saving && <span className="text-xs text-amber-400">Saving...</span>}
          {configMessage && (
            <span className={`text-xs ${configMessage.type === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {configMessage.text}
            </span>
          )}
        </div>

        {config && (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Mode:</label>
                <button
                  onClick={() => setModeModal(config.mode === "paper" ? "live" : "paper")}
                  className={`text-xs font-bold px-3 py-1 rounded transition-colors ${
                    config.mode === "live"
                      ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                      : "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
                  }`}
                >
                  {config.mode.toUpperCase()}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => saveConfig({ enabled: !config.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    config.enabled ? "bg-amber-600" : "bg-slate-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                      config.enabled ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>

            <ConfirmModal
              open={modeModal === "live"}
              title="Switch to Live Mode"
              confirmLabel="Switch to Live"
              confirmClass="bg-red-600 hover:bg-red-500"
              onConfirm={() => {
                saveConfig({ mode: "live" });
                setModeModal(null);
              }}
              onCancel={() => setModeModal(null)}
            >
              <p>You are about to enable <strong className="text-red-400">live trading</strong>. This means:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Real orders will be placed on Coinbase using your API keys</li>
                <li>Real money will be at risk on every signal</li>
                <li>Losses are real and irreversible</li>
              </ul>
              {!keysStatus?.has_keys && (
                <p className="text-amber-400 font-medium mt-2">
                  You have not configured Coinbase API keys yet. Live orders will fail until keys are added.
                </p>
              )}
              <p className="mt-2 text-slate-500">You can switch back to paper mode at any time.</p>
            </ConfirmModal>

            <ConfirmModal
              open={modeModal === "paper"}
              title="Switch to Paper Mode"
              confirmLabel="Switch to Paper"
              onConfirm={() => {
                saveConfig({ mode: "paper" });
                setModeModal(null);
              }}
              onCancel={() => setModeModal(null)}
            >
              <p>Switching to <strong className="text-amber-400">paper mode</strong> means:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>No real orders will be placed</li>
                <li>Fills are simulated against real market prices</li>
              </ul>
              <p className="mt-2 text-slate-500">Use this to test parameter changes without risking capital.</p>
            </ConfirmModal>

            {/* Mean Reversion Parameters */}
            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-emerald-400 mb-1">Strategy Parameters</h4>
              <p className="text-xs text-slate-500 mb-3">
                Buy when price drops below VWAP by the entry z-score threshold. Sell when it reverts back. Changes save on blur.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-slate-400 mb-1 block">Trading Pairs</label>
                  <input
                    type="text"
                    value={config.pairs}
                    onChange={(e) => setConfig({ ...config, pairs: e.target.value })}
                    onBlur={() => saveConfig({ pairs: config.pairs })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
                    placeholder="BTC-USD,ETH-USD"
                  />
                  <p className="text-xs text-slate-500 mt-1">Comma-separated Coinbase product IDs</p>
                </div>
                <ConfigField
                  label="Lookback Periods"
                  description="Number of 15-minute candles for VWAP calculation. 16 = 4 hours, 32 = 8 hours."
                  suffix="bars"
                  value={config.lookback_periods}
                  onChange={(v) => setConfig({ ...config, lookback_periods: v })}
                  onBlur={() => saveConfig({ lookback_periods: config.lookback_periods })}
                  step={4} min={4} max={96}
                />
                <ConfigField
                  label="Entry Z-Score"
                  description="Buy when z-score drops below this. -2.0 = price is 2 std devs below VWAP (oversold). More negative = pickier entries."
                  suffix="z"
                  value={config.entry_z_score}
                  onChange={(v) => setConfig({ ...config, entry_z_score: v })}
                  onBlur={() => saveConfig({ entry_z_score: config.entry_z_score })}
                  step={0.1} min={-5} max={-0.5}
                />
                <ConfigField
                  label="Exit Z-Score"
                  description="Sell when z-score rises above this. 0.0 = price has reverted to VWAP. Positive = wait for overshoot."
                  suffix="z"
                  value={config.exit_z_score}
                  onChange={(v) => setConfig({ ...config, exit_z_score: v })}
                  onBlur={() => saveConfig({ exit_z_score: config.exit_z_score })}
                  step={0.1} min={-1} max={3}
                />
              </div>
            </div>

            {/* Risk Management */}
            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-slate-300 mb-1">Risk Management</h4>
              <p className="text-xs text-slate-500 mb-3">Changes save when you click away from a field.</p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Position Size"
                  description="Dollar amount per trade. The bot buys this much of each pair when the entry signal triggers."
                  prefix="$"
                  value={config.position_size_usd}
                  onChange={(v) => setConfig({ ...config, position_size_usd: v })}
                  onBlur={() => saveConfig({ position_size_usd: config.position_size_usd })}
                  step={5} min={5} max={1000}
                />
                <ConfigField
                  label="Max Open Positions"
                  description="Maximum concurrent positions across all pairs."
                  value={config.max_open_positions}
                  onChange={(v) => setConfig({ ...config, max_open_positions: v })}
                  onBlur={() => saveConfig({ max_open_positions: config.max_open_positions })}
                  step={1} min={1} max={10}
                />
                <ConfigField
                  label="Stop Loss"
                  description="Close position if unrealized loss exceeds this percentage."
                  suffix="%"
                  value={config.stop_loss_pct}
                  onChange={(v) => setConfig({ ...config, stop_loss_pct: v })}
                  onBlur={() => saveConfig({ stop_loss_pct: config.stop_loss_pct })}
                  step={0.5} min={0.5} max={20}
                />
                <ConfigField
                  label="Daily Loss Limit"
                  description="Pauses the bot for the day if realized losses exceed this. 0 = disabled."
                  prefix="$"
                  value={config.daily_loss_limit_usd}
                  onChange={(v) => setConfig({ ...config, daily_loss_limit_usd: v })}
                  onBlur={() => saveConfig({ daily_loss_limit_usd: config.daily_loss_limit_usd })}
                  step={5} min={0} max={10000}
                />
                <ConfigField
                  label="Max Signals/Hour"
                  description="Rate limit on new signals. 0 = unlimited."
                  value={config.max_signals_per_hour}
                  onChange={(v) => setConfig({ ...config, max_signals_per_hour: v })}
                  onBlur={() => saveConfig({ max_signals_per_hour: config.max_signals_per_hour })}
                  step={1} min={0} max={20}
                />
              </div>
            </div>
          </>
        )}
      </section>

      {/* Coinbase API Keys */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4 max-w-lg">
        <h3 className="text-lg font-semibold text-white">Coinbase API Keys</h3>
        <div className="flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-full ${keysStatus?.valid ? "bg-emerald-500" : keysStatus?.has_keys ? "bg-amber-500" : "bg-red-500"}`} />
          <span className="text-sm text-slate-300">
            {keysStatus?.valid ? `Keys valid (${keysStatus.key_preview})` : keysStatus?.has_keys ? `Keys invalid (${keysStatus.key_preview})` : "No keys configured"}
          </span>
          {keysStatus?.has_keys && (
            <button onClick={handleDeleteKeys} className="ml-auto text-sm text-red-400 hover:text-red-300">
              Remove
            </button>
          )}
        </div>

        {keysMessage && (
          <p className={`text-sm rounded-lg p-3 ${keysMessage.type === "success" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-400/10 text-red-400"}`}>
            {keysMessage.text}
          </p>
        )}

        <form onSubmit={handleSaveKeys} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">API Key Name</label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="organizations/…/apiKeys/…"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Private Key (PEM)</label>
            <textarea
              value={privateKey}
              onChange={(e) => setPrivateKey(e.target.value)}
              placeholder={"-----BEGIN EC PRIVATE KEY-----\n…\n-----END EC PRIVATE KEY-----"}
              rows={4}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono resize-none"
            />
          </div>
          <button
            type="submit"
            disabled={savingKeys || !apiKey || !privateKey}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
          >
            {savingKeys ? "Saving..." : "Save API Keys"}
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Create a CDP API key at <span className="text-slate-400">coinbase.com &rarr; Settings &rarr; API</span>. Choose "Trading" permissions. You'll get an API key name and a private key (PEM). Required for live mode.
        </p>
      </section>
    </div>
  );
}
