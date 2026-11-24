import { ApiError, apiRequest } from "../api-client";

export type AuthUser = {
  id: string;
  email: string;
  fullName: string;
  role: "CUSTOMER" | "ADMIN";
  status: "ACTIVE" | "DISABLED";
};

export type TokenResponse = { accessToken: string; expiresIn: number; user: AuthUser };
export type SessionStatus = "unknown" | "authenticated" | "anonymous";
// The access token is deliberately not part of the observable state.
export type SessionState = { status: SessionStatus; user: AuthUser | null };

type RequestOptions = Omit<RequestInit, "signal"> & { signal?: AbortSignal; timeoutMs?: number };
export type Requester = <T>(path: string, options?: RequestOptions) => Promise<T>;
export type RefreshLock = <T>(task: () => Promise<T>) => Promise<T>;

export type SessionOptions = {
  request?: Requester;
  now?: () => number;
  /** Refresh this long before the access token expires. */
  refreshSkewMs?: number;
  /** Serializes refresh across browser tabs; defaults to the Web Locks API when present. */
  lock?: RefreshLock;
};

const REFRESH_LOCK_NAME = "commerce-auth-refresh";
// 401/403 on refresh mean the refresh session is gone (expired, revoked, reused, disabled, bad origin).
const SESSION_ENDED = new Set([401, 403]);

function isSessionEnded(error: unknown): error is ApiError {
  return error instanceof ApiError && SESSION_ENDED.has(error.status);
}

function defaultLock(): RefreshLock {
  return async <T>(task: () => Promise<T>) => {
    const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
    if (!locks) return task();
    return (await locks.request(REFRESH_LOCK_NAME, task)) as T;
  };
}

/**
 * Framework-agnostic session core. Create one instance per browser client (never a module-level
 * singleton: on the server it would be shared between users). The access token lives only in this
 * closure; the refresh token is an HttpOnly cookie the browser sends on its own.
 */
export function createSessionManager(options: SessionOptions = {}) {
  const request: Requester = options.request ?? apiRequest;
  const now = options.now ?? Date.now;
  const skewMs = options.refreshSkewMs ?? 30_000;
  const lock = options.lock ?? defaultLock();

  let state: SessionState = { status: "unknown", user: null };
  let accessToken: string | null = null;
  let expiresAt = 0;
  // Bumped by login/logout so a refresh that started earlier cannot overwrite the newer outcome.
  let epoch = 0;
  let inflight: Promise<void> | null = null;
  const listeners = new Set<() => void>();

  function emit() {
    for (const listener of [...listeners]) listener();
  }

  function setSession(token: TokenResponse) {
    accessToken = token.accessToken;
    expiresAt = now() + token.expiresIn * 1000;
    state = { status: "authenticated", user: token.user };
    emit();
  }

  function clearSession() {
    accessToken = null;
    expiresAt = 0;
    if (state.status === "anonymous") return;
    state = { status: "anonymous", user: null };
    emit();
  }

  // Single-flight: the backend rotates the refresh token without a grace window (IDN-07), so two
  // parallel refreshes would look like token reuse and revoke the whole family.
  function refresh(): Promise<void> {
    if (inflight) return inflight;
    const startedEpoch = epoch;
    const run = lock(async () => {
      try {
        const token = await request<TokenResponse>("/auth/refresh", { method: "POST" });
        if (epoch === startedEpoch) setSession(token);
      } catch (error) {
        if (isSessionEnded(error) && epoch === startedEpoch) clearSession();
        throw error;
      }
    });
    const tracked: Promise<void> = run.finally(() => {
      if (inflight === tracked) inflight = null;
    });
    inflight = tracked;
    return tracked;
  }

  async function restore(): Promise<SessionState> {
    try {
      await refresh();
    } catch (error) {
      // Network/5xx: leave the state as is so the UI can offer a retry instead of a false logout.
      if (!isSessionEnded(error)) throw error;
    }
    return state;
  }

  async function getAccessToken(): Promise<string | null> {
    if (accessToken === null) return null;
    if (now() < expiresAt - skewMs) return accessToken;
    try {
      await refresh();
    } catch (error) {
      if (isSessionEnded(error)) return null;
      if (accessToken !== null && now() < expiresAt) return accessToken;
      throw error;
    }
    return accessToken;
  }

  function send<T>(path: string, init: RequestOptions, token: string): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return request<T>(path, { ...init, headers });
  }

  async function authorizedRequest<T>(path: string, init: RequestOptions = {}): Promise<T> {
    const used = await getAccessToken();
    if (used === null) throw new ApiError("Cần đăng nhập để tiếp tục.", "AUTH_REQUIRED", 401);
    try {
      return await send<T>(path, init, used);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      // Another caller may already have refreshed while this request was in flight.
      if (accessToken === used) {
        try {
          await refresh();
        } catch (refreshError) {
          throw isSessionEnded(refreshError) ? error : refreshError;
        }
      }
      if (accessToken === null) throw error;
      return send<T>(path, init, accessToken); // exactly one retry
    }
  }

  async function login(email: string, password: string): Promise<AuthUser> {
    epoch += 1;
    const token = await request<TokenResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setSession(token);
    return token.user;
  }

  // Register only creates the account (201 User); the user then logs in (UC-ID-01).
  function register(email: string, fullName: string, password: string): Promise<AuthUser> {
    return request<AuthUser>("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, fullName, password }),
    });
  }

  async function logout(): Promise<void> {
    epoch += 1;
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } finally {
      // Local state is cleared even if the server call failed; the error still reaches the caller.
      clearSession();
    }
  }

  return {
    getState: (): SessionState => state,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    restore,
    login,
    register,
    logout,
    getAccessToken,
    authorizedRequest,
  };
}

export type SessionManager = ReturnType<typeof createSessionManager>;
