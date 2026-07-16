import { useEffect, useState } from "react";
import {
  getExplorerDigest,
  getExplorerLedger,
  type ExplorerDigest,
  type Observation,
} from "@/api/bot";
import { formatAgo } from "@/utils/date";

const REFRESH_MS = 30_000;

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1 text-white">{value}</p>
    </div>
  );
}

function kindStyle(kind: string): { label: string; cls: string } {
  switch (kind) {
    case "structural":
      return { label: "structural", cls: "bg-sky-600/20 text-sky-400 border-sky-800" };
    case "deviation":
      return { label: "deviation", cls: "bg-amber-600/20 text-amber-400 border-amber-800" };
    case "data_quality":
      return { label: "data quality", cls: "bg-slate-600/30 text-slate-300 border-slate-700" };
    default:
      return { label: kind, cls: "bg-slate-600/30 text-slate-300 border-slate-700" };
  }
}

function statusStyle(status: string): string {
  switch (status) {
    case "investigate":
      return "bg-amber-600/20 text-amber-400";
    case "edge-candidate":
      return "bg-emerald-600/20 text-emerald-400";
    case "resolved":
      return "bg-emerald-600/20 text-emerald-400";
    case "dead":
      return "bg-red-600/20 text-red-400";
    case "structural-known":
      return "bg-slate-600/30 text-slate-400";
    default:
      return "bg-slate-700/40 text-slate-400";
  }
}

function ObservationCard({ o }: { o: Observation }) {
  const k = kindStyle(o.kind);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${k.cls}`}>{k.label}</span>
        <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-semibold ${statusStyle(o.status)}`}>{o.status}</span>
        {o.streak > 1 && (
          <span className="inline-flex rounded px-1.5 py-0.5 text-xs font-semibold bg-emerald-600/20 text-emerald-400">
            {o.streak}-day streak
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-slate-600">{o.metric_key}</span>
      </div>
      <p className="text-sm font-semibold text-white leading-snug">{o.what}</p>
      <div className="space-y-1.5 text-sm">
        <p className="text-slate-400"><span className="text-slate-500">Why it matters — </span>{o.why_notable}</p>
        <p className="text-slate-300"><span className="text-slate-500">Next — </span>{o.next_step}</p>
        <p className="text-slate-500 text-xs"><span className="uppercase tracking-wide">Caveat</span> · {o.caveat}</p>
      </div>
    </div>
  );
}

function LedgerTable({ rows }: { rows: Observation[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">Observation ledger</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2 font-medium">Date</th>
              <th className="px-4 py-2 font-medium">Observation</th>
              <th className="px-4 py-2 font-medium text-center">Status</th>
              <th className="px-4 py-2 font-medium text-right">Streak</th>
              <th className="px-4 py-2 font-medium text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? rows.map((o) => (
              <tr key={o.id} className="border-t border-slate-800 align-top">
                <td className="px-4 py-2 text-slate-400 whitespace-nowrap">{o.date ?? "—"}</td>
                <td className="px-4 py-2 text-slate-300">
                  {o.what}
                  {o.resolution_note && (
                    <span className="block mt-1 text-xs text-emerald-400/80"><span className="font-semibold">Verdict · </span>{o.resolution_note}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-center">
                  <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-semibold ${statusStyle(o.status)}`}>{o.status}</span>
                </td>
                <td className="px-4 py-2 text-right text-slate-400">{o.streak}</td>
                <td className="px-4 py-2 text-right text-slate-400">{o.score?.toFixed(1)}</td>
              </tr>
            )) : (
              <tr className="border-t border-slate-800">
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">No observations logged yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function EdgeExplorerPage() {
  const [digest, setDigest] = useState<ExplorerDigest | null>(null);
  const [ledger, setLedger] = useState<Observation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      getExplorerDigest()
        .then((d) => {
          if (!active) return;
          setDigest(d);
          setError(null);
        })
        .catch(() => active && setError("Failed to load explorer digest"))
        .finally(() => active && setLoading(false));
      getExplorerLedger()
        .then((d) => active && setLedger(d.observations))
        .catch(() => active && setLedger([]));
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  if (loading && !digest) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500 text-sm">Loading Edge Explorer…</p>
      </div>
    );
  }

  const obs = digest?.observations ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-bold text-white">Edge Explorer</h1>
        <span className="text-sm text-slate-500">observations worth investigating · not signals</span>
        {digest?.generated_ts && (
          <span className="ml-auto text-xs text-slate-500">updated {formatAgo(new Date(digest.generated_ts).getTime() / 1000)}</span>
        )}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="As of" value={digest?.date ?? "—"} />
        <StatCard label="Metrics scanned" value={String(digest?.n_metrics ?? 0)} />
        <StatCard label="Observations" value={String(digest?.n_observations ?? 0)} />
        <StatCard label="Ledger size" value={String(ledger.length)} />
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-bold text-white">Today · ranked by surprise × persistence</h2>
        {obs.length > 0 ? (
          <div className="grid grid-cols-1 gap-4">
            {obs.map((o) => <ObservationCard key={o.id} o={o} />)}
          </div>
        ) : (
          <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-6 text-center text-slate-500 text-sm">
            Nothing notable today — a quiet market is a valid result.
          </div>
        )}
      </section>

      <section className="space-y-4 border-t border-slate-800 pt-6">
        <LedgerTable rows={ledger} />
      </section>
    </div>
  );
}
