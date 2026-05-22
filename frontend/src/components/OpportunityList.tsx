import type { MarketSnapshot } from "@/api/bot";

export default function MarketView({ markets }: { markets: MarketSnapshot[] }) {
  if (markets.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">No market data available yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">
          Live Markets{" "}
          <span className="text-slate-500 font-normal">({markets.length} pairs)</span>
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
              <th className="text-left px-4 py-2">Pair</th>
              <th className="text-right px-4 py-2">Price</th>
              <th className="text-right px-4 py-2">VWAP</th>
              <th className="text-right px-4 py-2">Std Dev</th>
              <th className="text-right px-4 py-2">Z-Score</th>
              <th className="text-center px-4 py-2">Signal?</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((m) => {
              const zColor =
                m.z_score <= -2 ? "text-red-400 font-bold" :
                m.z_score <= -1 ? "text-amber-400" :
                m.z_score >= 1 ? "text-emerald-400" :
                "text-slate-400";

              return (
                <tr key={m.pair} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="px-4 py-2 font-mono text-xs text-white">{m.pair}</td>
                  <td className="px-4 py-2 text-right text-slate-300 tabular-nums">
                    ${m.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400 tabular-nums">
                    ${m.vwap.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400 tabular-nums">
                    ${m.std_dev.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td className={`px-4 py-2 text-right tabular-nums ${zColor}`}>
                    {m.z_score.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {m.would_signal ? (
                      <span className="text-emerald-400 text-lg leading-none" title="Entry signal">&#9679;</span>
                    ) : (
                      <span className="text-slate-700">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
