import { Link } from 'react-router-dom';
import type { MarketOut, MarketQuoteEvent, PatternOut } from '@/types/verbatim';
import { centsToPrice, clsx, countdown } from '@/utils/verbatimFormat';
import { Badge } from './ui';

export interface WatchItem {
  market: MarketOut;
  patterns: PatternOut[];
}

interface Props {
  items: WatchItem[];
  quotes: Record<string, MarketQuoteEvent>;
  /** pattern ids currently pulsing from a near-miss */
  pulsing: Set<number>;
  nowMs: number;
}

export function WatchlistSidebar({ items, quotes, pulsing, nowMs }: Props) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
        Armed watchlist
      </h2>
      {items.length === 0 && (
        <div className="rounded border border-dashed border-slate-700 p-4 text-center text-xs text-slate-500">
          No armed markets. Arm one from the{' '}
          <Link to="/watchlist" className="text-emerald-400 underline">
            Watchlist
          </Link>
          .
        </div>
      )}
      {items.map(({ market, patterns }) => {
        const quote = quotes[market.ticker];
        const activePatterns = patterns.filter((p) => p.active);
        return (
          <div
            key={market.id}
            className="rounded-lg border border-slate-800 bg-slate-900/60 p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-100">
                  {market.title}
                </div>
                <div className="font-mono text-xs text-slate-500">
                  {market.ticker}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-xs text-slate-500">deadline</div>
                <div className="font-mono text-xs text-amber-300">
                  {countdown(market.deadline_utc, nowMs)}
                </div>
              </div>
            </div>

            <div className="mt-2 flex items-center gap-3 text-xs">
              <span className="text-slate-500">bid/ask</span>
              <span className="font-mono text-green-400">
                {centsToPrice(quote?.yes_bid ?? null)}
              </span>
              <span className="text-slate-600">/</span>
              <span className="font-mono text-red-400">
                {centsToPrice(quote?.yes_ask ?? null)}
              </span>
              {market.speaker && (
                <span className="ml-auto text-slate-500">{market.speaker}</span>
              )}
            </div>

            <div className="mt-2 flex flex-wrap gap-1">
              {activePatterns.length === 0 && (
                <span className="text-xs text-slate-600">no active patterns</span>
              )}
              {activePatterns.map((p) => (
                <span
                  key={p.id}
                  className={clsx(
                    'rounded px-1.5 py-0.5 text-xs',
                    pulsing.has(p.id)
                      ? 'animate-pulseHi bg-yellow-400/40 text-yellow-100'
                      : 'bg-slate-800 text-slate-300',
                  )}
                >
                  {p.phrase}
                </span>
              ))}
            </div>
            {market.parse_status === 'needs_review' && (
              <div className="mt-2">
                <Badge color="yellow">needs review</Badge>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
