import type { HealthOut, HeartbeatOut, StreamOut } from '@/types/verbatim';
import { ageSeconds, clsx } from '@/utils/verbatimFormat';
import type { WsStatus } from '@/hooks/verbatim/useWebSocket';
import { Badge } from './ui';

interface Props {
  health: HealthOut | null;
  streams: StreamOut[];
  heartbeats: HeartbeatOut[];
  wsStatus: WsStatus;
  nowMs: number;
}

function AudioMeter({ level }: { level: number | null }) {
  // level assumed 0..1 (fallback clamp).
  const v = level == null ? 0 : Math.max(0, Math.min(1, level));
  const bars = 5;
  const lit = Math.round(v * bars);
  return (
    <div className="flex items-end gap-0.5" title={`audio ${v.toFixed(2)}`}>
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          className={clsx(
            'w-1 rounded-sm',
            i < lit ? 'bg-green-400' : 'bg-slate-700',
          )}
          style={{ height: `${6 + i * 3}px` }}
        />
      ))}
    </div>
  );
}

function streamColor(status: StreamOut['status']) {
  switch (status) {
    case 'live':
      return 'green' as const;
    case 'armed':
      return 'blue' as const;
    case 'dead':
      return 'red' as const;
    default:
      return 'slate' as const;
  }
}

export function HealthStrip({
  health,
  streams,
  heartbeats,
  wsStatus,
  nowMs,
}: Props) {
  // Latest heartbeat per stream + latest GPU worker heartbeat.
  const latestByStream = new Map<number, HeartbeatOut>();
  let latestGpu: HeartbeatOut | null = null;
  for (const hb of heartbeats) {
    if (hb.stream_id != null) {
      const prev = latestByStream.get(hb.stream_id);
      if (!prev || Date.parse(hb.ts) > Date.parse(prev.ts)) {
        latestByStream.set(hb.stream_id, hb);
      }
    }
    const isGpu = /gpu|worker|stage2/i.test(hb.service);
    if (isGpu && (!latestGpu || Date.parse(hb.ts) > Date.parse(latestGpu.ts))) {
      latestGpu = hb;
    }
  }

  const gpuAge = latestGpu ? ageSeconds(latestGpu.ts, nowMs) : null;
  const gpuFresh = gpuAge != null && gpuAge < 15;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-slate-500">API</span>
        {health ? (
          <Badge color={health.status === 'ok' && health.degraded.length === 0 ? 'green' : 'yellow'}>
            {health.status}
            {health.degraded.length > 0 && ` · ${health.degraded.length} degraded`}
          </Badge>
        ) : (
          <Badge color="slate">…</Badge>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-slate-500">WS</span>
        <Badge color={wsStatus === 'open' ? 'green' : wsStatus === 'connecting' ? 'yellow' : 'red'}>
          {wsStatus}
        </Badge>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-slate-500">GPU</span>
        <Badge color={gpuFresh ? 'green' : latestGpu ? 'red' : 'slate'}>
          {latestGpu ? `${gpuAge!.toFixed(0)}s ago` : 'no beat'}
        </Badge>
      </div>

      <div className="mx-1 h-4 w-px bg-slate-700" />

      {streams.length === 0 && (
        <span className="text-slate-500">no streams</span>
      )}
      {streams.map((s) => {
        const hb = latestByStream.get(s.id);
        const age = hb ? ageSeconds(hb.ts, nowMs) : null;
        return (
          <div
            key={s.id}
            className="flex items-center gap-1.5 rounded bg-slate-800/60 px-2 py-1"
          >
            <Badge color={streamColor(s.status)}>{s.status}</Badge>
            <span className="max-w-[120px] truncate text-slate-300">
              {s.label || s.url}
            </span>
            <AudioMeter level={hb?.audio_level ?? null} />
            <span className="text-slate-500">
              {hb?.chunk_rate != null ? `${hb.chunk_rate.toFixed(1)}/s` : '—'}
            </span>
            <span
              className={clsx(
                age != null && age < 10 ? 'text-green-400' : 'text-red-400',
              )}
            >
              {age != null ? `${age.toFixed(0)}s` : '—'}
            </span>
          </div>
        );
      })}
    </div>
  );
}
