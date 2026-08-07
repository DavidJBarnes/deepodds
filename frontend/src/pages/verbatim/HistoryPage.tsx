import { useMemo, useState } from 'react';
import { api } from '@/api/verbatim';
import { useFetch } from '@/hooks/verbatim/useFetch';
import { DetectionsTable } from '@/components/verbatim/DetectionsTable';
import { LatencyChart } from '@/components/verbatim/charts/LatencyChart';
import { EdgeChart } from '@/components/verbatim/charts/EdgeChart';
import { Card, ErrorBox, Spinner } from '@/components/verbatim/ui';
import type { DetectionOut, DetectionState, MarketOut } from '@/types/verbatim';

type Filter = 'all' | DetectionState;

export function HistoryPage() {
  const [filter, setFilter] = useState<Filter>('all');

  const marketsFetch = useFetch<MarketOut[]>(() => api.markets(), []);
  const detFetch = useFetch<DetectionOut[]>(
    () => api.detections({ limit: 500 }),
    [],
  );

  const tickerByMarket = useMemo(() => {
    const rec: Record<number, string> = {};
    for (const m of marketsFetch.data ?? []) rec[m.id] = m.ticker;
    return rec;
  }, [marketsFetch.data]);

  const all = detFetch.data ?? [];
  const filtered = useMemo(
    () => (filter === 'all' ? all : all.filter((d) => d.state === filter)),
    [all, filter],
  );

  const rejected = all.filter((d) => d.state === 'rejected').length;
  const fpRate = all.length ? rejected / all.length : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-white">History</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">state</span>
          {(['all', 'confirmed', 'rejected'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={
                filter === f
                  ? 'rounded bg-slate-700 px-2 py-1 text-slate-100'
                  : 'rounded px-2 py-1 text-slate-400 hover:bg-slate-800'
              }
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {detFetch.loading && <Spinner label="Loading detections…" />}
      {detFetch.error && <ErrorBox message={detFetch.error} />}

      {!detFetch.loading && !detFetch.error && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Card>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Total detections
              </div>
              <div className="text-2xl font-bold text-slate-100">
                {all.length}
              </div>
            </Card>
            <Card>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Confirmed
              </div>
              <div className="text-2xl font-bold text-green-400">
                {all.length - rejected}
              </div>
            </Card>
            <Card>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                False-positive rate
              </div>
              <div className="text-2xl font-bold text-red-400">
                {(fpRate * 100).toFixed(1)}%
              </div>
              <div className="text-xs text-slate-500">
                {rejected} rejected / {all.length}
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">
                Per-hop latency (avg)
              </h3>
              <LatencyChart detections={all} />
            </Card>
            <Card>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">
                Edge seconds over time
              </h3>
              <EdgeChart detections={all} />
            </Card>
          </div>

          <DetectionsTable
            detections={filtered}
            tickerByMarket={tickerByMarket}
          />
        </>
      )}
    </div>
  );
}

// Default export so React.lazy can code-split this route.
export default HistoryPage;
