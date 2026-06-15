"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  type AuthResponse,
  type AuthUser,
  type Tenant,
  clearToken,
  fetchMe,
  getToken,
  login as apiLogin,
  setToken,
  signup as apiSignup,
} from "@/lib/api";

type AuthState = {
  user: AuthUser | null;
  tenant: Tenant | null;
  loading: boolean;
};

type AuthContextValue = AuthState & {
  login: (email: string, password: string) => Promise<void>;
  signup: (payload: {
    email: string;
    password: string;
    full_name?: string;
    company_name?: string;
  }) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    tenant: null,
    loading: true,
  });

  const applyAuth = useCallback((response: AuthResponse) => {
    setToken(response.access_token);
    setState({ user: response.user, tenant: response.tenant, loading: false });
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setState({ user: null, tenant: null, loading: false });
  }, []);

  // Restore the session from a stored token on first load.
  useEffect(() => {
    let active = true;
    const token = getToken();
    if (!token) {
      // Defer to a microtask so we don't setState synchronously in the effect.
      void Promise.resolve().then(() => {
        if (active) setState({ user: null, tenant: null, loading: false });
      });
      return () => {
        active = false;
      };
    }
    fetchMe()
      .then((me) => {
        if (!active) return;
        const { tenant, ...user } = me;
        setState({ user, tenant, loading: false });
      })
      .catch(() => {
        if (!active) return;
        clearToken();
        setState({ user: null, tenant: null, loading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      applyAuth(await apiLogin({ email, password }));
    },
    [applyAuth],
  );

  const signup = useCallback(
    async (payload: {
      email: string;
      password: string;
      full_name?: string;
      company_name?: string;
    }) => {
      applyAuth(await apiSignup(payload));
    },
    [applyAuth],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, signup, logout }),
    [state, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
