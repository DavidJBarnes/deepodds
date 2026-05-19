import type { Opportunity } from "@/api/bot";

const SERIES_SLUGS: Record<string, string> = {
  KXBTC: "bitcoin-range",
  KXBTCD: "bitcoin-price",
  KXETH: "ethereum-range",
  KXETHD: "ethereum-price",
};

function kalshiUrl(ticker: string) {
  const series = ticker.split("-")[0];
  const eventTicker = ticker.substring(0, ticker.lastIndexOf("-")).toLowerCase();
  const slug = SERIES_SLUGS[series];
  if (slug) return `https://kalshi.com/markets/${series.toLowerCase()}/${slug}/${eventTicker}`;
  return `https://kalshi.com/markets/${eventTicker}`;
}

const QUALITY_COLORS: Record<string, string> = {
  high: "text-emerald-400",
  medium: "text-amber-400",
  low: "text-slate-500",
};

export default function OpportunityList({ opportunities }: { opportunities: Opportunity[] }) {
  if (opportunities.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">No active opportunities. Scanner runs every 60 seconds.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">Active Opportunities</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
              <th className="text-left px-4 py-2">Ticker</th>
              <th className="text-left px-4 py-2">Asset</th>
              <th className="text-right px-4 py-2">Spot</th>
              <th className="text-right px-4 py-2">Strike</th>
              <th className="text-right px-4 py-2">Market</th>
              <th className="text-right px-4 py-2">Fair</th>
              <th className="text-right px-4 py-2">Edge</th>
              <th className="text-right px-4 py-2">IV</th>
              <th className="text-right px-4 py-2">Liquidity</th>
            </tr>
          </thead>
          <tbody>
            {opportunities.map((o) => (
              <tr key={o.ticker} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-2 font-mono text-xs">
                  <a
                    href={kalshiUrl(o.ticker)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-white hover:text-emerald-400 transition-colors"
                  >
                    {o.ticker}
                  </a>
                </td>
                <td className="px-4 py-2 text-slate-300">{o.asset}</td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.spot_price != null ? `$${o.spot_price.toLocaleString()}` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.strike_price != null ? `$${o.strike_price.toLocaleString()}` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.yes_price != null ? `${Number(o.yes_price.toFixed(1))}c` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.model_fair_cents != null ? `${o.model_fair_cents.toFixed(1)}c` : "—"}
                </td>
                <td className={`px-4 py-2 text-right font-medium ${QUALITY_COLORS[o.quality] || "text-slate-500"}`}>
                  {o.model_edge_cents != null ? `${o.model_edge_cents.toFixed(1)}c` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.implied_vol != null ? `${(o.implied_vol * 100).toFixed(0)}%` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {o.liquidity.toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
