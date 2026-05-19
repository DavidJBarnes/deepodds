import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useBotStore } from "@/stores/botStore";
import { getKalshiBalance, type KalshiBalance } from "@/api/settings";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/settings", label: "Settings" },
  { to: "/resources", label: "Resources" },
];

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const dashboard = useBotStore((s) => s.dashboard);
  const status = dashboard?.bot_status;
  const [balance, setBalance] = useState<KalshiBalance | null>(null);

  useEffect(() => {
    getKalshiBalance().then(setBalance).catch(() => {});
    const id = setInterval(() => getKalshiBalance().then(setBalance).catch(() => {}), 60000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="h-screen bg-slate-950 flex overflow-hidden">
      <aside className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="DeepOdds" className="w-9 h-9 shrink-0" />
            <div className="flex flex-col -space-y-0.5">
              <span className="text-[15px] font-bold tracking-tight text-white leading-tight">Deep<span className="text-emerald-400">Odds</span></span>
              <span className="text-[10px] font-medium uppercase tracking-[0.15em] text-slate-500 leading-tight">Trading Bot</span>
            </div>
          </div>
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
        {balance && (balance.cash_cents > 0 || balance.portfolio_cents > 0) && (
          <div className="px-4 py-3 border-t border-slate-800 space-y-1">
            <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">Kalshi Account</p>
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Cash</span>
              <span className="text-white font-medium">${(balance.cash_cents / 100).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Portfolio</span>
              <span className="text-emerald-400 font-medium">${(balance.portfolio_cents / 100).toFixed(2)}</span>
            </div>
          </div>
        )}
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
