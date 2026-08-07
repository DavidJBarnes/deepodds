import { useMemo } from 'react';
import type { DetectionOut } from '@/types/verbatim';
import { durationSeconds } from '@/utils/verbatimFormat';

interface Hop {
  label: string;
  from: keyof DetectionOut;
  to: keyof DetectionOut;
}

const HOPS: Hop[] = [
  { label: 'capture→stage1', from: 'chunk_capture_ts', to: 'stage1_done_ts' },
  { label: 'stage1→candidate', from: 'stage1_done_ts', to: 'candidate_ts' },
  { label: 'candidate→stage2', from: 'candidate_ts', to: 'stage2_done_ts' },
  { label: 'stage2→alert', from: 'stage2_done_ts', to: 'alert_sent_ts' },
];

/** Average per-hop latency (seconds) across a set of detections. */
export function LatencyChart({ detections }: { detections: DetectionOut[] }) {
  const bars = useMemo(() => {
    return HOPS.map((hop) => {
      const durs: number[] = [];
      for (const d of detections) {
        const a = d[hop.from] as string | null;
        const b = d[hop.to] as string | null;
        const s = durationSeconds(a, b);
        if (s != null && s >= 0) durs.push(s);
      }
      const avg = durs.length
        ? durs.reduce((x, y) => x + y, 0) / durs.length
        : 0;
      return { label: hop.label, avg, count: durs.length };
    });
  }, [detections]);

  const max = Math.max(0.001, ...bars.map((b) => b.avg));
  const w = 640;
  const h = 200;
  const pad = { top: 12, right: 16, bottom: 44, left: 44 };
  const innerW = w - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;
  const bw = innerW / bars.length;

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full min-w-[420px]"
        role="img"
        aria-label="Per-hop average latency"
      >
        {/* y axis ticks */}
        {[0, 0.5, 1].map((f) => {
          const y = pad.top + (1 - f) * innerH;
          return (
            <g key={f}>
              <line
                x1={pad.left}
                x2={w - pad.right}
                y1={y}
                y2={y}
                stroke="#1e293b"
              />
              <text x={pad.left - 6} y={y + 3} fill="#64748b" fontSize={10} textAnchor="end">
                {(max * f).toFixed(2)}s
              </text>
            </g>
          );
        })}
        {bars.map((b, i) => {
          const bh = (b.avg / max) * innerH;
          const x = pad.left + i * bw + bw * 0.15;
          const y = pad.top + innerH - bh;
          return (
            <g key={b.label}>
              <rect
                x={x}
                y={y}
                width={bw * 0.7}
                height={Math.max(0, bh)}
                fill="#6366f1"
                rx={2}
              />
              <text
                x={x + bw * 0.35}
                y={y - 4}
                fill="#c7d2fe"
                fontSize={10}
                textAnchor="middle"
              >
                {b.avg.toFixed(2)}s
              </text>
              <text
                x={x + bw * 0.35}
                y={h - pad.bottom + 14}
                fill="#94a3b8"
                fontSize={9}
                textAnchor="middle"
              >
                {b.label}
              </text>
              <text
                x={x + bw * 0.35}
                y={h - pad.bottom + 26}
                fill="#475569"
                fontSize={8}
                textAnchor="middle"
              >
                n={b.count}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
