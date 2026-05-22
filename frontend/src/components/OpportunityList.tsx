import type { Opportunity } from "@/api/bot";
import Countdown from "@/components/Countdown";

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

function isUrgent(closeTime: string | null) {
  if (!closeTime) return false;
  const diff = new Date(closeTime).getTime() - Date.now();
  return diff > 0 && diff < 10 * 60 * 1000;
}

function strikeLabel(o: Opportunity) {
  if (!o.strike_price) return "—";
  if (o.strike_type === "between" && o.cap_strike) {
    return `$${o.strike_price.toLocaleString()}–$${o.cap_strike.toLocaleString()}`;
  }
  const dir = o.strike_type === "above" ? ">" : o.strike_type === "below" ? "<" : "";
  return `${dir}$${o.strike_price.toLocaleString()}`;
}

function spotInRange(o: Opportunity) {
  if (!o.spot_price || !o.strike_price) return null;
  if (o.strike_type === "between" && o.cap_strike) {
    return o.strike_price < o.spot_price && o.spot_price < o.cap_strike;
  }
  if (o.strike_type === "above") return o.spot_price > o.strike_price;
  if (o.strike_type === "below") return o.spot_price < o.strike_price;
  return null;
}

export default function OpportunityList({ opportunities }: { opportunities: Opportunity[] }) {
  const polymarketOpps = opportunities
    .filter((o) => o.source === "polymarket")
    .sort((a, b) => (b.model_edge_cents || 0) - (a.model_edge_cents || 0));

  const nearExpiry = opportunities
    .filter((o) => {
      if (o.source === "polymarket") return false;
      if (!o.close_time) return false;
      const diff = new Date(o.close_time).getTime() - Date.now();
      return diff > 0 && diff < 2 * 60 * 60 * 1000;
    })
    .sort((a, b) => {
      const aDiff = new Date(a.close_time!).getTime();
      const bDiff = new Date(b.close_time!).getTime();
      return aDiff - bDiff;
    });

  const showKalshi = nearExpiry.length > 0;
  const showPolymarket = polymarketOpps.length > 0;

  if (!showKalshi && !showPolymarket) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">No opportunities found.</p>
      </div>
    );
  }

  return (
    <>
      {showKalshi && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800">
            <h3 className="text-sm font-semibold text-white">
              Near-Expiry Contracts{" "}
              <span className="text-slate-500 font-normal">({nearExpiry.length} expiring within 2h)</span>
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
                  <th className="text-left px-4 py-2">Contract</th>
                  <th className="text-left px-4 py-2">Asset</th>
                  <th className="text-right px-4 py-2">Spot</th>
                  <th className="text-right px-4 py-2">Range</th>
                  <th className="text-right px-4 py-2">YES</th>
                  <th className="text-right px-4 py-2">NO</th>
                  <th className="text-right px-4 py-2">Predict</th>
                  <th className="text-right px-4 py-2">Sigma</th>
                  <th className="text-right px-4 py-2">Discount</th>
                  <th className="text-right px-4 py-2">Expires</th>
                  <th className="text-center px-2 py-2">Signal?</th>
                </tr>
              </thead>
              <tbody>
                {nearExpiry.map((o) => {
                  const inside = spotInRange(o);
                  const urgent = isUrgent(o.close_time);
                  const predictSide = inside === true ? "yes" : inside === false ? "no" : null;
                  return (
                    <tr key={o.ticker} className={`border-b border-slate-800/50 hover:bg-slate-800/30 ${urgent ? "bg-amber-500/5" : ""}`}>
                      <td className="px-4 py-2 font-mono text-xs">
                        <a href={kalshiUrl(o.ticker)} target="_blank" rel="noopener noreferrer" className="text-white hover:text-emerald-400 transition-colors">
                          {o.ticker}
                        </a>
                      </td>
                      <td className="px-4 py-2 text-slate-400 uppercase text-xs">{o.asset}</td>
                      <td className="px-4 py-2 text-right text-slate-300 tabular-nums">{o.spot_price ? `$${o.spot_price.toLocaleString()}` : "—"}</td>
                      <td className="px-4 py-2 text-right text-slate-300 tabular-nums">{strikeLabel(o)}</td>
                      <td className="px-4 py-2 text-right tabular-nums"><span className={inside === true ? "text-emerald-400" : "text-slate-400"}>{o.yes_price != null ? `${o.yes_price.toFixed(1)}c` : "—"}</span></td>
                      <td className="px-4 py-2 text-right tabular-nums"><span className={inside === false ? "text-red-400" : "text-slate-400"}>{o.no_price != null ? `${o.no_price.toFixed(1)}c` : "—"}</span></td>
                      <td className="px-4 py-2 text-right">{predictSide ? <span className={predictSide === "yes" ? "text-emerald-400" : "text-red-400"}>{predictSide.toUpperCase()}</span> : <span className="text-slate-600">—</span>}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-slate-300">{o.sigma_distance != null ? `${o.sigma_distance.toFixed(1)}σ` : "—"}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{o.discount_cents != null && o.discount_cents > 0 ? <span className="text-emerald-400">{o.discount_cents.toFixed(1)}c</span> : <span className="text-slate-600">—</span>}</td>
                      <td className="px-4 py-2 text-right text-slate-400">{o.close_time ? <Countdown closeTime={o.close_time} /> : "—"}</td>
                      <td className="px-2 py-2 text-center">{o.would_signal ? <span className="text-emerald-400 text-lg leading-none" title={`${o.sigma_distance?.toFixed(1)}σ, ${o.discount_cents?.toFixed(1)}c discount`}>◆</span> : <span className="text-slate-700">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showPolymarket && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-white">Polymarket Neg-Risk Arb</h3>
            <span className="px-1.5 py-0.5 text-[10px] rounded bg-purple-500/20 text-purple-400 font-medium">PM</span>
            <span className="text-slate-500 font-normal text-xs">({polymarketOpps.length} events)</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
                  <th className="text-left px-4 py-2">Event</th>
                  <th className="text-right px-4 py-2">Outcomes</th>
                  <th className="text-right px-4 py-2">Edge</th>
                  <th className="text-right px-4 py-2">Volume</th>
                  <th className="text-right px-4 py-2">Liquidity</th>
                  <th className="text-right px-4 py-2">Expires</th>
                </tr>
              </thead>
              <tbody>
                {polymarketOpps.map((o) => {
                  const edge = o.model_edge_cents || 0;
                  const dir = o.edge_direction;
                  return (
                    <tr key={o.ticker} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="px-4 py-2">
                        <span className="text-white text-xs">{o.title}</span>
                      </td>
                      <td className="px-4 py-2 text-right text-slate-400 tabular-nums">{o.subtitle || "—"}</td>
                      <td className="px-4 py-2 text-right"><span className={dir === "short" ? "text-red-400" : "text-emerald-400"}>{dir?.toUpperCase()} {edge.toFixed(1)}c</span></td>
                      <td className="px-4 py-2 text-right text-slate-400 tabular-nums">{typeof o.volume === 'number' ? o.volume.toLocaleString() : "—"}</td>
                      <td className="px-4 py-2 text-right text-slate-400 tabular-nums">{typeof o.liquidity === 'number' ? o.liquidity.toLocaleString() : "—"}</td>
                      <td className="px-4 py-2 text-right text-slate-500 text-xs">{o.close_time ? new Date(o.close_time).toLocaleDateString() : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
