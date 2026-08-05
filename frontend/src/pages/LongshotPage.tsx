import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getLongshotStatus,
  getLongshotLiveStatus,
  type LongshotStatus,
  type LongshotSeriesPoint,
  type LongshotPosition,
} from "@/api/bot";
import { formatAgo } from "@/utils/date";

const REFRESH_MS = 30_000;

function fmtUsd(n: number): string {
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}
function fmtPct(n: number | null): string {
  return n == null ? "—" : `${(n * 100).toFixed(1)}%`;
}
function fmtCents(n: number | null | undefined): string {
  return n == null ? "—" : `${(n * 100).toFixed(0)}¢`;
}
function fmtDay(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function fmtDayTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function StatCard({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  const color =
    positive === undefined ? "text-white" : positive ? "text-emerald-400" : "text-red-400";
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function RecentSettledTable({ settled }: { settled: LongshotPosition[] }) {
  const rows = [...settled].sort((a, b) => (b.close_time ?? "").localeCompare(a.close_time ?? "")).slice(0, 30);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">Recently settled</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2 font-medium">Market</th>
              <th className="px-4 py-2 font-medium">Closed</th>
              <th className="px-4 py-2 font-medium text-right">Sold @</th>
              <th className="px-4 py-2 font-medium text-right">Size</th>
              <th className="px-4 py-2 font-medium text-center">Result</th>
              <th className="px-4 py-2 font-medium text-right">P&L</th>
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? rows.map((p) => (
              <tr key={p.ticker} className="border-t border-slate-800">
                <td className="px-4 py-2 font-mono text-xs text-slate-300">{p.ticker}</td>
                <td className="px-4 py-2 text-slate-400">{p.close_time ? fmtDayTime(p.close_time) : "—"}</td>
                <td className="px-4 py-2 text-right text-slate-300">{fmtCents(p.sell_price)}</td>
                <td className="px-4 py-2 text-right text-slate-300">{p.size}</td>
                <td className="px-4 py-2 text-center">
                  <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-semibold ${
                    p.result === "no" ? "bg-emerald-600/20 text-emerald-400" : "bg-red-600/20 text-red-400"
                  }`}>{(p.result ?? "").toUpperCase()}</span>
                </td>
                <td className={`px-4 py-2 text-right font-medium ${
                  (p.pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                }`}>{p.pnl == null ? "—" : fmtUsd(p.pnl)}</td>
              </tr>
            )) : (
              <tr className="border-t border-slate-800">
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">Nothing settled yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OpenPositionsTable({ open, deployed }: { open: LongshotPosition[]; deployed: number | null }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Open positions</h3>
        {deployed != null && <span className="text-xs text-slate-500">{fmtUsd(deployed)} collateral deployed</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2 font-medium">Market</th>
              <th className="px-4 py-2 font-medium text-right">Sold @</th>
              <th className="px-4 py-2 font-medium text-right">Size</th>
              <th className="px-4 py-2 font-medium text-right">Collateral</th>
              <th className="px-4 py-2 font-medium">Closes</th>
            </tr>
          </thead>
          <tbody>
            {open.length > 0 ? open.map((p) => (
              <tr key={p.ticker} className="border-t border-slate-800">
                <td className="px-4 py-2 font-mono text-xs text-slate-300">{p.ticker}</td>
                <td className="px-4 py-2 text-right text-slate-300">{fmtCents(p.sell_price)}</td>
                <td className="px-4 py-2 text-right text-slate-300">{p.size}</td>
                <td className="px-4 py-2 text-right text-slate-300">{p.collateral == null ? "—" : fmtUsd(p.collateral)}</td>
                <td className="px-4 py-2 text-slate-400">{p.close_time ? fmtDayTime(p.close_time) : "—"}</td>
              </tr>
            )) : (
              <tr className="border-t border-slate-800">
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">No open positions.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: LongshotSeriesPoint }[] }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-medium mb-1">{fmtDayTime(d.ts)}</p>
      <p className="text-emerald-400">Equity: {fmtUsd(d.equity)}</p>
      <p className="text-slate-400">Settled: {d.settled ?? 0}</p>
      <p className="text-sky-400">Hit-rate (NO): {fmtPct(d.hit_rate_no)}</p>
    </div>
  );
}

function EquityChart({ series, mounted }: { series: LongshotSeriesPoint[]; mounted: boolean }) {
  const dayTicks = (() => {
    const seen = new Set<string>();
    const ticks: string[] = [];
    for (const p of series) {
      const label = fmtDay(p.ts);
      if (!seen.has(label)) {
        seen.add(label);
        ticks.push(p.ts);
      }
    }
    return ticks;
  })();
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
      <h3 className="text-sm font-semibold text-white">Realized equity over time</h3>
      <div className="h-56 min-w-0">
        {mounted && series.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <defs>
                <linearGradient id="lsEq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#34d399" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={fmtDay} ticks={dayTicks} tick={{ fontSize: 11, fill: "#64748b" }}
                axisLine={{ stroke: "#334155" }} tickLine={false} minTickGap={20} />
              <YAxis tickFormatter={(v: number) => `$${v}`} tick={{ fontSize: 11, fill: "#64748b" }}
                axisLine={false} tickLine={false} width={64} domain={["dataMin - 5", "dataMax + 5"]} />
              <Tooltip content={<ChartTooltip />} contentStyle={{ backgroundColor: "transparent", border: "none" }} />
              <Area type="monotone" dataKey="equity" stroke="#34d399" strokeWidth={2} fill="url(#lsEq)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-slate-500 text-sm">Not enough data for chart yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}

interface DailyPnl {
  day: string;
  pnl: number;
  cum: number;
  trades: number;
  contracts: number;
}

/** Realized P&L bucketed by SETTLEMENT day.
 *
 * Derived from settled positions rather than from equity deltas in the tick series:
 * a tick snapshot moves when collateral is locked/released too, so differencing it
 * mixes cash-flow timing into what is supposed to be realized P&L. Grouping settled
 * positions by close_time gives the day the money was actually won or lost. */
function dailyPnl(settled: LongshotPosition[]): DailyPnl[] {
  const by = new Map<string, { pnl: number; trades: number; contracts: number }>();
  for (const p of settled) {
    if (!p.close_time || p.pnl == null) continue;
    const day = p.close_time.slice(0, 10);
    const acc = by.get(day) ?? { pnl: 0, trades: 0, contracts: 0 };
    acc.pnl += p.pnl;
    acc.trades += 1;
    acc.contracts += p.size ?? 0;
    by.set(day, acc);
  }
  let cum = 0;
  return [...by.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([day, a]) => {
      cum += a.pnl;
      return {
        day,
        pnl: Math.round(a.pnl * 100) / 100,
        cum: Math.round(cum * 100) / 100,
        trades: a.trades,
        contracts: a.contracts,
      };
    });
}

function DailyPnlTooltip({ active, payload }: { active?: boolean; payload?: { payload: DailyPnl }[] }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const cpc = d.contracts ? (100 * d.pnl) / d.contracts : null;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-medium mb-1">{fmtDay(`${d.day}T12:00:00Z`)}</p>
      <p className={d.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>Day: {fmtUsd(d.pnl)}</p>
      <p className="text-sky-400">Cumulative: {fmtUsd(d.cum)}</p>
      <p className="text-slate-400">
        {d.trades} settled · {d.contracts} contracts
        {cpc != null && ` · ${cpc >= 0 ? "+" : ""}${cpc.toFixed(2)}¢/ct`}
      </p>
    </div>
  );
}

/** Daily gain/loss bars with the cumulative realized line over the top.
 *
 * Two Y axes on purpose: cumulative P&L outgrows a single day's swing over time,
 * so on one shared axis the daily bars flatten into invisibility exactly as the
 * history gets long enough to be worth reading. */
function DailyPnlChart({ settled, mounted }: { settled: LongshotPosition[]; mounted: boolean }) {
  const data = useMemo(() => dailyPnl(settled), [settled]);
  const best = data.reduce((m, d) => (d.pnl > m ? d.pnl : m), 0);
  const worst = data.reduce((m, d) => (d.pnl < m ? d.pnl : m), 0);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-white">Daily realized P&L</h3>
        {data.length > 0 && (
          <span className="text-xs text-slate-500">
            {data.length} days · best <span className="text-emerald-400">{fmtUsd(best)}</span> · worst{" "}
            <span className="text-red-400">{fmtUsd(worst)}</span>
          </span>
        )}
      </div>
      <div className="h-56 min-w-0">
        {mounted && data.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 5, right: 4, bottom: 5, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d: string) => fmtDay(`${d}T12:00:00Z`)}
                tick={{ fontSize: 11, fill: "#64748b" }} axisLine={{ stroke: "#334155" }}
                tickLine={false} minTickGap={24} />
              <YAxis yAxisId="daily" tickFormatter={(v: number) => `$${v}`}
                tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} width={52} />
              <YAxis yAxisId="cum" orientation="right" tickFormatter={(v: number) => `$${v}`}
                tick={{ fontSize: 11, fill: "#38bdf8" }} axisLine={false} tickLine={false} width={52} />
              <Tooltip content={<DailyPnlTooltip />} cursor={{ fill: "#1e293b", fillOpacity: 0.4 }} />
              <ReferenceLine yAxisId="daily" y={0} stroke="#475569" />
              {/* Entry animation off: this page re-polls every 30s, and recharts replays
                  the whole draw-on animation each time new data lands — the chart spends
                  a chunk of every refresh unreadable. */}
              <Bar yAxisId="daily" dataKey="pnl" radius={[2, 2, 0, 0]} maxBarSize={26}
                isAnimationActive={false}>
                {data.map((d) => (
                  <Cell key={d.day} fill={d.pnl >= 0 ? "#34d399" : "#f87171"} />
                ))}
              </Bar>
              <Line yAxisId="cum" type="monotone" dataKey="cum" stroke="#38bdf8" strokeWidth={2}
                dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-slate-500 text-sm">Not enough settled days for a chart yet.</p>
          </div>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Bars = that day&apos;s realized gain/loss · <span className="text-sky-400">line</span> = cumulative.
        Bucketed by settlement day.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LIVE section — real money. Execution mode (dry-run / armed / killed) is the
// sub-state; this is the primary view now that a real account is running.
// ---------------------------------------------------------------------------
function LiveSection({ live, mounted }: { live: LongshotStatus | null; mounted: boolean }) {
  const hb = live?.heartbeat ?? null;
  const latest = live?.latest ?? null;
  const open = live?.open_positions ?? [];
  const settled = live?.settled_positions ?? [];
  const slip = latest?.slippage;

  const killed = !!latest?.killed;
  const running = !!hb && hb.status === "ok";
  const dryRun = !!latest?.dry_run;
  const pill = !hb
    ? { text: "NOT RUNNING", cls: "bg-slate-700/40 text-slate-400 border-slate-700" }
    : hb.status !== "ok"
    ? { text: "ERROR", cls: "bg-red-600/20 text-red-400 border-red-800" }
    : killed
    ? { text: "KILLED", cls: "bg-red-600/20 text-red-400 border-red-800" }
    : dryRun
    ? { text: "DRY-RUN", cls: "bg-amber-600/20 text-amber-400 border-amber-800" }
    : { text: "ARMED", cls: "bg-red-600/20 text-red-400 border-red-800" };

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold text-white">Live <span className="text-sm font-normal text-slate-500">· real money</span></h2>
        <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${pill.cls}`}>{pill.text}</span>
        {hb && <span className="text-sm text-slate-400">last tick {formatAgo(hb.wall_ts)}</span>}
        {hb?.error && <span className="text-sm text-red-400">{hb.error}</span>}
        {dryRun && running && !killed && (
          <span className="text-xs text-slate-500">observing real books — placing no orders</span>
        )}
      </div>

      {latest ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label="Equity" value={latest.equity == null ? "—" : fmtUsd(latest.equity)} />
            <StatCard label="Realized P&L" value={fmtUsd(latest.realized_pnl)}
              positive={latest.realized_pnl >= 0} />
            <StatCard label="Collateral" value={fmtUsd(latest.deployed_collateral)} />
            <StatCard label="Open" value={String(latest.open_positions)} />
            <StatCard label="Fill-rate" value={slip ? fmtPct(slip.fill_rate) : "—"} />
            <StatCard label="Avg slippage"
              value={slip?.avg_slippage_c == null ? "—" : `${slip.avg_slippage_c.toFixed(2)}¢`}
              positive={slip?.avg_slippage_c == null ? undefined : slip.avg_slippage_c <= 0} />
          </div>
          <DailyPnlChart settled={settled} mounted={mounted} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RecentSettledTable settled={settled} />
            <OpenPositionsTable open={open} deployed={latest.deployed_collateral} />
          </div>
        </>
      ) : (
        <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-6 text-center text-slate-500 text-sm">
          Live harness has no data yet.
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// PAPER section — simulated $8k control / benchmark. COLLAPSED BY DEFAULT since
// live now carries its own daily-P&L chart and is the thing actually being read.
//
// Kept rather than deleted because paper is the CONTROL, not decoration: pairing
// live against its paper twin on shared tickers is what exposed the 2026-08-04
// balance double-count (live never entered a ticker earlier than paper, on any of
// 1068 pairs). Losing the ability to eyeball that comparison would be a real loss.
// The heartbeat stays visible while collapsed so a dead paper arm is still obvious.
// ---------------------------------------------------------------------------
function PaperSection({ status, error, mounted }: { status: LongshotStatus | null; error: string | null; mounted: boolean }) {
  const [open_, setOpen] = useState(false);
  const hb = status?.heartbeat ?? null;
  const latest = status?.latest ?? null;
  const series = status?.series ?? [];
  const open = status?.open_positions ?? [];
  const settled = status?.settled_positions ?? [];
  const bannerError = error || hb?.error || null;
  const bannerOk = !bannerError && hb?.status === "ok";

  return (
    <section className="space-y-4 border-t border-slate-800 pt-6">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open_}
          aria-controls="paper-body"
          className="group flex items-center gap-2 text-lg font-bold text-white hover:text-slate-300 transition-colors"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true"
            className={`w-4 h-4 text-slate-500 transition-transform ${open_ ? "rotate-90" : ""}`}
            fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M7 4l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Paper
          <span className="text-sm font-normal text-slate-500">· simulated control (benchmark)</span>
        </button>
        <span className={`inline-flex h-2.5 w-2.5 rounded-full ${
          bannerOk ? "bg-emerald-400" : bannerError ? "bg-red-400" : "bg-amber-400"
        }`} />
        {!open_ && latest && (
          <span className="text-sm text-slate-400">
            {fmtUsd(latest.realized_pnl)} realized · {latest.settled_positions} settled
          </span>
        )}
        {hb && <span className="text-sm text-slate-400">last tick {formatAgo(hb.wall_ts)}</span>}
        {bannerError && <span className="text-sm text-red-400">{bannerError}</span>}
      </div>

      {!open_ ? null : (
      <div id="paper-body" className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-4">
        <StatCard label="Equity" value={latest ? fmtUsd(latest.equity) : "—"} />
        <StatCard label="Realized P&L" value={latest ? fmtUsd(latest.realized_pnl) : "—"}
          positive={latest ? latest.realized_pnl >= 0 : undefined} />
        <StatCard label="Collateral" value={latest ? fmtUsd(latest.deployed_collateral) : "—"} />
        <StatCard label="Open" value={latest ? String(latest.open_positions) : "—"} />
        <StatCard label="Settled" value={latest ? String(latest.settled_positions) : "—"} />
        <StatCard label="Hit-rate (NO)" value={latest ? fmtPct(latest.hit_rate_no) : "—"} />
        <StatCard label="ROI / collat" value={latest ? fmtPct(latest.roi_on_settled_collateral) : "—"}
          positive={latest?.roi_on_settled_collateral != null ? latest.roi_on_settled_collateral >= 0 : undefined} />
      </div>

      <DailyPnlChart settled={settled} mounted={mounted} />
      <EquityChart series={series} mounted={mounted} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RecentSettledTable settled={settled} />
        <OpenPositionsTable open={open} deployed={latest?.deployed_collateral ?? null} />
      </div>
      </div>
      )}
    </section>
  );
}

export default function LongshotPage() {
  const [status, setStatus] = useState<LongshotStatus | null>(null);
  const [live, setLive] = useState<LongshotStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    let active = true;
    const load = () => {
      getLongshotStatus()
        .then((d) => {
          if (!active) return;
          setStatus(d);
          setError(null);
        })
        .catch(() => active && setError("Failed to load longshot status"))
        .finally(() => active && setLoading(false));
      getLongshotLiveStatus()
        .then((d) => active && setLive(d))
        .catch(() => active && setLive(null));
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  if (loading && !status) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500 text-sm">Loading longshot…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-white">Longshot Short</h1>
      <LiveSection live={live} mounted={mounted} />
      <PaperSection status={status} error={error} mounted={mounted} />
    </div>
  );
}
