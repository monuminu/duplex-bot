"use client";

// Same-origin by default: in the single-container deployment the SPA is served
// by FastAPI, so an empty base means requests go to the same host. For split
// local dev, set NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8000.
export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_API_URL || "";
}

const TOKEN_KEY = "duplex_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${apiBaseUrl()}${path}`, { ...init, headers });

  if (response.status === 401) {
    // Token invalid/expired — drop it so the UI redirects to login.
    clearToken();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = data?.detail || message;
    } catch {
      const text = await response.text();
      if (text) message = text;
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ── Auth types + calls ───────────────────────────────────────────────

export type Tenant = { id: string; name: string; slug: string };
export type AuthUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  tenant_id: string;
};
export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
  tenant: Tenant;
};
export type MeResponse = AuthUser & { tenant: Tenant };

export function signup(payload: {
  email: string;
  password: string;
  full_name?: string;
  company_name?: string;
}) {
  return apiFetch<AuthResponse>("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function login(payload: { email: string; password: string }) {
  return apiFetch<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchMe() {
  return apiFetch<MeResponse>("/api/auth/me");
}

export function fetchAuthConfig() {
  return apiFetch<{ allow_signup: boolean }>("/api/auth/config");
}
