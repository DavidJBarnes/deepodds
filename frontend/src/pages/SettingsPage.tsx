import { type FormEvent, useEffect, useState } from "react";
import { useAuthStore } from "@/stores/authStore";
import ConfirmModal from "@/components/ConfirmModal";
import * as settingsApi from "@/api/settings";
import * as botApi from "@/api/bot";

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const [keysStatus, setKeysStatus] = useState<settingsApi.KalshiKeysStatus | null>(null);
  const [keyId, setKeyId] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysMessage, setKeysMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [config, setConfig] = useState<botApi.BotConfig | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [modeModal, setModeModal] = useState<"paper" | "live" | null>(null);
  const [kalshiBalance, setKalshiBalance] = useState<settingsApi.KalshiBalance | null>(null);

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKeysStatus);
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
      min_liquidity: config.min_liquidity,
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
              <div>
                <label className="block text-sm text-slate-400 mb-1">Max Exposure</label>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500 text-sm">$</span>
                  <input
                    type="number"
                    value={config.max_exposure_cents / 100}
                    onChange={(e) => setConfig({ ...config, max_exposure_cents: Math.round(Number(e.target.value) * 100) })}
                    step="1"
                    min="1"
                    max="1000"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Max $ in open positions at once. Freed when positions settle.
                  {kalshiBalance && kalshiBalance.cash_cents > 0 && (
                    <span className="ml-1 text-slate-400">
                      Kalshi cash: <span className="text-white">${(kalshiBalance.cash_cents / 100).toFixed(2)}</span>
                    </span>
                  )}
                </p>
                {kalshiBalance && kalshiBalance.cash_cents > 0 && config.max_exposure_cents > kalshiBalance.cash_cents && (
                  <p className="text-xs text-amber-400 mt-1">
                    Exposure exceeds your Kalshi cash balance. Live orders may fail if funds are insufficient.
                  </p>
                )}
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Daily Budget</label>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500 text-sm">$</span>
                  <input
                    type="number"
                    value={config.daily_budget_cents / 100}
                    onChange={(e) => setConfig({ ...config, daily_budget_cents: Math.round(Number(e.target.value) * 100) })}
                    step="1"
                    min="0"
                    max="1000"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1">0 = unlimited. Hard cap on total spend per day.</p>
                {kalshiBalance && kalshiBalance.cash_cents > 0 && config.daily_budget_cents > 0 && config.daily_budget_cents > kalshiBalance.cash_cents && (
                  <p className="text-xs text-amber-400 mt-1">
                    Daily budget exceeds your Kalshi cash balance.
                  </p>
                )}
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Min Edge (cents)</label>
                <input
                  type="number"
                  value={config.min_edge_cents}
                  onChange={(e) => setConfig({ ...config, min_edge_cents: Number(e.target.value) })}
                  step="0.5"
                  min="1"
                  max="50"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Min Liquidity</label>
                <input
                  type="number"
                  value={config.min_liquidity}
                  onChange={(e) => setConfig({ ...config, min_liquidity: Number(e.target.value) })}
                  step="1"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Max Position</label>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500 text-sm">$</span>
                  <input
                    type="number"
                    value={config.max_position_cents / 100}
                    onChange={(e) => setConfig({ ...config, max_position_cents: Math.round(Number(e.target.value) * 100) })}
                    step="1"
                    min="1"
                    max="100"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Max Contracts/Signal</label>
                <input
                  type="number"
                  value={config.max_contracts_per_signal}
                  onChange={(e) => setConfig({ ...config, max_contracts_per_signal: Number(e.target.value) })}
                  step="1"
                  min="1"
                  max="100"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Take Profit (cents)</label>
                <input
                  type="number"
                  value={config.take_profit_cents}
                  onChange={(e) => setConfig({ ...config, take_profit_cents: Number(e.target.value) })}
                  step="1"
                  min="0"
                  max="50"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500 mt-1">0 = disabled</p>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Stop Loss (cents)</label>
                <input
                  type="number"
                  value={config.stop_loss_cents}
                  onChange={(e) => setConfig({ ...config, stop_loss_cents: Number(e.target.value) })}
                  step="1"
                  min="0"
                  max="50"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500 mt-1">0 = disabled</p>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Daily Loss Limit</label>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500 text-sm">$</span>
                  <input
                    type="number"
                    value={config.daily_loss_limit_cents / 100}
                    onChange={(e) => setConfig({ ...config, daily_loss_limit_cents: Math.round(Number(e.target.value) * 100) })}
                    step="1"
                    min="0"
                    max="1000"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1">0 = disabled. Pauses bot if daily losses exceed this.</p>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Max Signals/Hour</label>
                <input
                  type="number"
                  value={config.max_signals_per_hour}
                  onChange={(e) => setConfig({ ...config, max_signals_per_hour: Number(e.target.value) })}
                  step="1"
                  min="0"
                  max="50"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500 mt-1">0 = unlimited</p>
              </div>
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
