import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { DetectionOut } from '@/types/verbatim';
import { clsx, formatDateTime, formatSeconds } from '@/utils/verbatimFormat';
import { Badge } from './ui';

type SortKey = 'time' | 'edge';

export function DetectionsTable({
  detections,
  tickerByMarket,
}: {
  detections: DetectionOut[];
  tickerByMarket: Record<number, string>;
}) {
  const [sortKey, setSortKey] = useState<SortKey>('time');
  const [desc, setDesc] = useState(true);

  const sorted = useMemo(() => {
    const arr = [...detections];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'time') {
        cmp = Date.parse(a.utterance_ts) - Date.parse(b.utterance_ts);
      } else {
        cmp = (a.edge_seconds ?? -Infinity) - (b.edge_seconds ?? -Infinity);
      }
      return desc ? -cmp : cmp;
    });
    return arr;
  }, [detections, sortKey, desc]);

  const toggle = (key: SortKey) => {
    if (key === sortKey) setDesc((d) => !d);
    else {
      setSortKey(key);
      setDesc(true);
    }
  };

  const arrow = (key: SortKey) =>
    key === sortKey ? (desc ? ' ▼' : ' ▲') : '';

  if (detections.length === 0) {
    return (
      <div className="rounded border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">
        No detections.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">ID</th>
            <th
              className="cursor-pointer select-none px-3 py-2"
              onClick={() => toggle('time')}
            >
              Time{arrow('time')}
            </th>
            <th className="px-3 py-2">Market</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Span</th>
            <th className="px-3 py-2">Scores</th>
            <th
              className="cursor-pointer select-none px-3 py-2"
              onClick={() => toggle('edge')}
            >
              Edge{arrow('edge')}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {sorted.map((d) => (
            <tr key={d.id} className="hover:bg-slate-800/40">
              <td className="px-3 py-2">
                <Link
                  to={`/detections/${d.id}`}
                  className="font-mono text-emerald-400 hover:underline"
                >
                  #{d.id}
                </Link>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-400">
                {formatDateTime(d.utterance_ts)}
              </td>
              <td className="px-3 py-2 font-mono text-xs text-slate-300">
                {tickerByMarket[d.market_id] ?? `#${d.market_id}`}
              </td>
              <td className="px-3 py-2">
                <Badge color={d.state === 'confirmed' ? 'green' : 'red'}>
                  {d.state}
                </Badge>
              </td>
              <td className="max-w-[160px] truncate px-3 py-2 text-slate-300">
                {d.matched_span || '—'}
              </td>
              <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-400">
                {d.stage1_score.toFixed(2)}
                {d.stage2_score != null && ` / ${d.stage2_score.toFixed(2)}`}
              </td>
              <td
                className={clsx(
                  'whitespace-nowrap px-3 py-2 font-mono',
                  d.edge_seconds == null
                    ? 'text-slate-500'
                    : d.edge_seconds >= 0
                      ? 'text-green-400'
                      : 'text-red-400',
                )}
              >
                {formatSeconds(d.edge_seconds)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
