import { FormEvent, useEffect, useState } from "react";
import { useAuthStore } from "@/stores/authStore";
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

  useEffect(() => {
    settingsApi.getKalshiKeysStatus().then(setKeysStatus);
    botApi.getBotConfig().then(setConfig);
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
      daily_budget_cents: config.daily_budget_cents,
      min_edge_cents: config.min_edge_cents,
      min_liquidity: config.min_liquidity,
      max_position_cents: config.max_position_cents,
      max_contracts_per_signal: config.max_contracts_per_signal,
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
                  onClick={() => handleUpdateConfig({ mode: config.mode === "paper" ? "live" : "paper" })}
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
                <label className="block text-sm text-slate-400 mb-1">Daily Budget</label>
                <div className="flex items-center gap-1">
                  <span className="text-slate-500 text-sm">$</span>
                  <input
                    type="number"
                    value={config.daily_budget_cents / 100}
                    onChange={(e) => setConfig({ ...config, daily_budget_cents: Math.round(Number(e.target.value) * 100) })}
                    step="1"
                    min="1"
                    max="1000"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
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
              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={savingConfig}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg transition-colors"
                >
                  {savingConfig ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
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
