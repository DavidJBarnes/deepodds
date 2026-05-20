import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useAuthStore } from "@/stores/authStore";
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
  const user = useAuthStore((s) => s.user);
  const [keysStatus, setKeysStatus] = useState<settingsApi.KalshiKeysStatus | null>(null);
  const [keyId, setKeyId] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysMessage, setKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [cbKeysStatus, setCbKeysStatus] = useState<settingsApi.CoinbaseKeysStatus | null>(null);
  const [cbKey, setCbKey] = useState("");
  const [cbSecret, setCbSecret] = useState("");
  const [savingCbKeys, setSavingCbKeys] = useState(false);
  const [cbKeysMessage, setCbKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [config, setConfig] = useState<botApi.BotConfig | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [modeModal, setModeModal] = useState<"paper" | "live" | null>(null);
  const [kalshiBalance, setKalshiBalance] = useState<settingsApi.KalshiBalance | null>(null);

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKeysStatus);
    settingsApi.getCoinbaseKeysStatus().then(setCbKeysStatus);
    botApi.getBotConfig().then(setConfig);
    settingsApi.getKalshiBalance().then(setKalshiBalance).catch(() => {});
  }, []);

  async function handleSaveKeys(e: FormEvent) {
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

  async function handleSaveCbKeys(e: FormEvent) {
    e.preventDefault();
    setSavingCbKeys(true);
    setCbKeysMessage(null);
    try {
      const result = await settingsApi.updateCoinbaseKeys(cbKey, cbSecret);
      setCbKeysStatus(result);
      setCbKey("");
      setCbSecret("");
      setCbKeysMessage({ type: "success", text: "Coinbase keys saved." });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to save keys";
      setCbKeysMessage({ type: "error", text: detail });
    } finally {
      setSavingCbKeys(false);
    }
  }

  async function handleDeleteCbKeys() {
    const result = await settingsApi.deleteCoinbaseKeys();
    setCbKeysStatus(result);
    setCbKeysMessage({ type: "success", text: "Coinbase keys removed." });
  }

  async function handleUpdateConfig(updates: Partial<botApi.BotConfig>) {
    setSavingConfig(true);
    setConfigMessage(null);
    try {
      const result = await botApi.updateBotConfig(updates);
      setConfig(result);
      setConfigMessage({ type: "success", text: "Settings saved." });
    } catch {
      setConfigMessage({ type: "error", text: "Failed to save settings." });
    } finally {
      setSavingConfig(false);
    }
  }

  function handleConfigSubmit(e: FormEvent) {
    e.preventDefault();
    if (!config) return;
    handleUpdateConfig({
      max_exposure_cents: config.max_exposure_cents,
      daily_budget_cents: config.daily_budget_cents,
      min_edge_cents: config.min_edge_cents,
      min_yes_prob: config.min_yes_prob,
      min_liquidity: config.min_liquidity,
      max_positions_per_asset: config.max_positions_per_asset,
      max_position_cents: config.max_position_cents,
      max_contracts_per_signal: config.max_contracts_per_signal,
      max_position_cents_moderate: config.max_position_cents_moderate,
      max_contracts_moderate: config.max_contracts_moderate,
      max_position_cents_high: config.max_position_cents_high,
      max_contracts_high: config.max_contracts_high,
      max_position_cents_elite: config.max_position_cents_elite,
      max_contracts_elite: config.max_contracts_elite,
      take_profit_cents: config.take_profit_cents,
      stop_loss_cents: config.stop_loss_cents,
      daily_loss_limit_cents: config.daily_loss_limit_cents,
      max_signals_per_hour: config.max_signals_per_hour,
      tier_budget_pct_elite: config.tier_budget_pct_elite,
      tier_budget_pct_high: config.tier_budget_pct_high,
    });
  }

  function handleSpotConfigSubmit(e: FormEvent) {
    e.preventDefault();
    if (!config) return;
    handleUpdateConfig({
      spot_dip_pct: config.spot_dip_pct,
      spot_take_profit_pct: config.spot_take_profit_pct,
      spot_stop_loss_pct: config.spot_stop_loss_pct,
      spot_buy_amount_usd: config.spot_buy_amount_usd,
      spot_max_position_usd: config.spot_max_position_usd,
      spot_cooldown_minutes: config.spot_cooldown_minutes,
    });
  }

  return (
    <div className="space-y-8 max-w-2xl">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Bot Config */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Bot Configuration</h3>

        {config && (
          <>
            <div className="flex items-center gap-4">
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
                <span className="text-xs text-slate-500">click to switch</span>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => handleUpdateConfig({ enabled: !config.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    config.enabled ? "bg-emerald-600" : "bg-slate-700"
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
                handleUpdateConfig({ mode: "live" });
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
                handleUpdateConfig({ mode: "paper" });
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

            {configMessage && (
              <p
                className={`text-sm rounded-lg p-3 ${
                  configMessage.type === "success"
                    ? "bg-emerald-500/10 text-emerald-400"
                    : "bg-red-400/10 text-red-400"
                }`}
              >
                {configMessage.text}
              </p>
            )}

            <form onSubmit={handleConfigSubmit} className="grid grid-cols-2 gap-4">
              <ConfigField
                label="Max Exposure"
                description="Maximum capital tied up in open positions at once. Freed when positions settle."
                prefix="$"
                value={config.max_exposure_cents / 100}
                onChange={(v) => setConfig({ ...config, max_exposure_cents: Math.round(v * 100) })}
                step={1} min={1} max={1000}
              >
                {kalshiBalance && kalshiBalance.cash_cents > 0 && (
                  <span className="text-slate-400">
                    Kalshi cash: <span className="text-white">${(kalshiBalance.cash_cents / 100).toFixed(2)}</span>
                  </span>
                )}
                {kalshiBalance && kalshiBalance.cash_cents > 0 && config.max_exposure_cents > kalshiBalance.cash_cents && (
                  <span className="text-amber-400 block">Exposure exceeds your Kalshi cash balance.</span>
                )}
              </ConfigField>
              <ConfigField
                label="Daily Budget"
                description="Hard cap on total new position spend per calendar day. 0 = unlimited."
                prefix="$"
                value={config.daily_budget_cents / 100}
                onChange={(v) => setConfig({ ...config, daily_budget_cents: Math.round(v * 100) })}
                step={1} min={0} max={1000}
              >
                {kalshiBalance && kalshiBalance.cash_cents > 0 && config.daily_budget_cents > 0 && config.daily_budget_cents > kalshiBalance.cash_cents && (
                  <span className="text-amber-400">Daily budget exceeds your Kalshi cash balance.</span>
                )}
              </ConfigField>
              <ConfigField
                label="Min Edge"
                description="Minimum fee-adjusted edge (in cents) the model must find before placing a signal. Lower = more signals but noisier."
                suffix="cents"
                value={config.min_edge_cents}
                onChange={(v) => setConfig({ ...config, min_edge_cents: v })}
                step={0.5} min={1} max={50}
              />
              <ConfigField
                label="Min YES Probability"
                description="Only buy YES when the model's probability exceeds this threshold. Filters out low-confidence longshot YES bets. 0 = no filter."
                suffix="%"
                value={config.min_yes_prob}
                onChange={(v) => setConfig({ ...config, min_yes_prob: v })}
                step={5} min={0} max={100}
              />
              <ConfigField
                label="Min Liquidity"
                description="Skip markets with fewer contracts available. Higher values avoid thin markets where fills are unreliable."
                value={config.min_liquidity}
                onChange={(v) => setConfig({ ...config, min_liquidity: v })}
                step={1} min={0} max={1000}
              />
              <ConfigField
                label="Max Positions/Asset"
                description="Limit concurrent open positions per underlying asset (BTC or ETH). Prevents correlated exposure to a single price move."
                value={config.max_positions_per_asset}
                onChange={(v) => setConfig({ ...config, max_positions_per_asset: v })}
                step={1} min={0} max={20}
              />
              <ConfigField
                label="Max Position"
                description="Maximum dollar value of a single position (speculative tier). Higher-edge tiers override this in the tier config below."
                prefix="$"
                value={config.max_position_cents / 100}
                onChange={(v) => setConfig({ ...config, max_position_cents: Math.round(v * 100) })}
                step={1} min={1} max={100}
              />
              <ConfigField
                label="Max Contracts/Signal"
                description="Upper limit on contracts per signal. Combined with max position to cap risk on any single trade."
                value={config.max_contracts_per_signal}
                onChange={(v) => setConfig({ ...config, max_contracts_per_signal: v })}
                step={1} min={1} max={100}
              />
              <ConfigField
                label="Take Profit"
                description="Exit early when unrealized profit per contract reaches this many cents. Locks in gains before expiry. 0 = hold to settlement."
                suffix="cents"
                value={config.take_profit_cents}
                onChange={(v) => setConfig({ ...config, take_profit_cents: v })}
                step={1} min={0} max={50}
              />
              <ConfigField
                label="Stop Loss"
                description="Exit early when unrealized loss per contract reaches this many cents. Limits downside on bad trades. 0 = hold to settlement."
                suffix="cents"
                value={config.stop_loss_cents}
                onChange={(v) => setConfig({ ...config, stop_loss_cents: v })}
                step={1} min={0} max={50}
              />
              <ConfigField
                label="Daily Loss Limit"
                description="Pauses the bot for the rest of the day if realized losses exceed this amount. Prevents tilt/drawdown spirals. 0 = disabled."
                prefix="$"
                value={config.daily_loss_limit_cents / 100}
                onChange={(v) => setConfig({ ...config, daily_loss_limit_cents: Math.round(v * 100) })}
                step={1} min={0} max={1000}
              />
              <ConfigField
                label="Max Signals/Hour"
                description="Rate limit on new signals per hour. Prevents the bot from over-trading in volatile conditions. 0 = unlimited."
                value={config.max_signals_per_hour}
                onChange={(v) => setConfig({ ...config, max_signals_per_hour: v })}
                step={1} min={0} max={50}
              />
              <div className="col-span-2">
                <button
                  type="submit"
                  disabled={savingConfig}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
                >
                  {savingConfig ? "Saving..." : "Save"}
                </button>
              </div>
            </form>

            <details className="mt-2">
              <summary className="text-sm text-slate-400 cursor-pointer hover:text-slate-300 select-none">
                Position Sizing by Tier
              </summary>
              <p className="text-xs text-slate-500 mt-2 mb-3">
                Higher-edge signals get larger position limits. "Speculative" uses the defaults above.
              </p>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Elite Reserve %</label>
                  <input
                    type="number"
                    value={config.tier_budget_pct_elite}
                    onChange={(e) => setConfig({ ...config, tier_budget_pct_elite: Number(e.target.value) })}
                    step="1"
                    min="0"
                    max="50"
                    className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                  <p className="text-xs text-slate-600 mt-0.5">% of daily budget reserved for elite signals</p>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">High Reserve %</label>
                  <input
                    type="number"
                    value={config.tier_budget_pct_high}
                    onChange={(e) => setConfig({ ...config, tier_budget_pct_high: Number(e.target.value) })}
                    step="1"
                    min="0"
                    max="50"
                    className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                  <p className="text-xs text-slate-600 mt-0.5">% of daily budget reserved for high signals</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div />
                <div className="text-slate-500 text-center">Max Position</div>
                <div className="text-slate-500 text-center">Max Contracts</div>

                <div className="flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-blue-400" />
                  <span className="text-slate-300">Moderate (20-49c)</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500">$</span>
                  <input type="number" value={config.max_position_cents_moderate / 100}
                    onChange={(e) => setConfig({ ...config, max_position_cents_moderate: Math.round(Number(e.target.value) * 100) })}
                    step="1" min="1" max="100"
                    className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                </div>
                <input type="number" value={config.max_contracts_moderate}
                  onChange={(e) => setConfig({ ...config, max_contracts_moderate: Number(e.target.value) })}
                  step="1" min="1" max="100"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />

                <div className="flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-amber-400" />
                  <span className="text-slate-300">High (50-79c)</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500">$</span>
                  <input type="number" value={config.max_position_cents_high / 100}
                    onChange={(e) => setConfig({ ...config, max_position_cents_high: Math.round(Number(e.target.value) * 100) })}
                    step="1" min="1" max="100"
                    className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                </div>
                <input type="number" value={config.max_contracts_high}
                  onChange={(e) => setConfig({ ...config, max_contracts_high: Number(e.target.value) })}
                  step="1" min="1" max="100"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />

                <div className="flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
                  <span className="text-slate-300">Elite (80c+)</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500">$</span>
                  <input type="number" value={config.max_position_cents_elite / 100}
                    onChange={(e) => setConfig({ ...config, max_position_cents_elite: Math.round(Number(e.target.value) * 100) })}
                    step="1" min="1" max="500"
                    className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                </div>
                <input type="number" value={config.max_contracts_elite}
                  onChange={(e) => setConfig({ ...config, max_contracts_elite: Number(e.target.value) })}
                  step="1" min="1" max="200"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
            </details>
          </>
        )}
      </section>

      {/* Kalshi Keys */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Kalshi API Keys</h3>
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full ${keysStatus?.has_keys ? "bg-emerald-500" : "bg-red-500"}`}
          />
          <span className="text-sm text-slate-300">
            {keysStatus?.has_keys
              ? `Keys configured (${keysStatus.key_id_preview})`
              : "No keys configured"}
          </span>
          {keysStatus?.has_keys && (
            <button
              onClick={handleDeleteKeys}
              className="ml-auto text-sm text-red-400 hover:text-red-300"
            >
              Remove keys
            </button>
          )}
        </div>

        {keysMessage && (
          <p
            className={`text-sm rounded-lg p-3 ${
              keysMessage.type === "success"
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-red-400/10 text-red-400"
            }`}
          >
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
            {savingKeys ? "Saving..." : "Save Keys"}
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Generate API keys at kalshi.com under Account &gt; API Keys. Required for live trading mode.
        </p>
      </section>

      {/* Spot Trading Config */}
      <section className="bg-slate-900 border border-blue-500/20 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Spot BTC Trading</h3>
          {config && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Mode:</label>
                <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                  config.spot_mode === "live"
                    ? "bg-red-500/20 text-red-400"
                    : "bg-blue-500/20 text-blue-400"
                }`}>
                  {config.spot_mode.toUpperCase()}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-slate-400">Enabled:</label>
                <button
                  onClick={() => handleUpdateConfig({ spot_enabled: !config.spot_enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    config.spot_enabled ? "bg-blue-600" : "bg-slate-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                      config.spot_enabled ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>
          )}
        </div>
        <p className="text-xs text-slate-500">
          Buy the dip strategy: automatically buys BTC when price drops from its rolling 1-hour high, and sells on recovery or stop loss.
        </p>
        {config && (
          <form onSubmit={handleSpotConfigSubmit} className="grid grid-cols-2 gap-4">
            <ConfigField
              label="Dip Threshold"
              description="Buy when BTC drops this % from its rolling 1-hour high. Lower values trigger more often. 3% is a moderate dip."
              suffix="%"
              value={config.spot_dip_pct}
              onChange={(v) => setConfig({ ...config, spot_dip_pct: v })}
              step={0.5} min={0.1} max={20}
            />
            <ConfigField
              label="Take Profit"
              description="Sell when price rises this % above your average entry. Locks in gains. 2% is conservative."
              suffix="%"
              value={config.spot_take_profit_pct}
              onChange={(v) => setConfig({ ...config, spot_take_profit_pct: v })}
              step={0.5} min={0.1} max={50}
            />
            <ConfigField
              label="Stop Loss"
              description="Sell when price drops this % below your average entry. Limits downside. 5% is standard."
              suffix="%"
              value={config.spot_stop_loss_pct}
              onChange={(v) => setConfig({ ...config, spot_stop_loss_pct: v })}
              step={0.5} min={0.5} max={50}
            />
            <ConfigField
              label="Buy Amount"
              description="USD to spend on each dip buy. Smaller amounts = more averaging-in opportunities."
              prefix="$"
              value={config.spot_buy_amount_usd}
              onChange={(v) => setConfig({ ...config, spot_buy_amount_usd: v })}
              step={10} min={10} max={10000}
            />
            <ConfigField
              label="Max Position"
              description="Maximum total USD invested in BTC at any time. Prevents over-concentration in a single asset."
              prefix="$"
              value={config.spot_max_position_usd}
              onChange={(v) => setConfig({ ...config, spot_max_position_usd: v })}
              step={50} min={10} max={100000}
            />
            <ConfigField
              label="Cooldown"
              description="Minimum minutes between successive dip buys. Prevents buying repeatedly in a freefall."
              suffix="min"
              value={config.spot_cooldown_minutes}
              onChange={(v) => setConfig({ ...config, spot_cooldown_minutes: v })}
              step={5} min={1} max={1440}
            />
            <div className="col-span-2">
              <button
                type="submit"
                disabled={savingConfig}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
              >
                {savingConfig ? "Saving..." : "Save Spot Settings"}
              </button>
            </div>
          </form>
        )}
      </section>

      {/* Coinbase Keys */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Coinbase API Keys</h3>
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full ${cbKeysStatus?.has_keys ? "bg-emerald-500" : "bg-red-500"}`}
          />
          <span className="text-sm text-slate-300">
            {cbKeysStatus?.has_keys
              ? `Keys configured (${cbKeysStatus.key_preview})`
              : "No keys configured"}
          </span>
          {cbKeysStatus?.has_keys && (
            <button
              onClick={handleDeleteCbKeys}
              className="ml-auto text-sm text-red-400 hover:text-red-300"
            >
              Remove keys
            </button>
          )}
        </div>

        {cbKeysMessage && (
          <p
            className={`text-sm rounded-lg p-3 ${
              cbKeysMessage.type === "success"
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-red-400/10 text-red-400"
            }`}
          >
            {cbKeysMessage.text}
          </p>
        )}

        <form onSubmit={handleSaveCbKeys} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">API Key ID</label>
            <input
              type="text"
              value={cbKey}
              onChange={(e) => setCbKey(e.target.value)}
              placeholder="Your Coinbase API Key ID"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">API Secret</label>
            <textarea
              value={cbSecret}
              onChange={(e) => setCbSecret(e.target.value)}
              placeholder={"-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----"}
              rows={6}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono resize-y"
            />
          </div>
          <button
            type="submit"
            disabled={savingCbKeys || !cbKey || !cbSecret}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
          >
            {savingCbKeys ? "Saving..." : "Save Keys"}
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Create API keys at coinbase.com under Settings &gt; API. Required for live spot trading.
        </p>
      </section>

      {/* Account */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-white mb-2">Account</h3>
        <p className="text-sm text-slate-400">
          Email: <span className="text-white">{user?.email}</span>
        </p>
      </section>
    </div>
  );
}
