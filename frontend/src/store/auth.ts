import { create } from "zustand";

const KEY = "clothing_token";

type AuthState = {
  token: string | null;
  setToken: (t: string) => void;
  clear: () => void;
};

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem(KEY),
  setToken: (t) => {
    localStorage.setItem(KEY, t);
    set({ token: t });
  },
  clear: () => {
    localStorage.removeItem(KEY);
    set({ token: null });
  },
}));
