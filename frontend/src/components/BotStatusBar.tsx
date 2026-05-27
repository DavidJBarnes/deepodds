import type { ReactNode } from "react";

interface Props {
  mode: string;
  enabled: boolean;
  openPositions: number;
  maxOpenPositions: number;
  hasKeysWarning?: string;
  children?: ReactNode;
}

export default function BotStatusBar({
  mode,
  enabled,
  openPositions,
  maxOpenPositions,
  hasKeysWarning,
  children,
}: Props) {
  const posPct = maxOpenPositions > 0
    ? Math.min(100, (openPositions / maxOpenPositions) * 100)
    : 0;

  let barColor = "bg-sky-500";
  if (posPct > 90) barColor = "bg-red-500";
  else if (posPct > 60) barColor = "bg-amber-500";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              enabled ? "bg-sky-500 animate-pulse" : "bg-slate-600"
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
