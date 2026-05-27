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

export default function CountdownCell({ target }: { target: string | null }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!target) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [target]);

  if (!target) return <span className="text-slate-600">—</span>;

  const t = new Date(target).getTime();
  const diff = t - now;

  if (diff <= 0) return <span className="text-red-400 text-xs">Expired</span>;

  return (
    <span className="tabular-nums text-slate-300">
      {formatCountdown(diff)}
    </span>
  );
}
