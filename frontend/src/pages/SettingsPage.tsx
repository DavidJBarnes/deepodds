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

const STRATEGIES = [
  { value: "settlement_arb", label: "Settlement Arb", desc: "Buy near-certain contracts close to expiry at a discount. No model needed." },
  { value: "naive_no", label: "Naive NO", desc: "Buy NO on any range contract under 8¢. Baseline control strategy." },
  { value: "model", label: "BSM Model (V1)", desc: "Black-Scholes probability model. Legacy — kept for comparison." },
];

export default function SettingsPage() {
  const [keysStatus, setKeysStatus] = useState<settingsApi.KalshiKeysStatus | null>(null);
  const [keyId, setKeyId] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysMessage, setKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [config, setConfig] = useState<botApi.BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [configMessage, setConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [modeModal, setModeModal] = useState<"paper" | "live" | null>(null);
  const [kalshiBalance, setKalshiBalance] = useState<settingsApi.KalshiBalance | null>(null);

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKeysStatus);
    botApi.getBotConfig().then(setConfig);
    settingsApi.getKalshiBalance().then(setKalshiBalance).catch(() => {});
  }, []);

  async function handleSaveKeys(e: React.FormEvent) {
    e.preventDefault();
    setSavingKeys(true);
    setKeysMessage(null);
    try {
      const result = await settingsApi.updateKalshiKeys(keyId, privateKey);
      setKeysStatus(result);
      setKeyId("");
      setPrivateKey("");
      setKeysMessage({ type: "success", text: "Kalshi keys saved." });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to save keys";
      setKeysMessage({ type: "error", text: detail });
    } finally {
      setSavingKeys(false);
    }
  }

  async function handleDeleteKeys() {
    const result = await settingsApi.deleteKalshiKeys();
    setKeysStatus(result);
    setKeysMessage({ type: "success", text: "Kalshi keys removed." });
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
          <h3 className="text-lg font-semibold text-white">Strategy</h3>
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
              {config.strategy === "settlement_arb" && (
                <div className="flex items-center gap-2">
                  <label className="text-sm text-slate-400">Arb:</label>
                  <button
                    onClick={() => saveConfig({ settlement_arb_enabled: !config.settlement_arb_enabled })}
                    className={`relative w-10 h-5 rounded-full transition-colors ${
                      config.settlement_arb_enabled ? "bg-emerald-600" : "bg-slate-700"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                        config.settlement_arb_enabled ? "translate-x-5" : ""
                      }`}
                    />
                  </button>
                </div>
              )}
            </div>

            {/* Strategy selector */}
            <div>
              <label className="text-sm text-slate-400 mb-2 block">Strategy</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {STRATEGIES.map((s) => (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => saveConfig({ strategy: s.value })}
                    className={`text-left p-3 rounded-lg border transition-colors ${
                      config.strategy === s.value
                        ? "border-emerald-500 bg-emerald-500/10"
                        : "border-slate-700 bg-slate-800 hover:border-slate-600"
                    }`}
                  >
                    <span className={`text-sm font-medium block ${config.strategy === s.value ? "text-emerald-400" : "text-white"}`}>
                      {s.label}
                    </span>
                    <span className="text-xs text-slate-500 block mt-0.5">{s.desc}</span>
                  </button>
                ))}
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
                <li>Real orders will be placed on Kalshi using your API keys</li>
                <li>Real money will be at risk on every signal</li>
                <li>Losses are real and irreversible</li>
              </ul>
              {!keysStatus?.has_keys && (
                <p className="text-amber-400 font-medium mt-2">
                  You have not configured Kalshi API keys yet. Live orders will fail until keys are added.
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
                <li>Fills and exits are simulated against real market prices</li>
                <li>Existing live orders on Kalshi are not affected</li>
              </ul>
              <p className="mt-2 text-slate-500">Use this to test strategy changes without risking capital.</p>
            </ConfirmModal>

            {/* Settlement Arb params */}
            {config.strategy === "settlement_arb" && (
              <div className="border-t border-slate-800 pt-4">
                <h4 className="text-sm font-semibold text-emerald-400 mb-1">Settlement Arb Parameters</h4>
                <p className="text-xs text-slate-500 mb-3">
                  Controls when the bot enters near-expiry contracts. Changes save automatically when you click away from a field.
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <ConfigField
                    label="Max Minutes to Expiry"
                    description="Only consider contracts expiring within this many minutes."
                    suffix="min"
                    value={config.settlement_arb_max_minutes}
                    onChange={(v) => setConfig({ ...config, settlement_arb_max_minutes: v })}
                    onBlur={() => saveConfig({ settlement_arb_max_minutes: config.settlement_arb_max_minutes })}
                    step={5} min={1} max={240}
                  />
                  <ConfigField
                    label="Min Sigma Distance"
                    description="How many standard deviations spot must be from the nearest boundary. 1.5σ = 93% win probability."
                    suffix="σ"
                    value={config.settlement_arb_min_sigma}
                    onChange={(v) => setConfig({ ...config, settlement_arb_min_sigma: v })}
                    onBlur={() => saveConfig({ settlement_arb_min_sigma: config.settlement_arb_min_sigma })}
                    step={0.1} min={0.5} max={5}
                  />
                  <ConfigField
                    label="Min Discount"
                    description="Minimum cents below fair value required to enter."
                    suffix="cents"
                    value={config.settlement_arb_min_discount_cents}
                    onChange={(v) => setConfig({ ...config, settlement_arb_min_discount_cents: v })}
                    onBlur={() => saveConfig({ settlement_arb_min_discount_cents: config.settlement_arb_min_discount_cents })}
                    step={1} min={1} max={50}
                  />
                  <ConfigField
                    label="Max Position"
                    description="Maximum dollar value per settlement arb signal."
                    prefix="$"
                    value={config.settlement_arb_max_position_cents / 100}
                    onChange={(v) => setConfig({ ...config, settlement_arb_max_position_cents: Math.round(v * 100) })}
                    onBlur={() => saveConfig({ settlement_arb_max_position_cents: config.settlement_arb_max_position_cents })}
                    step={1} min={1} max={1000}
                  />
                </div>
              </div>
            )}

            {/* Risk Management */}
            <div className="border-t border-slate-800 pt-4">
              <h4 className="text-sm font-semibold text-slate-300 mb-1">Risk Management</h4>
              <p className="text-xs text-slate-500 mb-3">Changes save when you click away from a field.</p>
              <div className="grid grid-cols-2 gap-4">
                <ConfigField
                  label="Max Exposure"
                  description="Maximum capital tied up in open positions at once."
                  prefix="$"
                  value={config.max_exposure_cents / 100}
                  onChange={(v) => setConfig({ ...config, max_exposure_cents: Math.round(v * 100) })}
                  onBlur={() => saveConfig({ max_exposure_cents: config.max_exposure_cents })}
                  step={1} min={1} max={1000}
                >
                  {kalshiBalance && kalshiBalance.cash_cents > 0 && (
                    <span className="text-slate-400">
                      Kalshi cash: <span className="text-white">${(kalshiBalance.cash_cents / 100).toFixed(2)}</span>
                    </span>
                  )}
                </ConfigField>
                <ConfigField
                  label="Daily Budget"
                  description="Hard cap on total new position spend per day. 0 = unlimited."
                  prefix="$"
                  value={config.daily_budget_cents / 100}
                  onChange={(v) => setConfig({ ...config, daily_budget_cents: Math.round(v * 100) })}
                  onBlur={() => saveConfig({ daily_budget_cents: config.daily_budget_cents })}
                  step={1} min={0} max={1000}
                />
                <ConfigField
                  label="Daily Loss Limit"
                  description="Pauses the bot for the day if realized losses exceed this. 0 = disabled."
                  prefix="$"
                  value={config.daily_loss_limit_cents / 100}
                  onChange={(v) => setConfig({ ...config, daily_loss_limit_cents: Math.round(v * 100) })}
                  onBlur={() => saveConfig({ daily_loss_limit_cents: config.daily_loss_limit_cents })}
                  step={1} min={0} max={1000}
                />
                <ConfigField
                  label="Max Positions/Asset"
                  description="Limit concurrent open positions per BTC or ETH."
                  value={config.max_positions_per_asset}
                  onChange={(v) => setConfig({ ...config, max_positions_per_asset: v })}
                  onBlur={() => saveConfig({ max_positions_per_asset: config.max_positions_per_asset })}
                  step={1} min={0} max={20}
                />
                <ConfigField
                  label="Max Signals/Hour"
                  description="Rate limit on new signals. 0 = unlimited."
                  value={config.max_signals_per_hour}
                  onChange={(v) => setConfig({ ...config, max_signals_per_hour: v })}
                  onBlur={() => saveConfig({ max_signals_per_hour: config.max_signals_per_hour })}
                  step={1} min={0} max={50}
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
          <span className={`w-2.5 h-2.5 rounded-full ${keysStatus?.valid ? "bg-emerald-500" : keysStatus?.has_keys ? "bg-amber-500" : "bg-red-500"}`} />
          <span className="text-sm text-slate-300">
            {keysStatus?.valid ? `Keys valid (${keysStatus.key_id_preview})` : keysStatus?.has_keys ? `Keys invalid — re-enter them (${keysStatus.key_id_preview})` : "No keys configured"}
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
            <label className="block text-sm text-slate-400 mb-1">API Key ID</label>
            <input
              type="text"
              value={keyId}
              onChange={(e) => setKeyId(e.target.value)}
              placeholder="Your Kalshi API Key ID"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">RSA Private Key (PEM)</label>
            <textarea
              value={privateKey}
              onChange={(e) => setPrivateKey(e.target.value)}
              placeholder={"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"}
              rows={6}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono resize-y"
            />
          </div>
          <button
            type="submit"
            disabled={savingKeys || !keyId || !privateKey}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
          >
            {savingKeys ? "Saving..." : "Save API Keys"}
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Generate API keys at kalshi.com under Account → API Keys. Required for live trading mode.
        </p>
      </section>
    </div>
  );
}
