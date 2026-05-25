import type { MarketSnapshot } from "@/api/bot";

function ZScoreBar({ z, entry, exit }: { z: number; entry: number; exit: number }) {
  // Bar range: slightly past the entry threshold on the left, mirrored on the right
  const rangeMin = Math.min(entry * 1.3, -3);
  const rangeMax = -rangeMin;
  const clamped = Math.max(rangeMin, Math.min(rangeMax, z));
  const pct = ((clamped - rangeMin) / (rangeMax - rangeMin)) * 100;
  const entryPct = ((entry - rangeMin) / (rangeMax - rangeMin)) * 100;
  const exitPct = ((exit - rangeMin) / (rangeMax - rangeMin)) * 100;
  const centerPct = ((0 - rangeMin) / (rangeMax - rangeMin)) * 100;

  // Dot color based on proximity to entry
  const dotColor =
    z <= entry ? "bg-emerald-400 shadow-emerald-400/50 shadow-lg" :
    z <= entry * 0.5 ? "bg-amber-400" :
    z >= exit && exit >= 0 ? "bg-rose-400" :
    "bg-slate-300";

  return (
    <div className="space-y-1">
      <div className="relative h-3 rounded-full bg-slate-800 overflow-visible">
        {/* Buy zone */}
        <div
          className="absolute inset-y-0 left-0 rounded-l-full bg-emerald-500/15"
          style={{ width: `${entryPct}%` }}
        />
        {/* Sell zone */}
        <div
          className="absolute inset-y-0 right-0 rounded-r-full bg-rose-500/10"
          style={{ width: `${100 - exitPct}%` }}
        />

        {/* Entry threshold line */}
        <div
          className="absolute top-0 bottom-0 w-px bg-emerald-500/60"
          style={{ left: `${entryPct}%` }}
        />
        {/* Center / VWAP line */}
        <div
          className="absolute top-0 bottom-0 w-px bg-slate-600"
          style={{ left: `${centerPct}%` }}
        />
        {/* Exit threshold line */}
        {exit !== 0 && (
          <div
            className="absolute top-0 bottom-0 w-px bg-rose-500/40"
            style={{ left: `${exitPct}%` }}
          />
        )}

        {/* Current z-score dot */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full ${dotColor} border-2 border-slate-900 transition-all duration-700 ease-out`}
          style={{ left: `${pct}%` }}
        />
      </div>

      {/* Labels */}
      <div className="relative h-3 text-[9px] text-slate-600 select-none">
        <span className="absolute -translate-x-1/2" style={{ left: `${entryPct}%` }}>
          BUY {entry}
        </span>
        <span className="absolute -translate-x-1/2" style={{ left: `${centerPct}%` }}>
          VWAP
        </span>
        {exit !== 0 && (
          <span className="absolute -translate-x-1/2" style={{ left: `${exitPct}%` }}>
            SELL {exit}
          </span>
        )}
      </div>
    </div>
  );
}

interface Props {
  markets: MarketSnapshot[];
  entryZ?: number;
  exitZ?: number;
}

export default function MarketView({ markets, entryZ = -2, exitZ = 0 }: Props) {
  if (markets.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">No market data available yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {markets.map((m) => {
        const zColor =
          m.z_score <= entryZ ? "text-emerald-400" :
          m.z_score <= entryZ * 0.5 ? "text-amber-400" :
          m.z_score >= exitZ && exitZ >= 0 && m.z_score > 0 ? "text-rose-400" :
          "text-slate-300";

        const priceDelta = m.price - m.vwap;
        const priceDeltaPct = m.vwap > 0 ? (priceDelta / m.vwap) * 100 : 0;

        return (
          <div key={m.pair} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            {/* Header row */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm font-semibold text-white">{m.pair}</span>
                {m.would_signal && (
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full">
                    Buy signal
                  </span>
                )}
              </div>
              <div className="text-right">
                <span className="text-sm text-white font-medium tabular-nums">
                  ${m.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
                <span className={`text-xs ml-2 tabular-nums ${priceDelta >= 0 ? "text-rose-400" : "text-emerald-400"}`}>
                  {priceDelta >= 0 ? "+" : ""}{priceDeltaPct.toFixed(2)}% vs VWAP
                </span>
              </div>
            </div>

            {/* Z-Score bar */}
            <ZScoreBar z={m.z_score} entry={entryZ} exit={exitZ} />

            {/* Stats row */}
            <div className="flex items-center justify-between text-xs">
              <div className="flex gap-4">
                <span className="text-slate-500">
                  VWAP <span className="text-slate-400 tabular-nums">${m.vwap.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </span>
                <span className="text-slate-500">
                  Std Dev <span className="text-slate-400 tabular-nums">${m.std_dev.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </span>
              </div>
              <div className="flex items-center gap-3">
                {m.min_z_24h < m.z_score && m.min_z_24h <= m.effective_entry_z * 0.7 && (
                  <span className="text-amber-400/80 tabular-nums">
                    24h low: {m.min_z_24h.toFixed(2)}z
                  </span>
                )}
                {m.z_distance > 0 && m.z_distance < 1.0 && !m.would_signal && (
                  <span className={`tabular-nums ${m.z_distance < 0.5 ? "text-amber-400" : "text-slate-500"}`}>
                    {m.z_distance.toFixed(1)} away
                  </span>
                )}
                <span className={`font-mono font-bold tabular-nums ${zColor}`}>
                  z = {m.z_score.toFixed(2)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export type { Props as MarketViewProps };
