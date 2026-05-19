import { create } from "zustand";
import * as authApi from "@/api/auth";

interface AuthState {
  token: string | null;
  user: authApi.User | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  initialize: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem("token"),
  user: null,
  isAuthenticated: !!localStorage.getItem("token"),

  login: async (email, password) => {
    const { access_token } = await authApi.login(email, password);
    localStorage.setItem("token", access_token);
    set({ token: access_token, isAuthenticated: true });
    await get().fetchUser();
  },

  register: async (email, password) => {
    const { access_token } = await authApi.register(email, password);
    localStorage.setItem("token", access_token);
    set({ token: access_token, isAuthenticated: true });
    await get().fetchUser();
  },

  logout: () => {
    localStorage.removeItem("token");
    set({ token: null, user: null, isAuthenticated: false });
  },

  fetchUser: async () => {
    try {
      const user = await authApi.getMe();
      set({ user, isAuthenticated: true });
    } catch {
      get().logout();
    }
  },

  initialize: async () => {
    if (get().token) {
      await get().fetchUser();
    }
  },
}));
