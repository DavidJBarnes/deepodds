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
  // Filter to near-expiry only (< 2 hours) for settlement arb relevance
  const nearExpiry = opportunities
    .filter((o) => {
      if (!o.close_time) return false;
      const diff = new Date(o.close_time).getTime() - Date.now();
      return diff > 0 && diff < 2 * 60 * 60 * 1000;
    })
    .sort((a, b) => {
      const aDiff = new Date(a.close_time!).getTime();
      const bDiff = new Date(b.close_time!).getTime();
      return aDiff - bDiff;
    });

  if (nearExpiry.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">
          No near-expiry contracts found. Contracts expiring within 2 hours will appear here for settlement arb evaluation.
        </p>
      </div>
    );
  }

  return (
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
              <th className="text-right px-4 py-2">Expires</th>
            </tr>
          </thead>
          <tbody>
            {nearExpiry.map((o) => {
              const inside = spotInRange(o);
              const urgent = isUrgent(o.close_time);
              // Predict winning side based on spot position
              const predictSide = inside === true ? "yes" : inside === false ? "no" : null;

              return (
                <tr key={o.ticker} className={`border-b border-slate-800/50 hover:bg-slate-800/30 ${urgent ? "bg-amber-500/5" : ""}`}>
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
                  <td className="px-4 py-2 text-right text-slate-300 font-mono">
                    {o.spot_price != null ? `$${o.spot_price.toLocaleString()}` : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400 text-xs">
                    {strikeLabel(o)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    <span className={predictSide === "yes" ? "text-emerald-400 font-medium" : "text-slate-300"}>
                      {o.yes_price != null ? `${Number(o.yes_price).toFixed(0)}c` : "—"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    <span className={predictSide === "no" ? "text-emerald-400 font-medium" : "text-slate-300"}>
                      {o.no_price != null ? `${Number(o.no_price).toFixed(0)}c` : "—"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    {predictSide ? (
                      <span className={predictSide === "yes" ? "text-emerald-400" : "text-red-400"}>
                        {predictSide.toUpperCase()}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {o.close_time ? (
                      <Countdown closeTime={o.close_time} />
                    ) : (
                      <span className="text-slate-600">—</span>
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
