export type ApiErrorEnvelope = {
  code: string;
  message: string;
  requestId: string;
  details?: unknown;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
    readonly requestId?: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  return "code" in value && typeof value.code === "string" &&
    "message" in value && typeof value.message === "string" &&
    "requestId" in value && typeof value.requestId === "string";
}

type RequestOptions = Omit<RequestInit, "signal"> & {
  signal?: AbortSignal;
  timeoutMs?: number;
};

// Relative browser base only. Server Components should use an explicit server-side client.
export function createApiClient(baseUrl = "/api/v1") {
  if (!/^\/api\/v1(?:\/[a-zA-Z0-9_-]+)*$/.test(baseUrl)) {
    throw new Error("API base must be a relative /api/v1 path");
  }
  return async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
    // Reject URL escapes, traversal and fragments; queries remain supported.
    const pathname = path.split("?")[0];
    if (!/^\/(?:[a-zA-Z0-9_-]+\/?)*$/.test(pathname) || path.includes("#")) {
      throw new Error("API path must be relative to the configured base");
    }
    const { timeoutMs = 8_000, signal, ...init } = options;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("Invalid API timeout");
    const controller = new AbortController();
    let timedOut = false;
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    let requestId: string | undefined;
    try {
      const response = await fetch(`${baseUrl}${path}`, {
        ...init, headers, signal: controller.signal, cache: "no-store", credentials: "same-origin",
      });
      requestId = response.headers.get("X-Request-Id") ?? undefined;
      const body: unknown = await response.json().catch(() => undefined);
      if (controller.signal.aborted) throw new Error("Aborted response body");
      if (!response.ok) {
        if (isEnvelope(body)) {
          throw new ApiError(body.message, body.code, response.status, body.requestId || requestId, body.details);
        }
        throw new ApiError("Yêu cầu thất bại. Vui lòng thử lại.", "HTTP_ERROR", response.status, requestId);
      }
      if (response.status === 204) return undefined as T;
      if (body === undefined) throw new ApiError("Phản hồi không đúng định dạng JSON.", "INVALID_RESPONSE", response.status, requestId);
      return body as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (signal?.aborted) throw new ApiError("Đã hủy yêu cầu.", "REQUEST_ABORTED", 0, requestId);
      if (timedOut) throw new ApiError("Kết nối quá thời gian chờ. Vui lòng thử lại.", "REQUEST_TIMEOUT", 0, requestId);
      throw new ApiError("Không kết nối được hệ thống. Kiểm tra frontend và gateway.", "NETWORK_ERROR", 0, requestId);
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", cancel);
    }
  };
}

export const apiRequest = createApiClient();
