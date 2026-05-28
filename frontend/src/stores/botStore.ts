import { create } from "zustand";
import * as botApi from "@/api/bot";

interface BotState {
  dashboard: botApi.DashboardData | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastRefreshed: Date | null;
  fetchDashboard: (venue?: string) => Promise<void>;
}

export const useBotStore = create<BotState>((set, get) => ({
  dashboard: null,
  loading: false,
  refreshing: false,
  error: null,
  lastRefreshed: null,

  fetchDashboard: async (venue = "all") => {
    const isFirst = !get().dashboard;
    set(isFirst ? { loading: true, error: null } : { refreshing: true, error: null });
    try {
      const data = await botApi.getDashboard(venue);
      set({ dashboard: data, loading: false, refreshing: false, lastRefreshed: new Date() });
    } catch {
      set({ error: "Failed to load dashboard", loading: false, refreshing: false });
    }
  },
}));
