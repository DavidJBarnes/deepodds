import { Suspense, lazy, useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import VerbatimLayout from "@/components/verbatim/VerbatimLayout";
import LoginPage from "@/pages/LoginPage";
// import RegisterPage from "@/pages/RegisterPage";  // registration disabled (single-tenant)

// Every route is lazy, not just the new ones. The bundle was already 682KB —
// recharts-dominated — and adding four Verbatim pages to a single chunk would
// make every visitor download the charting library and the speech console just to
// look at Longshot. Split so each tab pays only for itself.
const LongshotPage = lazy(() => import("@/pages/LongshotPage"));
const EdgeExplorerPage = lazy(() => import("@/pages/EdgeExplorerPage"));
const VerbatimLivePage = lazy(() => import("@/pages/verbatim/LivePage"));
const VerbatimHistoryPage = lazy(() => import("@/pages/verbatim/HistoryPage"));
const VerbatimWatchlistPage = lazy(() => import("@/pages/verbatim/WatchlistPage"));
const VerbatimDetectionDetailPage = lazy(
  () => import("@/pages/verbatim/DetectionDetailPage"),
);

function RouteFallback() {
  return (
    <div className="flex items-center justify-center h-64">
      <p className="text-slate-500 text-sm">Loading…</p>
    </div>
  );
}

export default function App() {
  const initialize = useAuthStore((s) => s.initialize);

  useEffect(() => {
    initialize();
  }, [initialize]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* registration disabled (single-tenant) — re-enable with multi-tenant work
      <Route path="/register" element={<RegisterPage />} /> */}
      <Route element={<ProtectedRoute />}>
        <Route
          element={
            <Suspense fallback={<RouteFallback />}>
              <Layout />
            </Suspense>
          }
        >
          <Route index element={<LongshotPage />} />
          <Route path="longshot" element={<LongshotPage />} />
          <Route path="edge" element={<EdgeExplorerPage />} />
          <Route path="verbatim" element={<VerbatimLayout />}>
            <Route index element={<VerbatimLivePage />} />
            <Route path="history" element={<VerbatimHistoryPage />} />
            <Route path="watchlist" element={<VerbatimWatchlistPage />} />
            <Route path="detections/:id" element={<VerbatimDetectionDetailPage />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}
