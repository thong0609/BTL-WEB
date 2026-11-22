import { ApiError, apiRequest } from "./api-client";

export const statusLabels = {
  PROCESSING: "Đang xử lý", AWAITING_CONFIRMATION: "Chờ xác nhận", PREPARING: "Chuẩn bị hàng",
  SHIPPING: "Đang giao", COMPLETED: "Hoàn thành", CANCELLING: "Đang hủy", CANCELLED: "Đã hủy", REJECTED: "Từ chối",
} as const;
export type OrderStatus = keyof typeof statusLabels;
export const actionLabels = { CONFIRM: "Xác nhận đơn", CANCEL: "Hủy đơn", DISPATCH: "Bàn giao vận chuyển", COMPLETE: "Hoàn thành đơn", RECORD_EXCEPTION: "Ghi nhận giao lỗi" } as const;
export type OrderAction = keyof typeof actionLabels;
export type CartItem = { productId: string; quantity: number };
export type QuoteItem = CartItem & { sku: string; name: string; unitPriceAmount: string; lineTotalAmount: string; catalogVersion: number };
export type Quote = { items: QuoteItem[]; subtotalAmount: string; shippingFeeAmount: string; totalAmount: string; currency: "VND"; quotedAt: string };
export type Recipient = { name: string; phone: string; address: string };
export type CreateOrder = { items: (CartItem & { expectedUnitPriceAmount: string; expectedCatalogVersion: number })[]; expectedShippingFeeAmount: string; recipient: Recipient; paymentMethod: "COD" | "SIMULATED"; note: string };
export type OrderSummary = { id: string; orderNumber: string; status: OrderStatus; paymentStatus: string | null; totalAmount: string; currency: "VND"; createdAt: string };
export type OrderPage = { items: OrderSummary[]; page: number; pageSize: number; total: number };
export type Order = Omit<Quote, "quotedAt"> & OrderSummary & {
  customerId: string; paymentMethod: "COD" | "SIMULATED"; paymentId: string | null; recipient: Recipient; note: string | null;
  workflow: { phase: string; state: string; requiresAttention: boolean };
  history: { fromStatus: OrderStatus | null; toStatus: OrderStatus; reason: string | null; createdAt: string }[];
  allowedActions: OrderAction[];
};
export type Accepted = { orderId: string; orderNumber: string; status: OrderStatus };
export type ActionResult = { orderId: string; status: OrderStatus; workflowState: string };
export const paymentLabels: Record<string, string> = { PENDING: "Đang xử lý", AWAITING_COLLECTION: "Chờ thu khi giao", SUCCEEDED: "Đã thanh toán", FAILED: "Thanh toán thất bại", REFUND_PENDING: "Đang hoàn tiền", REFUNDED: "Đã hoàn tiền", CANCELLED: "Đã hủy khoản thu" };
export const isUuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
function invalid(): never { throw new ApiError("Dữ liệu đơn hàng không hợp lệ. Vui lòng thử tải lại.", "INVALID_RESPONSE", 502); }
export function object(v: unknown): Record<string, unknown> { if (!v || typeof v !== "object" || Array.isArray(v)) return invalid(); return v as Record<string, unknown>; }
function text(v: unknown): v is string { return typeof v === "string"; }
function integer(v: unknown, min = 0): v is number { return typeof v === "number" && Number.isSafeInteger(v) && v >= min; }
function date(v: unknown): boolean { return text(v) && !Number.isNaN(Date.parse(v)); }
function money(v: unknown): v is string { return text(v) && /^[0-9]+$/.test(v) && BigInt(v) <= BigInt("9223372036854775807"); }
function status(v: unknown): v is OrderStatus { return text(v) && Object.hasOwn(statusLabels, v); }
function payment(v: unknown): boolean { return v === null || (text(v) && Object.hasOwn(paymentLabels, v)); }
export function parseCart(v: unknown): CartItem[] {
  if (!Array.isArray(v) || v.length > 50) return invalid();
  const ids = new Set<string>();
  return v.map((raw) => {
    const row = object(raw);
    if (!isUuid(row.productId) || !integer(row.quantity, 1) || row.quantity > 999 || ids.has(row.productId)) return invalid();
    ids.add(row.productId);
    return { productId: row.productId, quantity: row.quantity };
  });
}
function priced(v: unknown) {
  const row = object(v);
  if (!Array.isArray(row.items) || !row.items.length) return invalid();
  parseCart(row.items);
  let sum = BigInt(0);
  const skus = new Set<string>();
  for (const raw of row.items) {
    const item = object(raw);
    if (!text(item.sku) || skus.has(item.sku) || !text(item.name) || !money(item.unitPriceAmount) || !money(item.lineTotalAmount) || !integer(item.catalogVersion)) return invalid();
    skus.add(item.sku);
    if (BigInt(item.unitPriceAmount) * BigInt(item.quantity as number) !== BigInt(item.lineTotalAmount)) return invalid();
    sum += BigInt(item.lineTotalAmount);
  }
  if (!money(row.subtotalAmount) || !money(row.shippingFeeAmount) || !money(row.totalAmount) || row.currency !== "VND" || sum !== BigInt(row.subtotalAmount) || sum + BigInt(row.shippingFeeAmount) !== BigInt(row.totalAmount)) return invalid();
  return row;
}
export function parseQuote(v: unknown): Quote { const row = priced(v); if (!date(row.quotedAt)) return invalid(); return row as Quote; }
function summary(v: unknown): OrderSummary {
  const row = object(v);
  if (!isUuid(row.id) || !text(row.orderNumber) || !status(row.status) || !payment(row.paymentStatus) || !money(row.totalAmount) || row.currency !== "VND" || !date(row.createdAt)) return invalid();
  return row as OrderSummary;
}
export function parsePage(v: unknown): OrderPage {
  const row = object(v);
  if (!Array.isArray(row.items) || !integer(row.page, 1) || !integer(row.pageSize, 1) || row.pageSize > 100 || !integer(row.total) || row.items.length > row.pageSize || row.items.length > row.total) return invalid();
  row.items.forEach(summary); return row as OrderPage;
}
export function parseOrder(v: unknown): Order {
  const row = priced(v); summary(row);
  const who = object(row.recipient), flow = object(row.workflow);
  if (!isUuid(row.customerId) || (row.paymentId !== null && !isUuid(row.paymentId)) || !["COD", "SIMULATED"].includes(row.paymentMethod as string) || !text(who.name) || !text(who.phone) || !text(who.address) || (row.note !== null && !text(row.note)) || !["CHECKOUT", "IDLE", "CANCELLATION", "DISPATCH", "COMPLETION"].includes(flow.phase as string) || !["RUNNING", "WAITING", "DONE", "NEEDS_ATTENTION"].includes(flow.state as string) || typeof flow.requiresAttention !== "boolean" || !Array.isArray(row.allowedActions) || !row.allowedActions.every((a) => text(a) && Object.hasOwn(actionLabels, a)) || !Array.isArray(row.history)) return invalid();
  for (const raw of row.history) {
    const h = object(raw);
    if ((h.fromStatus !== null && !status(h.fromStatus)) || !status(h.toStatus) || (h.reason !== null && !text(h.reason)) || !date(h.createdAt)) return invalid();
  }
  return row as Order;
}
export function parseAccepted(v: unknown): Accepted { const row = object(v); if (!isUuid(row.orderId) || !text(row.orderNumber) || !status(row.status)) return invalid(); return row as Accepted; }
export function parseAction(v: unknown): ActionResult { const row = object(v); if (!isUuid(row.orderId) || !status(row.status) || !["RUNNING", "WAITING", "DONE", "NEEDS_ATTENTION"].includes(row.workflowState as string)) return invalid(); return row as ActionResult; }
export function formatMoney(amount: string) { if (!money(amount)) return "—"; return `${new Intl.NumberFormat("vi-VN").format(BigInt(amount))} ₫`; }
export function createPayload(quote: Quote, recipient: Recipient, paymentMethod: "COD" | "SIMULATED", note: string): CreateOrder {
  return { items: quote.items.map((i) => ({ productId: i.productId, quantity: i.quantity, expectedUnitPriceAmount: i.unitPriceAmount, expectedCatalogVersion: i.catalogVersion })), expectedShippingFeeAmount: quote.shippingFeeAmount, recipient, paymentMethod, note };
}
export function orderBase(admin: boolean) { return admin ? "/admin/orders" : "/orders"; }
export function actionPath(id: string, action: OrderAction, admin: boolean) {
  if (!isUuid(id) || (!admin && action !== "CANCEL")) throw new Error("Invalid action");
  const segment = { CONFIRM: "confirm", CANCEL: "cancel", DISPATCH: "dispatch", COMPLETE: "complete", RECORD_EXCEPTION: "exceptions" }[action];
  return `${orderBase(admin)}/${id}/${segment}`;
}
export function shouldPoll(order: Order) { return order.workflow.phase !== "IDLE" && !["COMPLETED", "CANCELLED", "REJECTED"].includes(order.status); }
export function userError(error: unknown, context: "order" | "auth" = "order"): string {
  if (!(error instanceof ApiError)) return error instanceof Error && error.message === "PENDING_REQUEST_CHANGED" ? "Yêu cầu trước chưa rõ kết quả. Hãy gửi lại đúng nội dung cũ trước khi thay đổi." : "Không thể xử lý yêu cầu. Vui lòng thử lại.";
  if (context === "auth" && error.status === 404) return "Đăng nhập chưa sẵn sàng. Chức năng tài khoản của hệ thống chưa được kết nối.";
  const known: Record<string, string> = { AUTH_UNAVAILABLE: "Đăng nhập chưa sẵn sàng. Vui lòng thử lại sau.", AUTH_INVALID: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.", FORBIDDEN: "Bạn không có quyền thực hiện thao tác này.", NOT_FOUND: "Không tìm thấy đơn hàng hoặc bạn không có quyền xem.", ORDER_STATE_CONFLICT: "Trạng thái đơn vừa thay đổi. Hãy tải lại để xem thao tác được phép.", PRICE_CHANGED: "Giá hoặc phí giao hàng đã thay đổi. Hãy kiểm tra và xác nhận giá mới.", DEPENDENCY_UNAVAILABLE: "Hệ thống đang bận. Vui lòng thử lại sau.", VALIDATION_ERROR: "Vui lòng kiểm tra thông tin đã nhập.", IDEMPOTENCY_CONFLICT: "Nội dung yêu cầu khác lần gửi trước. Hãy tải lại để kiểm tra đơn." };
  return `${known[error.code] ?? (error.status === 404 ? "Chức năng chưa sẵn sàng hoặc dữ liệu không tồn tại." : error.status === 0 ? "Chưa nhận được kết quả. Gửi lại yêu cầu để kiểm tra an toàn." : "Yêu cầu chưa hoàn tất. Vui lòng thử lại.")}${error.requestId ? ` Mã tra cứu: ${error.requestId}` : ""}`;
}
export async function orderGet<T>(path: string, token: string, parse: (v: unknown) => T, signal?: AbortSignal): Promise<T> {
  return parse(await apiRequest<unknown>(path, { headers: { Authorization: `Bearer ${token}` }, signal }));
}
export async function orderPost<T>(path: string, token: string, body: unknown, parse: (v: unknown) => T, key?: string): Promise<T> {
  return parse(await apiRequest<unknown>(path, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) }, body: JSON.stringify(body) }));
}
