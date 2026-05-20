import { create } from "zustand";
import * as botApi from "@/api/bot";

interface BotState {
  dashboard: botApi.DashboardData | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastRefreshed: Date | null;
  spotPrice: number | null;
  spotHigh1h: number | null;
  spotDipPct: number | null;
  spotTrades: botApi.SpotTrade[];
  spotPosition: botApi.SpotPosition | null;
  fetchDashboard: () => Promise<void>;
  fetchSpotData: () => Promise<void>;
  startPriceStream: () => () => void;
}

export const useBotStore = create<BotState>((set, get) => ({
  dashboard: null,
  loading: false,
  refreshing: false,
  error: null,
  lastRefreshed: null,
  spotPrice: null,
  spotHigh1h: null,
  spotDipPct: null,
  spotTrades: [],
  spotPosition: null,

  fetchDashboard: async () => {
    const isFirst = !get().dashboard;
    set(isFirst ? { loading: true, error: null } : { refreshing: true, error: null });
    try {
      const data = await botApi.getDashboard();
      set({ dashboard: data, loading: false, refreshing: false, lastRefreshed: new Date() });
    } catch {
      set({ error: "Failed to load dashboard", loading: false, refreshing: false });
    }
  },

  fetchSpotData: async () => {
    try {
      const [trades, position] = await Promise.all([
        botApi.getSpotTrades(),
        botApi.getSpotPosition(),
      ]);
      set({ spotTrades: trades, spotPosition: position });
    } catch {
      // silent
    }
  },

  startPriceStream: () => {
    const baseUrl = import.meta.env.VITE_API_URL || "";
    const url = `${baseUrl}/api/v1/spot/price/stream`;
    const es = new EventSource(url, { withCredentials: false } as EventSourceInit);

    // For auth, we'll fall back to polling if SSE doesn't support auth headers
    // Instead use the REST endpoint
    const interval = setInterval(async () => {
      try {
        const data = await botApi.getSpotPrice();
        set({
          spotPrice: data.price,
          spotHigh1h: data.high_1h,
          spotDipPct: data.dip_pct,
        });
      } catch {
        // silent
      }
    }, 2000);

    es.close();

    return () => {
      clearInterval(interval);
    };
  },
}));
