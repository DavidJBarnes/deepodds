import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/verbatim';
import { useFetch } from '@/hooks/verbatim/useFetch';
import { Badge, Card, ErrorBox, Spinner } from '@/components/verbatim/ui';
import { clsx, formatDateTime } from '@/utils/verbatimFormat';
import type { MarketOut, PatternOut, ParseStatus } from '@/types/verbatim';

function parseStatusColor(status: ParseStatus) {
  switch (status) {
    case 'parsed':
      return 'green' as const;
    case 'needs_review':
      return 'yellow' as const;
    case 'raw_rules':
      return 'purple' as const;
    default:
      return 'slate' as const;
  }
}

export function WatchlistPage() {
  const marketsFetch = useFetch<MarketOut[]>(() => api.markets(), []);
  const markets = marketsFetch.data ?? [];

  const needsReview = markets.filter((m) => m.parse_status === 'needs_review');

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-white">Watchlist</h1>

      <ArmStreamForm markets={markets} />

      {marketsFetch.loading && <Spinner label="Loading markets…" />}
      {marketsFetch.error && <ErrorBox message={marketsFetch.error} />}

      {needsReview.length > 0 && (
        <Card className="border-yellow-800 bg-yellow-950/30">
          <h2 className="mb-1 text-sm font-semibold text-yellow-300">
            Needs review ({needsReview.length})
          </h2>
          <div className="flex flex-wrap gap-2 text-xs">
            {needsReview.map((m) => (
              <a
                key={m.id}
                href={`#market-${m.id}`}
                className="rounded bg-yellow-900/50 px-2 py-1 font-mono text-yellow-200 hover:bg-yellow-900"
              >
                {m.ticker}
              </a>
            ))}
          </div>
        </Card>
      )}

      <div className="space-y-4">
        {markets.map((m) => (
          <MarketRow
            key={m.id}
            market={m}
            onMarketChange={(updated) =>
              marketsFetch.setData((prev) =>
                (prev ?? []).map((x) => (x.id === updated.id ? updated : x)),
              )
            }
          />
        ))}
      </div>
    </div>
  );
}

function MarketRow({
  market,
  onMarketChange,
}: {
  market: MarketOut;
  onMarketChange: (m: MarketOut) => void;
}) {
  const patternsFetch = useFetch<PatternOut[]>(
    () => api.patterns(market.id),
    [market.id],
  );
  const [patterns, setPatterns] = useState<PatternOut[]>([]);
  const [newPhrase, setNewPhrase] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (patternsFetch.data) setPatterns(patternsFetch.data);
  }, [patternsFetch.data]);

  const toggleActive = async (p: PatternOut) => {
    setErr(null);
    try {
      const updated = await api.setPatternActive(p.id, !p.active);
      setPatterns((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'toggle failed');
    }
  };

  const addPattern = async () => {
    const phrase = newPhrase.trim();
    if (!phrase) return;
    setBusy(true);
    setErr(null);
    try {
      const list = await api.addPattern(market.id, phrase);
      setPatterns(list);
      setNewPhrase('');
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'add failed');
    } finally {
      setBusy(false);
    }
  };

  const toggleArm = async () => {
    setBusy(true);
    setErr(null);
    try {
      const updated = await api.armMarket(market.id, !market.armed);
      onMarketChange(updated);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'arm failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      className={clsx(
        'scroll-mt-16',
        market.parse_status === 'needs_review' && 'border-yellow-800',
      )}
    >
      <div id={`market-${market.id}`} />
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-500">
              {market.ticker}
            </span>
            <Badge color={parseStatusColor(market.parse_status)}>
              {market.parse_status}
            </Badge>
            {market.armed && <Badge color="green">armed</Badge>}
          </div>
          <div className="mt-0.5 text-sm font-medium text-slate-100">
            {market.title}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {market.speaker && <span>speaker: {market.speaker} · </span>}
            deadline: {formatDateTime(market.deadline_utc)}
          </div>
        </div>
        <button
          onClick={toggleArm}
          disabled={busy}
          className={clsx(
            'rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50',
            market.armed
              ? 'bg-red-900/60 text-red-200 hover:bg-red-900'
              : 'bg-green-900/60 text-green-200 hover:bg-green-900',
          )}
        >
          {market.armed ? 'Disarm' : 'Arm'}
        </button>
      </div>

      {err && <div className="mt-2 text-xs text-red-400">{err}</div>}

      <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Raw rules */}
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Raw rules
          </h4>
          <pre className="scroll-thin max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-950/60 p-2 text-xs text-slate-400">
            {market.raw_rules || '— none —'}
          </pre>
        </div>

        {/* Parsed patterns */}
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Patterns
          </h4>
          {patternsFetch.loading && <Spinner />}
          {patternsFetch.error && <ErrorBox message={patternsFetch.error} />}
          <ul className="space-y-1">
            {patterns.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-2 rounded bg-slate-800/50 px-2 py-1 text-sm"
              >
                <div className="min-w-0">
                  <span
                    className={clsx(
                      'truncate',
                      p.active ? 'text-slate-100' : 'text-slate-500 line-through',
                    )}
                  >
                    {p.variant || p.phrase}
                  </span>
                  <span className="ml-2 text-xs text-slate-600">
                    {p.variant_kind}
                    {p.manual && ' · manual'} · v{p.version}
                  </span>
                </div>
                <button
                  onClick={() => toggleActive(p)}
                  className={clsx(
                    'shrink-0 rounded px-2 py-0.5 text-xs',
                    p.active
                      ? 'bg-green-900/60 text-green-200'
                      : 'bg-slate-700 text-slate-300',
                  )}
                >
                  {p.active ? 'active' : 'off'}
                </button>
              </li>
            ))}
            {patterns.length === 0 && !patternsFetch.loading && (
              <li className="text-xs text-slate-600">no patterns</li>
            )}
          </ul>

          <div className="mt-2 flex gap-2">
            <input
              value={newPhrase}
              onChange={(e) => setNewPhrase(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void addPattern();
              }}
              placeholder="add manual phrase…"
              className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
            />
            <button
              onClick={() => void addPattern()}
              disabled={busy || !newPhrase.trim()}
              className="rounded bg-emerald-800 px-3 py-1 text-sm text-emerald-100 hover:bg-emerald-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function ArmStreamForm({ markets }: { markets: MarketOut[] }) {
  const [url, setUrl] = useState('');
  const [label, setLabel] = useState('');
  const [speaker, setSpeaker] = useState('');
  const [armedUntil, setArmedUntil] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const toggleMarket = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const submit = async () => {
    if (!url.trim()) {
      setErr('URL is required');
      return;
    }
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      const stream = await api.armStream({
        url: url.trim(),
        label: label.trim() || null,
        expected_speaker: speaker.trim() || null,
        armed_until: armedUntil
          ? new Date(armedUntil).toISOString()
          : null,
        market_ids: selected.size ? Array.from(selected) : undefined,
      });
      setOk(`Armed stream #${stream.id} (${stream.status})`);
      setUrl('');
      setLabel('');
      setSpeaker('');
      setArmedUntil('');
      setSelected(new Set());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'arm failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-slate-300">
        Arm a stream
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs text-slate-400">
          Stream URL
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-600 focus:outline-none"
          />
        </label>
        <label className="text-xs text-slate-400">
          Label (optional)
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-600 focus:outline-none"
          />
        </label>
        <label className="text-xs text-slate-400">
          Expected speaker (optional)
          <input
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-600 focus:outline-none"
          />
        </label>
        <label className="text-xs text-slate-400">
          Armed until (optional)
          <input
            type="datetime-local"
            value={armedUntil}
            onChange={(e) => setArmedUntil(e.target.value)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-600 focus:outline-none"
          />
        </label>
      </div>

      {markets.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-slate-400">
            Attach markets (optional)
          </div>
          <div className="scroll-thin flex max-h-32 flex-wrap gap-1 overflow-auto">
            {markets.map((m) => (
              <button
                key={m.id}
                onClick={() => toggleMarket(m.id)}
                className={clsx(
                  'rounded px-2 py-0.5 text-xs',
                  selected.has(m.id)
                    ? 'bg-emerald-800 text-emerald-100'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
                )}
              >
                {m.ticker}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => void submit()}
          disabled={busy}
          className="rounded bg-emerald-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
        >
          {busy ? 'Arming…' : 'Arm stream'}
        </button>
        {err && <span className="text-xs text-red-400">{err}</span>}
        {ok && <span className="text-xs text-green-400">{ok}</span>}
      </div>
    </Card>
  );
}

// Default export so React.lazy can code-split this route.
export default WatchlistPage;
