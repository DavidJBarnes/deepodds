import { useEffect, useState } from "react";

interface Props {
  closeTime: string;
}

/** Real-time countdown to contract expiry, updates every second. */
export default function Countdown({ closeTime }: Props) {
  const [parts, setParts] = useState<{ h: number; m: number; s: number; expired: boolean }>({ h: 0, m: 0, s: 0, expired: false });

  useEffect(() => {
    function tick() {
      const diff = new Date(closeTime).getTime() - Date.now();
      if (diff <= 0) {
        setParts({ h: 0, m: 0, s: 0, expired: true });
        return;
      }
      const totalSeconds = Math.floor(diff / 1000);
      setParts({
        h: Math.floor(totalSeconds / 3600),
        m: Math.floor((totalSeconds % 3600) / 60),
        s: totalSeconds % 60,
        expired: false,
      });
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [closeTime]);

  if (parts.expired) {
    return <span className="text-red-400 text-xs font-medium">expired</span>;
  }

  const pad = (n: number) => String(n).padStart(2, "0");

  return (
    <span className="inline-flex gap-0.5 font-mono text-xs tabular-nums">
      <span className="bg-slate-800 text-slate-200 px-1 py-0.5 rounded">{pad(parts.h)}</span>
      <span className="text-slate-600">:</span>
      <span className="bg-slate-800 text-slate-200 px-1 py-0.5 rounded">{pad(parts.m)}</span>
      <span className="text-slate-600">:</span>
      <span className="bg-slate-800 text-slate-200 px-1 py-0.5 rounded">{pad(parts.s)}</span>
    </span>
  );
}
