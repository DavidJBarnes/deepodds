import { useCallback, useEffect, useState } from "react";
import { useBotStore } from "@/stores/botStore";
import StatsCard from "@/components/StatsCard";
import PnLChart from "@/components/PnLChart";
import CalibrationChart from "@/components/CalibrationChart";
import RefreshBar from "@/components/RefreshBar";

const REFRESH_INTERVAL = 30;

export default function DashboardPage() {
  const { dashboard, loading, refreshing, lastRefreshed, fetchDashboard } = useBotStore();
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);

  const refresh = useCallback(() => {
    setCountdown(REFRESH_INTERVAL);
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    const tick = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          fetchDashboard();
          return REFRESH_INTERVAL;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  }, [fetchDashboard]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!dashboard && loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-400">Loading dashboard...</p>
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-red-400">Failed to load dashboard</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <RefreshBar
        refreshing={refreshing}
        lastRefreshed={lastRefreshed}
        countdown={countdown}
        onRefresh={refresh}
        scannerHealth={dashboard.scanner_health}
      />

      <StatsCard stats={dashboard.stats} />
      <PnLChart refreshKey={lastRefreshed?.getTime() ?? undefined} />
      <CalibrationChart refreshKey={lastRefreshed?.getTime() ?? undefined} />
    </div>
  );
}
