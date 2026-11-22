import { ApiError } from "./api-client";

export type PendingRequest = { key: string; path: string; body: unknown };
const prefix = "commerce.order.pending.v1:";
function storageKey(userId: string, path: string) { return `${prefix}${userId}:${path}`; }
export function readPending(storage: Storage, userId: string, path: string): PendingRequest | null {
  const raw = storage.getItem(storageKey(userId, path));
  if (!raw) return null;
  const item: unknown = JSON.parse(raw);
  if (!item || typeof item !== "object" || !("key" in item) || typeof item.key !== "string" || !("path" in item) || item.path !== path || !("body" in item)) throw new Error("Invalid pending request");
  return item as PendingRequest;
}
export async function mutate<T>(storage: Storage, userId: string, path: string, body: unknown, send: (intent: PendingRequest) => Promise<T>): Promise<T> {
  const old = readPending(storage, userId, path);
  if (old && JSON.stringify(old.body) !== JSON.stringify(body)) throw new Error("PENDING_REQUEST_CHANGED");
  const intent = old ?? { key: crypto.randomUUID(), path, body };
  // Saving must succeed before HTTP. A timeout or invalid success response keeps the intent.
  storage.setItem(storageKey(userId, path), JSON.stringify(intent));
  try {
    const result = await send(intent);
    storage.removeItem(storageKey(userId, path));
    return result;
  } catch (error) {
    if (error instanceof ApiError && [400, 401, 403, 404, 409].includes(error.status) && error.code !== "INVALID_RESPONSE") storage.removeItem(storageKey(userId, path));
    throw error;
  }
}
export function clearOrderSession(storage: Storage) {
  for (let i = storage.length - 1; i >= 0; i--) {
    const key = storage.key(i);
    if (key?.startsWith(prefix)) storage.removeItem(key);
  }
}
export const cartKey = "commerce.cart.v1";
export function saveCart(items: { productId: string; quantity: number }[]) {
  sessionStorage.setItem(cartKey, JSON.stringify(items));
  window.dispatchEvent(new Event("commerce:cart-changed"));
}
