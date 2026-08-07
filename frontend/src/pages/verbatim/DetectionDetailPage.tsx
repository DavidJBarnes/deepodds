import { Link, useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api } from '@/api/verbatim';
import { useFetch } from '@/hooks/verbatim/useFetch';
import { MoneyChart } from '@/components/verbatim/charts/MoneyChart';
import { Badge, Card, ErrorBox, Spinner } from '@/components/verbatim/ui';
import { clsx, formatDateTime, formatSeconds } from '@/utils/verbatimFormat';
import type { DetectionOut } from '@/types/verbatim';

function highlightSpan(text: string, span: string | null) {
  if (!span) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(span.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-yellow-400/30 px-0.5 text-yellow-100">
        {text.slice(idx, idx + span.length)}
      </mark>
      {text.slice(idx + span.length)}
    </>
  );
}

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-slate-200">
          {value == null ? '—' : value.toFixed(3)}
        </span>
      </div>
      <div className="h-2 w-full rounded bg-slate-800">
        <div
          className="h-2 rounded bg-emerald-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function DetectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const numId = Number(id);
  const { data, loading, error } = useFetch<DetectionOut>(
    () => api.detection(numId),
    [numId],
  );

  // clip_path is an S3 object KEY, not a playable path — the bucket is private,
  // so the API signs a short-lived GET per request. Fetched lazily once the
  // detection loads rather than eagerly for every row in a list.
  const [clipSrc, setClipSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!data?.clip_path) {
      setClipSrc(null);
      return;
    }
    let active = true;
    api
      .clipUrl(data.id)
      .then((url) => active && setClipSrc(url))
      .catch(() => active && setClipSrc(null));
    return () => {
      active = false;
    };
  }, [data]);

  if (loading) return <Spinner label="Loading detection…" />;
  if (error) return <ErrorBox message={error} />;
  if (!data)
    return <div className="text-slate-500">Detection not found.</div>;

  const d = data;
  const edge = d.edge_seconds;
  const edgeWon = edge != null && edge >= 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link to="/history" className="text-sm text-emerald-400 hover:underline">
          ← History
        </Link>
        <h1 className="text-lg font-semibold text-white">Detection #{d.id}</h1>
        <Badge color={d.state === 'confirmed' ? 'green' : 'red'}>
          {d.state}
        </Badge>
        {d.speaker_label && (
          <Badge color={d.speaker_is_expected ? 'green' : 'yellow'}>
            {d.speaker_label}
            {d.speaker_is_expected === false ? ' (unexpected)' : ''}
          </Badge>
        )}
      </div>

      {/* Edge headline */}
      <Card
        className={clsx(
          'flex flex-col items-center py-6',
          edge == null
            ? ''
            : edgeWon
              ? 'border-green-700 bg-green-950/40'
              : 'border-red-700 bg-red-950/40',
        )}
      >
        <div className="text-xs uppercase tracking-wide text-slate-400">
          Edge
        </div>
        <div
          className={clsx(
            'text-4xl font-bold tabular-nums',
            edge == null
              ? 'text-slate-400'
              : edgeWon
                ? 'text-green-400'
                : 'text-red-400',
          )}
        >
          {formatSeconds(edge)}
        </div>
        <div className="mt-1 text-sm">
          {edge == null ? (
            <span className="text-slate-500">no market reaction recorded</span>
          ) : edgeWon ? (
            <span className="text-green-300">Verbatim won</span>
          ) : (
            <span className="text-red-300">market moved first</span>
          )}
        </div>
      </Card>

      {/* Audio */}
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-300">Clip</h3>
        {clipSrc ? (
          <audio controls src={clipSrc} className="w-full">
            Your browser does not support audio playback.
          </audio>
        ) : (
          <div className="text-sm text-slate-500">No clip available.</div>
        )}
        {d.clip_path && (
          <div className="mt-1 font-mono text-xs text-slate-600">
            {d.clip_path}
          </div>
        )}
      </Card>

      {/* Transcripts side by side */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-300">
            Stage 1 transcript
          </h3>
          <p className="text-sm leading-relaxed text-slate-200">
            {highlightSpan(d.stage1_transcript, d.matched_span)}
          </p>
        </Card>
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-300">
            Stage 2 transcript
          </h3>
          <p className="text-sm leading-relaxed text-slate-200">
            {d.stage2_transcript ? (
              highlightSpan(d.stage2_transcript, d.matched_span)
            ) : (
              <span className="text-slate-500">— not run —</span>
            )}
          </p>
        </Card>
      </div>

      {/* Score breakdown */}
      <Card>
        <h3 className="mb-3 text-sm font-semibold text-slate-300">
          Score breakdown
        </h3>
        <div className="space-y-3">
          <ScoreBar label="Stage 1" value={d.stage1_score} />
          <ScoreBar label="Stage 2" value={d.stage2_score} />
          <ScoreBar
            label="Confirm"
            value={
              d.state === 'confirmed'
                ? (d.stage2_score ?? d.stage1_score)
                : 0
            }
          />
        </div>
        {d.matched_span && (
          <div className="mt-3 text-sm">
            <span className="text-slate-500">Matched span: </span>
            <span className="font-medium text-yellow-200">
              {d.matched_span}
            </span>
          </div>
        )}
      </Card>

      {/* Money chart */}
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-300">
          Market mid &amp; timing
        </h3>
        <MoneyChart detection={d} />
      </Card>

      {/* Timestamps */}
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-300">
          Pipeline timestamps
        </h3>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          {(
            [
              ['utterance', d.utterance_ts],
              ['chunk_capture', d.chunk_capture_ts],
              ['stage1_done', d.stage1_done_ts],
              ['candidate', d.candidate_ts],
              ['stage2_done', d.stage2_done_ts],
              ['alert_sent', d.alert_sent_ts],
              ['market_reaction', d.market_reaction_ts],
            ] as const
          ).map(([label, ts]) => (
            <div key={label} className="flex justify-between gap-2">
              <dt className="text-slate-500">{label}</dt>
              <dd className="font-mono text-slate-300">
                {formatDateTime(ts)}
              </dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}

// Default export so React.lazy can code-split this route.
export default DetectionDetailPage;
