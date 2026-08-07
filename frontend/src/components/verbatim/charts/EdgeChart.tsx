import { useMemo } from 'react';
import type { DetectionOut } from '@/types/verbatim';
import { parseTs } from '@/utils/verbatimFormat';

/** Scatter of edge_seconds over time. Green above zero, red below. */
export function EdgeChart({ detections }: { detections: DetectionOut[] }) {
  const points = useMemo(() => {
    return detections
      .map((d) => ({
        t: parseTs(d.utterance_ts),
        edge: d.edge_seconds,
        id: d.id,
      }))
      .filter(
        (p): p is { t: number; edge: number; id: number } =>
          p.t != null && p.edge != null,
      )
      .sort((a, b) => a.t - b.t);
  }, [detections]);

  const w = 640;
  const h = 220;
  const pad = { top: 16, right: 16, bottom: 28, left: 44 };
  const innerW = w - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;

  if (points.length === 0) {
    return (
      <div className="rounded border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">
        No edge data yet.
      </div>
    );
  }

  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const tSpan = Math.max(1, t1 - t0);
  const edges = points.map((p) => p.edge);
  const eMax = Math.max(1, ...edges);
  const eMin = Math.min(-1, ...edges);
  const eSpan = eMax - eMin;

  const x = (t: number) => pad.left + ((t - t0) / tSpan) * innerW;
  const y = (e: number) => pad.top + (1 - (e - eMin) / eSpan) * innerH;
  const zeroY = y(0);

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full min-w-[420px]"
        role="img"
        aria-label="Edge seconds over time"
      >
        <line
          x1={pad.left}
          x2={w - pad.right}
          y1={zeroY}
          y2={zeroY}
          stroke="#475569"
          strokeWidth={1}
        />
        <text x={pad.left - 6} y={y(eMax) + 3} fill="#64748b" fontSize={10} textAnchor="end">
          {eMax.toFixed(1)}s
        </text>
        <text x={pad.left - 6} y={zeroY + 3} fill="#64748b" fontSize={10} textAnchor="end">
          0
        </text>
        <text x={pad.left - 6} y={y(eMin) + 3} fill="#64748b" fontSize={10} textAnchor="end">
          {eMin.toFixed(1)}s
        </text>
        {points.map((p) => (
          <circle
            key={p.id}
            cx={x(p.t)}
            cy={y(p.edge)}
            r={3.5}
            fill={p.edge >= 0 ? '#22c55e' : '#ef4444'}
            opacity={0.85}
          />
        ))}
      </svg>
    </div>
  );
}
