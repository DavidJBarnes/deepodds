import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
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

// ---------------------------------------------------------------------------
// LIVE section — real money. Execution mode (dry-run / armed / killed) is the
// sub-state; this is the primary view now that a real account is running.
// ---------------------------------------------------------------------------
function LiveSection({ live }: { live: LongshotStatus | null }) {
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
// PAPER section — simulated $8k control / benchmark. Always running as the
// shadow we compare live fills against.
// ---------------------------------------------------------------------------
function PaperSection({ status, error, mounted }: { status: LongshotStatus | null; error: string | null; mounted: boolean }) {
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
        <h2 className="text-lg font-bold text-white">Paper <span className="text-sm font-normal text-slate-500">· simulated control (benchmark)</span></h2>
        <span className={`inline-flex h-2.5 w-2.5 rounded-full ${
          bannerOk ? "bg-emerald-400" : bannerError ? "bg-red-400" : "bg-amber-400"
        }`} />
        <span className="text-sm text-slate-400">{hb ? hb.status : "no heartbeat"}</span>
        {hb && <span className="text-sm text-slate-400">last tick {formatAgo(hb.wall_ts)}</span>}
        {bannerError && <span className="text-sm text-red-400">{bannerError}</span>}
      </div>

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

      <EquityChart series={series} mounted={mounted} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RecentSettledTable settled={settled} />
        <OpenPositionsTable open={open} deployed={latest?.deployed_collateral ?? null} />
      </div>
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
      <LiveSection live={live} />
      <PaperSection status={status} error={error} mounted={mounted} />
    </div>
  );
}
