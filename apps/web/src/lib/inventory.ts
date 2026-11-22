import { ApiError, apiRequest } from "./api-client";

export type Stock = {
  productId: string;
  onHandQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
  lowStockThreshold: number;
  version: number;
};
export type ProductLabel = {
  productId: string;
  name: string;
  sku: string;
  category: string;
};
export type Movement = {
  id: string;
  operationId: string;
  productId: string;
  movementType: string;
  onHandDelta: number;
  reservedDelta: number;
  onHandAfter: number;
  reservedAfter: number;
  reason: string;
  createdAt: string;
};
export type Page<T> = {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
};
export type StockCreate = { productId: string; lowStockThreshold: number };
export type StockAdjustment = {
  productId: string;
  delta: number;
  reason: string;
  expectedVersion: number;
};
export type InventoryQuery = {
  page: number;
  pageSize: number;
  lowStock?: boolean;
};
export type InventoryApi = {
  list(query: InventoryQuery, signal?: AbortSignal): Promise<Page<Stock>>;
  movements(
    productId: string,
    page: number,
    signal?: AbortSignal,
  ): Promise<Page<Movement>>;
  initialize(body: StockCreate, key: string): Promise<Stock>;
  adjust(body: StockAdjustment, key: string): Promise<Stock>;
};

export const MAX_INTEGER = 2_147_483_647;
export const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function stockResponse(value: Stock): Stock {
  const quantities = [
    value.onHandQuantity,
    value.reservedQuantity,
    value.availableQuantity,
    value.lowStockThreshold,
    value.version,
  ];
  if (
    !UUID_PATTERN.test(value.productId) ||
    quantities.some((n) => !Number.isInteger(n) || n < 0 || n > MAX_INTEGER) ||
    value.onHandQuantity - value.reservedQuantity !== value.availableQuantity
  ) {
    throw new ApiError(
      "Dữ liệu tồn kho không hợp lệ. Vui lòng tải lại.",
      "INVALID_RESPONSE",
      502,
    );
  }
  return value;
}

export function createInventoryApi(accessToken: string): InventoryApi {
  const headers = { Authorization: `Bearer ${accessToken}` };
  const root = "/admin/inventory";
  async function write(
    path: string,
    body: StockCreate | StockAdjustment,
    key: string,
  ) {
    return stockResponse(
      await apiRequest<Stock>(root + path, {
        method: "POST",
        headers: {
          ...headers,
          "Content-Type": "application/json",
          "Idempotency-Key": key,
        },
        body: JSON.stringify(body),
      }),
    );
  }
  return {
    async list(query, signal) {
      const params = new URLSearchParams({
        page: String(query.page),
        pageSize: String(query.pageSize),
      });
      if (query.lowStock !== undefined)
        params.set("lowStock", String(query.lowStock));
      const result = await apiRequest<Page<Stock>>(`${root}?${params}`, {
        headers,
        signal,
      });
      return { ...result, items: result.items.map(stockResponse) };
    },
    movements(productId, page, signal) {
      if (!UUID_PATTERN.test(productId)) throw new Error("Invalid product ID");
      return apiRequest<Page<Movement>>(
        `${root}/${productId}/movements?page=${page}&pageSize=10`,
        { headers, signal },
      );
    },
    initialize: (body, key) => write("/items", body, key),
    adjust: (body, key) => write("/adjustments", body, key),
  };
}

export type AdminAccount = {
  id: string;
  name?: string;
  email?: string;
  role: string;
  status: string;
};
export async function loginInventory(email: string, password: string) {
  const result = await apiRequest<{ accessToken: string }>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (typeof result.accessToken !== "string" || !result.accessToken) {
    throw new ApiError(
      "Không nhận được phiên đăng nhập hợp lệ.",
      "INVALID_RESPONSE",
      502,
    );
  }
  const user = await apiRequest<AdminAccount>("/users/me", {
    headers: { Authorization: `Bearer ${result.accessToken}` },
  });
  if (user.role !== "ADMIN" || user.status !== "ACTIVE") {
    throw new ApiError(
      "Tài khoản này không có quyền quản trị kho.",
      "FORBIDDEN",
      403,
    );
  }
  // Access tokens live only in React memory; never in localStorage or URLs.
  return { accessToken: result.accessToken, user };
}

export function inventoryError(error: unknown): string {
  if (!(error instanceof ApiError))
    return "Không thực hiện được thao tác. Vui lòng thử lại.";
  const messages: Record<string, string> = {
    STOCK_VERSION_CONFLICT:
      "Tồn kho đã thay đổi. Đóng cửa sổ, tải lại tồn và xác nhận điều chỉnh mới.",
    STOCK_CONFIGURATION_CONFLICT:
      "Sản phẩm đã có trong kho với ngưỡng cảnh báo khác.",
    INSUFFICIENT_STOCK:
      "Không thể giảm tồn xuống thấp hơn lượng hàng đang được giữ.",
    STOCK_LIMIT_EXCEEDED: "Số lượng vượt giới hạn cho phép.",
    IDEMPOTENCY_CONFLICT:
      "Nội dung yêu cầu đã thay đổi. Vui lòng đóng và thực hiện thao tác mới.",
    NOT_FOUND:
      "Không tìm thấy sản phẩm. Kiểm tra lại mã sản phẩm trong danh mục.",
    AUTH_INVALID:
      "Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
    SESSION_EXPIRED: "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
    FORBIDDEN: "Bạn không có quyền quản trị kho.",
    DEPENDENCY_UNAVAILABLE: "Dịch vụ chưa sẵn sàng. Vui lòng thử lại sau.",
  };
  if (error.status === 404 && error.code === "HTTP_ERROR")
    return "Chức năng đăng nhập chưa sẵn sàng. Vui lòng thử lại khi dịch vụ được kết nối.";
  return messages[error.code] ?? error.message;
}

export function unknownOutcome(error: unknown): boolean {
  return (
    error instanceof ApiError && (error.status === 0 || error.status >= 500)
  );
}

// A form owns one attempt. Ambiguous network failures must retry the same body/key.
export class InventoryAttempt {
  readonly key: string;
  constructor(
    readonly body: StockCreate | StockAdjustment,
    key = crypto.randomUUID(),
  ) {
    this.key = key;
  }
}
