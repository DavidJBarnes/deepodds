import { NavLink, Outlet } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useBotStore } from "@/stores/botStore";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const dashboard = useBotStore((s) => s.dashboard);
  const status = dashboard?.bot_status;

  return (
    <div className="min-h-screen bg-slate-950 flex">
      <aside className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-xl font-bold text-emerald-400">DeepOdds</h1>
          {status && (
            <div className="flex items-center gap-2 mt-2">
              <span
                className={`text-xs font-bold px-2 py-0.5 rounded ${
                  status.mode === "live"
                    ? "bg-red-500/20 text-red-400"
                    : "bg-amber-500/20 text-amber-400"
                }`}
              >
                {status.mode.toUpperCase()}
              </span>
              <span
                className={`w-2 h-2 rounded-full ${
                  status.enabled ? "bg-emerald-500" : "bg-slate-600"
                }`}
              />
            </div>
          )}
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-emerald-600/20 text-emerald-400"
                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800">
          <p className="text-xs text-slate-500 truncate mb-2">{user?.email}</p>
          <button
            onClick={logout}
            className="text-sm text-slate-400 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
