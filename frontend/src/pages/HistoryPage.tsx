import { useEffect, useState } from "react";
import { getHistory, type HistoryEntry } from "@/api/bot";

export default function HistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getHistory({ limit: 100 })
      .then((data) => {
        if (!cancelled) setEntries(data.items);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white">History</h2>

      {loading ? (
        <p className="text-slate-400">Loading...</p>
      ) : entries.length === 0 ? (
        <p className="text-slate-400">No history entries yet.</p>
      ) : (
        <div className="space-y-2">
          {entries.map((e) => (
            <div key={e.id} className="bg-slate-900 border border-slate-800 rounded-xl px-5 py-3">
              <p className="text-sm text-white">{e.text}</p>
              <p className="text-xs text-slate-500 mt-1">
                {new Date(e.created_at).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
