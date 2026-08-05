import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

const navItems = [
  { to: "/", label: "Longshot Short" },
  { to: "/edge", label: "Edge Explorer" },
];

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [navOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Auto-collapse on navigation. Without this the drawer stays open over the page
  // you just tapped through to, which on a phone hides the whole thing.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // Escape closes, and focus returns to the button that opened it.
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setNavOpen(false);
        toggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? "bg-emerald-600/20 text-emerald-400"
        : "text-slate-400 hover:text-white hover:bg-slate-800"
    }`;

  return (
    // h-dvh, not h-screen: on mobile Safari/Chrome 100vh includes the collapsing URL
    // bar, so h-screen leaves the bottom of the page permanently cut off.
    <div className="h-dvh bg-slate-950 flex overflow-hidden">
      {/* Backdrop — mobile only, and only mounted while open so it can never
          swallow clicks on desktop. */}
      {navOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-40 bg-slate-950/70 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        id="main-nav"
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-slate-900 border-r border-slate-800
          flex flex-col shrink-0 transition-[transform,visibility] duration-200 ease-out
          pl-[env(safe-area-inset-left)]
          lg:static lg:z-auto lg:w-56 lg:translate-x-0 lg:visible ${
            navOpen ? "translate-x-0" : "-translate-x-full max-lg:invisible"
          }`}
      >
        <div className="px-4 py-5 border-b border-slate-800 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <img src="/favicon.svg" alt="" className="w-9 h-9 shrink-0" />
            <div className="flex flex-col -space-y-0.5 min-w-0">
              <span className="text-[15px] font-bold tracking-tight text-white leading-tight">
                Deep<span className="text-emerald-400">Odds</span>
              </span>
              <span className="text-[10px] font-medium uppercase tracking-[0.15em] text-slate-500 leading-tight">
                Trading Bot
              </span>
            </div>
          </div>
          {/* Close affordance inside the drawer — on a phone the backdrop is easy to
              miss, and there's no visible edge to swipe against. */}
          <button
            type="button"
            onClick={() => setNavOpen(false)}
            aria-label="Close navigation"
            className="lg:hidden -mr-1 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <svg viewBox="0 0 20 20" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={linkClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-slate-800 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <p className="text-xs text-slate-500 truncate mb-2">{user?.email}</p>
          <button
            onClick={logout}
            className="text-sm text-slate-400 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar — the only way to reach the nav once it's collapsed. */}
        <header className="lg:hidden shrink-0 flex items-center gap-3 px-3 h-14 bg-slate-900 border-b border-slate-800 pt-[env(safe-area-inset-top)]">
          <button
            ref={toggleRef}
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls="main-nav"
            className="p-2 -ml-1 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <svg viewBox="0 0 20 20" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M3 5.5h14M3 10h14M3 14.5h14" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-2 min-w-0">
            <img src="/favicon.svg" alt="" className="w-6 h-6 shrink-0" />
            <span className="text-sm font-bold tracking-tight text-white truncate">
              Deep<span className="text-emerald-400">Odds</span>
            </span>
          </div>
        </header>

        <main className="flex-1 overflow-auto overscroll-contain">
          <div className="max-w-6xl mx-auto p-4 sm:p-6 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
