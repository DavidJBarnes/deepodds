import type { ReactNode } from "react";

type VenueColor = "emerald" | "sky";

interface Props {
  mode: string;
  venueLabel: string;
  venueColor: VenueColor;
  enabled: boolean;
  openPositions: number;
  maxOpenPositions: number;
  hasKeysWarning?: string;
  children?: ReactNode;
}

const VENUE_CLASSES: Record<VenueColor, { pill: string; dot: string; bar: string }> = {
  emerald: {
    pill: "bg-emerald-500/20 text-emerald-400",
    dot: "bg-emerald-500",
    bar: "bg-emerald-500",
  },
  sky: {
    pill: "bg-sky-500/20 text-sky-400",
    dot: "bg-sky-500",
    bar: "bg-sky-500",
  },
};

export default function BotStatusBar({
  mode,
  venueLabel,
  venueColor,
  enabled,
  openPositions,
  maxOpenPositions,
  hasKeysWarning,
  children,
}: Props) {
  const posPct = maxOpenPositions > 0
    ? Math.min(100, (openPositions / maxOpenPositions) * 100)
    : 0;
  const v = VENUE_CLASSES[venueColor];
  const modePill = mode === "live"
    ? "bg-red-500/20 text-red-400"
    : "bg-amber-500/20 text-amber-400";

  let barColor = v.bar;
  if (posPct > 90) barColor = "bg-red-500";
  else if (posPct > 60) barColor = "bg-amber-500";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold px-2.5 py-1 rounded ${modePill}`}>
            {mode.toUpperCase()}
          </span>
          <span className={`text-xs font-bold px-2.5 py-1 rounded ${v.pill}`}>
            {venueLabel}
          </span>
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              enabled ? `${v.dot} animate-pulse` : "bg-slate-600"
            }`}
          />
          <span className="text-sm text-slate-400">
            {enabled ? "Running" : "Paused"}
          </span>
          {hasKeysWarning && (
            <span className="text-xs text-amber-400">{hasKeysWarning}</span>
          )}
        </div>

        <div className="h-4 w-px bg-slate-700" />

        <div className="flex-1 min-w-48">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>Positions</span>
            <span>{openPositions} / {maxOpenPositions}</span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${barColor}`}
              style={{ width: `${posPct}%` }}
            />
          </div>
        </div>

        {children && (
          <>
            <div className="h-4 w-px bg-slate-700" />
            <div className="flex gap-4 text-sm">{children}</div>
          </>
        )}
      </div>
    </div>
  );
}
