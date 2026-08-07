import { NavLink } from "react-router-dom";

/** In-page tab strip for the Verbatim views.
 *
 * Replaces the standalone console's NavHeader. DeepOdds' sidebar is single-level
 * and already carries one "Verbatim" entry, so four more sidebar items would
 * misrepresent these as peers of Longshot and Edge Explorer. They are sub-views.
 */
const TABS = [
  { to: "/verbatim", label: "Live", end: true },
  { to: "/verbatim/history", label: "History", end: false },
  { to: "/verbatim/watchlist", label: "Watchlist", end: false },
];

export function VerbatimTabs() {
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 pb-2">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-emerald-600/20 text-emerald-400"
                : "text-slate-400 hover:bg-slate-800 hover:text-white"
            }`
          }
        >
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}
