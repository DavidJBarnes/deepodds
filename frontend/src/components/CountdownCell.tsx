import { useEffect, useState } from "react";

function formatCountdown(ms: number): string {
  if (ms <= 0) return "Expired";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatSettledAt(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CountdownCell({
  target,
  status,
  resolvedAt,
}: {
  target: string | null;
  status?: string;
  resolvedAt?: string | null;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!target) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [target]);

  if (!target) return <span className="text-slate-600">—</span>;

  if (status?.startsWith("settled_") && resolvedAt) {
    return <span className="text-slate-400 text-xs">{formatSettledAt(resolvedAt)}</span>;
  }

  if (status?.startsWith("settled_")) return null;

  const t = new Date(target).getTime();
  const diff = t - now;

  if (diff <= 0) return <span className="text-slate-500 text-xs">Expired</span>;

  return (
    <span className="tabular-nums text-slate-300">
      {formatCountdown(diff)}
    </span>
  );
}
