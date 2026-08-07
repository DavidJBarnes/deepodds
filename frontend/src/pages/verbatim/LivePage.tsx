import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api } from '@/api/verbatim';
import { useFetch } from '@/hooks/verbatim/useFetch';
import { useWebSocket } from '@/hooks/verbatim/useWebSocket';
import { useNow } from '@/hooks/verbatim/useNow';
import { HealthStrip } from '@/components/verbatim/HealthStrip';
import {
  TranscriptPanel,
  type TranscriptLine,
} from '@/components/verbatim/TranscriptPanel';
import {
  WatchlistSidebar,
  type WatchItem,
} from '@/components/verbatim/WatchlistSidebar';
import { ErrorBox, Spinner } from '@/components/verbatim/ui';
import type {
  DetectionOut,
  HealthOut,
  HeartbeatOut,
  MarketOut,
  MarketQuoteEvent,
  PatternOut,
  StreamOut,
  WsMessage,
} from '@/types/verbatim';

const MAX_LINES = 200;

export function LivePage() {
  const nowMs = useNow(1000);

  // Static-ish data (reloaded on mount / manual).
  const streamsFetch = useFetch<StreamOut[]>(() => api.streams(), []);
  const marketsFetch = useFetch<MarketOut[]>(() => api.markets(), []);

  const [health, setHealth] = useState<HealthOut | null>(null);
  const [heartbeats, setHeartbeats] = useState<HeartbeatOut[]>([]);
  const [quotes, setQuotes] = useState<Record<string, MarketQuoteEvent>>({});
  const [linesByStream, setLinesByStream] = useState<
    Record<number, TranscriptLine[]>
  >({});
  const [pulsing, setPulsing] = useState<Set<number>>(new Set());
  const [recentDetections, setRecentDetections] = useState<DetectionOut[]>([]);
  const [watchPatterns, setWatchPatterns] = useState<
    Record<number, PatternOut[]>
  >({});

  const lineSeq = useRef(0);
  const pulseTimers = useRef<Map<number, number>>(new Map());

  // Poll health + heartbeats periodically.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .health()
        .then((h) => !cancelled && setHealth(h))
        .catch(() => undefined);
      api
        .heartbeats(50)
        .then((hb) => !cancelled && setHeartbeats(hb))
        .catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Load patterns for armed markets.
  const armedMarkets = (marketsFetch.data ?? []).filter((m) => m.armed);
  const armedKey = armedMarkets.map((m) => m.id).join(',');
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      armedMarkets.map((m) =>
        api
          .patterns(m.id)
          .then((p) => [m.id, p] as const)
          .catch(() => [m.id, [] as PatternOut[]] as const),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const rec: Record<number, PatternOut[]> = {};
      for (const [id, p] of entries) rec[id] = p;
      setWatchPatterns(rec);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armedKey]);

  const pulsePattern = useCallback((patternId: number) => {
    setPulsing((prev) => {
      const next = new Set(prev);
      next.add(patternId);
      return next;
    });
    const timers = pulseTimers.current;
    const existing = timers.get(patternId);
    if (existing) window.clearTimeout(existing);
    const t = window.setTimeout(() => {
      setPulsing((prev) => {
        const next = new Set(prev);
        next.delete(patternId);
        return next;
      });
      timers.delete(patternId);
    }, 1200);
    timers.set(patternId, t);
  }, []);

  const onMessage = useCallback(
    (msg: WsMessage) => {
      switch (msg.type) {
        case 'transcript': {
          const ev = msg.data as import('@/types/verbatim').TranscriptEvent;
          const key = `t${lineSeq.current++}`;
          setLinesByStream((prev) => {
            const cur = prev[ev.stream_id] ?? [];
            const next = [
              ...cur,
              { key, event: ev, receivedAt: Date.now() },
            ].slice(-MAX_LINES);
            return { ...prev, [ev.stream_id]: next };
          });
          break;
        }
        case 'near_miss': {
          const ev = msg.data as import('@/types/verbatim').NearMissEvent;
          pulsePattern(ev.pattern_id);
          break;
        }
        case 'detection': {
          const ev = msg.data as DetectionOut;
          setRecentDetections((prev) => [ev, ...prev].slice(0, 20));
          break;
        }
        case 'heartbeat': {
          const ev = msg.data as HeartbeatOut;
          setHeartbeats((prev) => [ev, ...prev].slice(0, 80));
          break;
        }
        case 'market': {
          const ev = msg.data as MarketQuoteEvent;
          setQuotes((prev) => ({ ...prev, [ev.ticker]: ev }));
          break;
        }
        default:
          break;
      }
    },
    [pulsePattern],
  );

  // Browsers cannot set an Authorization header on a WebSocket handshake, so the
  // DeepOdds JWT rides in the query string. The API validates it BEFORE accept(),
  // closing 4401 on a bad token rather than connecting an unauthenticated peer.
  const wsPath = useMemo(
    () => `/api/v1/verbatim/ws?token=${encodeURIComponent(localStorage.getItem('token') ?? '')}`,
    [],
  );
  const { status: wsStatus, send } = useWebSocket(wsPath, onMessage);

  // Client keepalive ping.
  useEffect(() => {
    const id = window.setInterval(() => send('ping'), 20000);
    return () => window.clearInterval(id);
  }, [send]);

  const streams = streamsFetch.data ?? [];
  const watchItems: WatchItem[] = armedMarkets.map((m) => ({
    market: m,
    patterns: watchPatterns[m.id] ?? [],
  }));

  const loading = streamsFetch.loading || marketsFetch.loading;
  const error = streamsFetch.error ?? marketsFetch.error;

  return (
    <div className="space-y-4">
      <HealthStrip
        health={health}
        streams={streams}
        heartbeats={heartbeats}
        wsStatus={wsStatus}
        nowMs={nowMs}
      />

      {loading && <Spinner label="Loading streams…" />}
      {error && <ErrorBox message={error} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {!loading && streams.length === 0 && (
            <div className="rounded border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">
              No streams. Arm one from the Watchlist page.
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {streams.map((s) => (
              <div key={s.id} className="h-[360px]">
                <TranscriptPanel
                  stream={s}
                  lines={linesByStream[s.id] ?? []}
                />
              </div>
            ))}
          </div>

          {recentDetections.length > 0 && (
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Live detections
              </h3>
              <ul className="space-y-1 text-sm">
                {recentDetections.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/verbatim/detections/${d.id}`}
                      className="text-emerald-400 hover:underline"
                    >
                      #{d.id}
                    </Link>{' '}
                    <span
                      className={
                        d.state === 'confirmed'
                          ? 'text-green-400'
                          : 'text-red-400'
                      }
                    >
                      {d.state}
                    </span>{' '}
                    <span className="text-slate-400">
                      {d.matched_span || d.stage1_transcript.slice(0, 60)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <aside>
          <WatchlistSidebar
            items={watchItems}
            quotes={quotes}
            pulsing={pulsing}
            nowMs={nowMs}
          />
        </aside>
      </div>
    </div>
  );
}

// Default export so React.lazy can code-split this route.
export default LivePage;
