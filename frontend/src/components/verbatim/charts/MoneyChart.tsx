import { useMemo } from 'react';
import type { DetectionOut } from '@/types/verbatim';
import { parseTs } from '@/utils/verbatimFormat';

interface Marker {
  label: string;
  ts: number;
  color: string;
}

/**
 * "The money chart": market mid over a window around the detection, with
 * vertical markers at utterance / alert_sent / market_reaction.
 *
 * The backend does not (per the contract) return a mid time-series, so we
 * synthesize a plausible reaction curve: flat before the market reaction,
 * then a ramp. This is purely illustrative of the timing relationship; the
 * load-bearing information is the marker placement and the edge headline.
 */
export function MoneyChart({ detection }: { detection: DetectionOut }) {
  const utt = parseTs(detection.utterance_ts);
  const alert = parseTs(detection.alert_sent_ts);
  const reaction = parseTs(detection.market_reaction_ts);

  const { width, height, markers, path, times } = useMemo(() => {
    const w = 640;
    const h = 220;
    const pad = { top: 16, right: 16, bottom: 28, left: 16 };

    const known = [utt, alert, reaction].filter((v): v is number => v != null);
    const anchor = known.length ? Math.min(...known) : Date.now();
    const anchorMax = known.length ? Math.max(...known) : anchor + 10000;
    // Pad the window by 20% on each side, minimum 10s span.
    const span = Math.max(anchorMax - anchor, 10000);
    const t0 = anchor - span * 0.25;
    const t1 = anchorMax + span * 0.25;

    const x = (t: number) =>
      pad.left + ((t - t0) / (t1 - t0)) * (w - pad.left - pad.right);
    const innerH = h - pad.top - pad.bottom;
    const y = (v: number) => pad.top + (1 - v) * innerH; // v in [0,1]

    // Synthetic mid curve: baseline until reaction, then sigmoid ramp.
    const reactAt = reaction ?? alert ?? utt ?? anchor;
    const baseline = 0.35;
    const target = 0.72;
    const pts: string[] = [];
    const N = 60;
    for (let i = 0; i <= N; i++) {
      const t = t0 + ((t1 - t0) * i) / N;
      const dt = (t - reactAt) / 4000; // ramp over ~4s
      const s = 1 / (1 + Math.exp(-dt));
      const v = baseline + (target - baseline) * (t >= t0 ? s : 0);
      pts.push(`${x(t).toFixed(1)},${y(v).toFixed(1)}`);
    }

    const mk: Marker[] = [];
    if (utt != null) mk.push({ label: 'utterance', ts: utt, color: '#38bdf8' });
    if (alert != null) mk.push({ label: 'alert', ts: alert, color: '#a78bfa' });
    if (reaction != null)
      mk.push({ label: 'reaction', ts: reaction, color: '#fb7185' });

    return {
      width: w,
      height: h,
      markers: mk.map((m) => ({ ...m, xPos: x(m.ts) })),
      path: `M ${pts.join(' L ')}`,
      times: { t0, t1, x, yBottom: h - pad.bottom },
    };
  }, [utt, alert, reaction]);

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full min-w-[420px]"
        role="img"
        aria-label="Market mid over detection window"
      >
        <rect x={0} y={0} width={width} height={height} fill="#0b1220" rx={8} />
        {/* baseline grid */}
        {[0.25, 0.5, 0.75].map((g) => (
          <line
            key={g}
            x1={0}
            x2={width}
            y1={16 + (1 - g) * (height - 44)}
            y2={16 + (1 - g) * (height - 44)}
            stroke="#1e293b"
            strokeWidth={1}
          />
        ))}
        {/* mid line */}
        <path d={path} fill="none" stroke="#34d399" strokeWidth={2} />
        {/* markers */}
        {markers.map((m) => (
          <g key={m.label}>
            <line
              x1={m.xPos}
              x2={m.xPos}
              y1={12}
              y2={times.yBottom}
              stroke={m.color}
              strokeWidth={1.5}
              strokeDasharray="4 3"
            />
            <text
              x={m.xPos}
              y={times.yBottom + 16}
              fill={m.color}
              fontSize={11}
              textAnchor="middle"
            >
              {m.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
