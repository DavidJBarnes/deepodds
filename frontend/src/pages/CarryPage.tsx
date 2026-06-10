import { useEffect, useState } from "react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getCarryStatus, type CarryStatus, type CarrySeriesPoint } from "@/api/bot";
import { formatAgo, formatUnixTime } from "@/utils/date";

const REFRESH_MS = 30_000;

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

function fmtUsd(n: number): string {
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

function fmtPct(n: number | null): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function fmtRatio(n: number | null): string {
  if (n == null) return "—";
  return n.toFixed(2);
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: CarrySeriesPoint }[];
}) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-medium mb-1">{formatUnixTime(d.ts)}</p>
      <p className="text-emerald-400">Equity: {fmtUsd(d.equity)}</p>
      <p className="text-sky-400">Accrued funding: {fmtUsd(d.accrued_funding)}</p>
    </div>
  );
}

export default function CarryPage() {
  const [status, setStatus] = useState<CarryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    let active = true;
    const load = () => {
      getCarryStatus()
        .then((d) => {
          if (!active) return;
          setStatus(d);
          setError(null);
        })
        .catch(() => {
          if (active) setError("Failed to load carry status");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
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
        <p className="text-slate-500 text-sm">Loading funding carry…</p>
      </div>
    );
  }

  const hb = status?.heartbeat ?? null;
  const latest = status?.latest ?? null;
  const series = status?.series ?? [];
  const killed = hb?.killed || latest?.killed || false;
  const bannerError = error || hb?.error || null;
  const bannerOk = !bannerError && (hb?.status === "ok" || hb?.status === "running");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Funding Carry</h1>
      </div>

      {/* Liveness banner */}
      <div
        className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${
          bannerError
            ? "border-red-800 bg-red-950/40"
            : "border-slate-800 bg-slate-900"
        }`}
      >
        <span
          className={`inline-flex h-2.5 w-2.5 rounded-full ${
            bannerOk ? "bg-emerald-400" : bannerError ? "bg-red-400" : "bg-amber-400"
          }`}
        />
        <span className="text-sm font-medium text-white">
          {hb ? hb.status : "no heartbeat"}
        </span>
        {hb && (
          <span className="text-sm text-slate-400">last tick {formatAgo(hb.wall_ts)}</span>
        )}
        {bannerError && <span className="text-sm text-red-400">{bannerError}</span>}
        {killed && (
          <span className="ml-auto inline-flex items-center rounded-md bg-red-600 px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-white">
            Killed
          </span>
        )}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Equity" value={latest ? fmtUsd(latest.equity) : "—"} />
        <StatCard
          label="Accrued Funding"
          value={latest ? fmtUsd(latest.accrued_funding_total) : "—"}
          positive={latest ? latest.accrued_funding_total >= 0 : undefined}
        />
        <StatCard
          label="Realized P&L"
          value={latest ? fmtUsd(latest.realized_pnl) : "—"}
          positive={latest ? latest.realized_pnl >= 0 : undefined}
        />
        <StatCard label="Cash" value={latest ? fmtUsd(latest.cash) : "—"} />
      </div>

      {/* Per-symbol table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-white">Positions</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2 font-medium">Symbol</th>
                <th className="px-4 py-2 font-medium text-right">Funding now (%/yr)</th>
                <th className="px-4 py-2 font-medium text-right">Trailing 7d (%/yr)</th>
                <th className="px-4 py-2 font-medium text-right">Target $</th>
                <th className="px-4 py-2 font-medium text-right">Notional $</th>
                <th className="px-4 py-2 font-medium text-right">Margin ratio</th>
                <th className="px-4 py-2 font-medium text-right">Accrued funding $</th>
              </tr>
            </thead>
            <tbody>
              {latest && Object.keys(latest.symbols).length > 0 ? (
                Object.entries(latest.symbols).map(([sym, s]) => {
                  const flat = s.notional === 0;
                  return (
                    <tr key={sym} className="border-t border-slate-800">
                      <td className="px-4 py-2 font-medium text-white">{sym}</td>
                      <td className="px-4 py-2 text-right text-slate-300">{fmtPct(s.funding_ann)}</td>
                      <td className="px-4 py-2 text-right text-slate-300">{fmtPct(s.trailing_ann)}</td>
                      <td className="px-4 py-2 text-right text-slate-300">{fmtUsd(s.target)}</td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {flat ? <span className="text-slate-500">flat</span> : fmtUsd(s.notional)}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-300">{fmtRatio(s.margin_ratio)}</td>
                      <td
                        className={`px-4 py-2 text-right ${
                          s.accrued_funding >= 0 ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {fmtUsd(s.accrued_funding)}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr className="border-t border-slate-800">
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                    No symbols.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Chart */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h3 className="text-sm font-semibold text-white">Equity &amp; Accrued Funding</h3>
        <div className="h-64 min-w-0">
          {mounted && series.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={series} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                <defs>
                  <linearGradient id="fundingGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                <XAxis
                  dataKey="ts"
                  tickFormatter={formatUnixTime}
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  axisLine={{ stroke: "#334155" }}
                  tickLine={false}
                />
                <YAxis
                  tickFormatter={(v: number) => `$${v}`}
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                />
                <Tooltip content={<ChartTooltip />} contentStyle={{ backgroundColor: "transparent", border: "none" }} />
                <Area
                  type="monotone"
                  dataKey="accrued_funding"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  fill="url(#fundingGradient)"
                />
                <Line type="monotone" dataKey="equity" stroke="#34d399" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center">
              <p className="text-slate-500 text-sm">Not enough data for chart yet.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
