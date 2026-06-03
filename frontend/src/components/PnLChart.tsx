import { useEffect, useState } from "react";
import {
  Area,
  Bar,
  ComposedChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import type { PnLChartData } from "@/api/bot";
import { getPnLChart } from "@/api/bot";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

function formatDate(dateStr: string) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function PnLChart({ refreshKey }: { refreshKey?: number }) {
  const [mounted, setMounted] = useState(false);
  const [data, setData] = useState<PnLChartData | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    setLoading(true);
    getPnLChart(days).then(setData).finally(() => setLoading(false));
  }, [days, refreshKey]);

  if (loading && !data) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-64 flex items-center justify-center">
        <p className="text-slate-500 text-sm">Loading P&L chart...</p>
      </div>
    );
  }

  if (!data || data.daily.length < 1) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-48 flex items-center justify-center">
        <p className="text-slate-500 text-sm">Not enough data for P&L chart yet.</p>
      </div>
    );
  }

  const lastIdx = data.daily.length - 1;
  const todayPnl = data.daily[lastIdx].pnl_usd;
  const todayPctOfTotal = data.total_pnl_usd !== 0 ? (todayPnl / data.total_pnl_usd) * 100 : 0;

  const chartData = data.daily.map((d, i) => ({
    ...d,
    pnlDollars: d.pnl_usd,
    cumulativeDollars: d.cumulative_pnl_usd,
    todayPnL: i === lastIdx ? d.pnl_usd : undefined,
    todayPctOfTotal: i === lastIdx ? todayPctOfTotal : undefined,
  }));

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Cumulative P&L</h3>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`text-xs px-2.5 py-1 rounded transition-colors ${
                days === p.days
                  ? "bg-emerald-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-56 min-w-0">
        {mounted && (
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
            <defs>
              <linearGradient id="pnlGradientPos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="pnlGradientNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f87171" stopOpacity={0.02} />
                <stop offset="100%" stopColor="#f87171" stopOpacity={0.3} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              tick={{ fontSize: 11, fill: "#64748b" }}
              axisLine={{ stroke: "#334155" }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `$${v}`}
              tick={{ fontSize: 11, fill: "#64748b" }}
              axisLine={false}
              tickLine={false}
              width={50}
            />
            <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
            <Bar dataKey="pnlDollars" fill="#475569" opacity={0.5} barSize={8} radius={[2, 2, 0, 0]} />
            <Bar dataKey="todayPnL" fill="#fbbf24" barSize={8} radius={[2, 2, 0, 0]} />
            <Area
              type="monotone"
              dataKey="cumulativeDollars"
              stroke={data.total_pnl_usd >= 0 ? "#34d399" : "#f87171"}
              strokeWidth={2}
              fill={data.total_pnl_usd >= 0 ? "url(#pnlGradientPos)" : "url(#pnlGradientNeg)"}
            />
          </ComposedChart>
        </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-5 gap-3 text-center">
        <div>
          <p className="text-xs text-slate-500">Today</p>
          <p className={`text-sm font-medium ${todayPnl >= 0 ? "text-amber-400" : "text-red-400"}`}>
            {todayPnl >= 0 ? "+" : ""}${todayPnl.toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-600">{todayPctOfTotal.toFixed(1)}% of total</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Best Day</p>
          <p className={`text-sm font-medium ${data.best_day_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {data.best_day_usd >= 0 ? "+" : ""}${data.best_day_usd.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Worst Day</p>
          <p className={`text-sm font-medium ${data.worst_day_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {data.worst_day_usd >= 0 ? "+" : ""}${data.worst_day_usd.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Winning Days</p>
          <p className="text-sm font-medium text-white">{data.winning_days}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Losing Days</p>
          <p className="text-sm font-medium text-white">{data.losing_days}</p>
        </div>
      </div>
    </div>
  );
}
