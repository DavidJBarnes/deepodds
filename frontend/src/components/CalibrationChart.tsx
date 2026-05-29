import { useEffect, useState } from "react";
import { getCalibration, type CalibrationBin, type CalibrationData } from "@/api/bot";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";

const COLORS = {
  calibrated: "#38bdf8",
  overconfident: "#f87171",
  underconfident: "#4ade80",
  neutral: "#64748b",
};

function barColor(bin: CalibrationData["bins"][number]): string {
  if (bin.count === 0) return COLORS.neutral;
  const diff = bin.avg_model_prob - bin.actual_win_rate;
  if (diff > 0.05) return COLORS.overconfident;
  if (diff < -0.05) return COLORS.underconfident;
  return COLORS.calibrated;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: CalibrationBin & { modelPct: number; actualPct: number } }[] }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const diff = d.avg_model_prob - d.actual_win_rate;
  const diffLabel = diff > 0.05 ? "Overconfident" : diff < -0.05 ? "Underconfident" : "Well-calibrated";
  const diffColor = diff > 0.05 ? "text-red-400" : diff < -0.05 ? "text-emerald-400" : "text-sky-400";
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-medium mb-1">{d.bin_label}</p>
      <p className="text-sky-400">Model: {d.modelPct}%</p>
      <p className={diffColor}>Actual: {d.actualPct}%</p>
      <p className={`mt-1 ${diffColor}`}>{diffLabel}</p>
      <p className="text-slate-400 mt-1">{d.count} signals · {d.wins}W / {d.count - d.wins}L</p>
    </div>
  );
}

type CalibrationVenue = "kalshi_crypto" | "kalshi_climate";

const VENUE_TITLE: Record<CalibrationVenue, string> = {
  kalshi_crypto: "Crypto Model Calibration",
  kalshi_climate: "Climate Model Calibration",
};

export default function CalibrationChart({
  venue = "kalshi_crypto",
  refreshKey,
}: {
  venue?: CalibrationVenue;
  refreshKey?: number;
}) {
  const [data, setData] = useState<CalibrationData | null>(null);
  const [loading, setLoading] = useState(true);
  const title = VENUE_TITLE[venue];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCalibration(venue)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [venue, refreshKey]);

  if (loading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="animate-pulse h-4 w-48 bg-slate-800 rounded mb-3" />
        <div className="animate-pulse h-48 bg-slate-800 rounded" />
      </div>
    );
  }

  if (!data || data.total_samples === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-1">{title}</h3>
        <p className="text-xs text-slate-400">
          No signals have reached resolution yet. Data appears only after paper
          signals settle at expiry (exit price $0 or $1). Take-profit / edge
          exits at intermediate prices don&apos;t count — the underlying
          outcome wasn&apos;t observed.
        </p>
      </div>
    );
  }

  const chartData = data.bins.map((b) => ({
    ...b,
    modelPct: +(b.avg_model_prob * 100).toFixed(1),
    actualPct: +(b.actual_win_rate * 100).toFixed(1),
  }));

  const perfectStart = { x: chartData[0]?.bin_low ?? 0 * 100, y: chartData[0]?.bin_low ?? 0 * 100 };
  const perfectEnd = { x: 100, y: 100 };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-slate-400">
            n={data.total_samples}
          </span>
          <span className="text-slate-400">
            Brier{" "}
            <span className={data.brier_score < 0.25 ? "text-emerald-400" : "text-amber-400"}>
              {data.brier_score.toFixed(3)}
            </span>
          </span>
          {!data.reliability_ready && (
            <span className="bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-full text-[10px] font-medium">
              Collecting data (need &ge;10)
            </span>
          )}
        </div>
      </div>

      <div className="text-xs text-slate-500 leading-relaxed">
        <span className="text-sky-400">Ideal: </span>
        bars along the dashed diagonal (model prob &asymp; actual win rate).
        <span className="text-red-400"> Red: </span>model overconfident.
        <span className="text-emerald-400"> Green: </span>model underconfident.
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={chartData}
          margin={{ top: 5, right: 10, left: -10, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="bin_label"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            domain={[0, 100]}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            content={<CustomTooltip />}
            cursor={{ fill: "rgba(255, 255, 255, 0.05)" }}
            contentStyle={{ backgroundColor: "transparent", border: "none" }}
          />
          <ReferenceLine
            segment={[
              { x: perfectStart.x, y: perfectStart.y },
              { x: perfectEnd.x, y: perfectEnd.y },
            ]}
            stroke="#475569"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          <Bar dataKey="actualPct" radius={[3, 3, 0, 0]} maxBarSize={32}>
            {chartData.map((b, i) => (
              <Cell key={i} fill={barColor(b)} fillOpacity={0.7} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {data.reliability_ready && data.total_samples >= 30 && (
        <p className="text-[10px] text-slate-500 text-center">
          Calibration reliable — {data.total_samples} settled signals with Brier score {data.brier_score.toFixed(3)}.
          {data.brier_score < 0.15
            ? " Model is well-calibrated."
            : data.brier_score < 0.25
            ? " Model is adequately calibrated."
            : " Consider Platt scaling when 50+ samples available."}
        </p>
      )}
    </div>
  );
}
