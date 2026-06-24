import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import LoginPage from "@/pages/LoginPage";
// import RegisterPage from "@/pages/RegisterPage";  // registration disabled (single-tenant)
import LongshotPage from "@/pages/LongshotPage";

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
        <Route element={<Layout />}>
          <Route index element={<LongshotPage />} />
          <Route path="longshot" element={<LongshotPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
