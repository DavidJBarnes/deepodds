import { NavLink, Outlet } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

const navItems = [
  { to: "/", label: "Funding Carry" },
  { to: "/longshot", label: "Longshot Short" },
];

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

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
