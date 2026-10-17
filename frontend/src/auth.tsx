import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, post, setToken, setUnauthorizedHandler, User } from "./api";

interface AuthState {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}
const Ctx = createContext<AuthState>({ user: null, login: async () => {}, logout: () => {} });
export const useAuth = () => useContext(Ctx);

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem("clinic_user");
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(loadUser);

  const logout = useCallback(() => {
    setToken(null);
    try { localStorage.removeItem("clinic_user"); } catch { /* ignore */ }
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await post<{ access_token: string; user: User }>("/auth/login", { email, password });
    setToken(res.access_token);
    try { localStorage.setItem("clinic_user", JSON.stringify(res.user)); } catch { /* ignore */ }
    setUser(res.user);
  }, []);

  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>;
}

export { api };
