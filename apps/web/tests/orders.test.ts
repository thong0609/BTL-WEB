import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import { ApiError } from "../src/lib/api-client";
import { clearOrderSession, mutate, readPending } from "../src/lib/order-intent";
import { actionPath, createPayload, formatMoney, orderPost, parseAccepted, parseCart, parseOrder, parseQuote, shouldPoll } from "../src/lib/orders";

const fixture = JSON.parse(readFileSync(new URL("../../../docs/order/fixtures/http.json", import.meta.url), "utf-8"));
const quote = fixture.examples.find((e: { name: string }) => e.name === "quote").responseBody;
const create = fixture.examples.find((e: { name: string }) => e.name === "create_cod").requestBody;
const accepted = fixture.examples.find((e: { name: string }) => e.name === "create_cod").responseBody;
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
class MemoryStorage implements Storage {
  data = new Map<string, string>();
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  getItem(k: string) { return this.data.get(k) ?? null; }
  key(i: number) { return [...this.data.keys()][i] ?? null; }
  removeItem(k: string) { this.data.delete(k); }
  setItem(k: string, v: string) { this.data.set(k, v); }
}
test("quote totals remain exact above JS safe integer; malformed totals/versions are rejected", () => {
  const q = parseQuote(quote);
  assert.equal(q.totalAmount, "430000");
  const big = structuredClone(quote);
  big.items[0].unitPriceAmount = "9007199254740993";
  big.items[0].lineTotalAmount = big.subtotalAmount = "18014398509481986";
  big.totalAmount = "18014398509511986";
  assert.equal(parseQuote(big).totalAmount, "18014398509511986");
  assert.equal(formatMoney("9007199254740993"), "9.007.199.254.740.993 ₫");
  for (const patch of [{ totalAmount: 430000 }, { totalAmount: "430001" }, { items: [{ ...quote.items[0], catalogVersion: true }] }, { items: [quote.items[0], quote.items[0]] }]) assert.throws(() => parseQuote({ ...quote, ...patch }), { code: "INVALID_RESPONSE" });
});
test("create uses confirmed prices, version and shipping; does not send user/status/total", () => {
  assert.deepEqual(createPayload(parseQuote(quote), create.recipient, "COD", create.note), create);
});
test("cart rejects duplicated/invalid IDs, boolean quantity and over 50 lines", () => {
  assert.deepEqual(parseCart([{ productId: create.items[0].productId, quantity: 2 }]), [{ productId: create.items[0].productId, quantity: 2 }]);
  for (const value of [[{ productId: "not-uuid", quantity: 2 }], [{ ...create.items[0], quantity: true }], [create.items[0], create.items[0]], new Array(51).fill(create.items[0])]) assert.throws(() => parseCart(value));
});
test("detail uses saved names/prices, validates actions, and polls only active workflows", () => {
  const raw = { ...quote, id: accepted.orderId, orderNumber: accepted.orderNumber, customerId: "10000000-0000-4000-8000-000000000001", status: "PROCESSING", paymentStatus: null, paymentId: null, paymentMethod: "COD", recipient: create.recipient, note: create.note, createdAt: quote.quotedAt, workflow: { phase: "CHECKOUT", state: "WAITING", requiresAttention: false }, history: [], allowedActions: [] };
  const detail = parseOrder(raw);
  assert.equal(detail.items[0].name, quote.items[0].name);
  assert.equal(shouldPoll(detail), true);
  assert.equal(shouldPoll({ ...detail, status: "CANCELLED" }), false);
  assert.equal(shouldPoll({ ...detail, workflow: { ...detail.workflow, phase: "IDLE" } }), false);
  assert.throws(() => parseOrder({ ...raw, allowedActions: ["DELETE"] }));
});
test("customer action path cannot invoke admin actions; POST carries bearer and key", async () => {
  assert.throws(() => actionPath(accepted.orderId, "DISPATCH", false));
  assert.equal(actionPath(accepted.orderId, "RECORD_EXCEPTION", true), `/admin/orders/${accepted.orderId}/exceptions`);
  globalThis.fetch = async (path, init) => {
    assert.equal(path, "/api/v1/orders");
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer only-test");
    assert.equal(new Headers(init?.headers).get("Idempotency-Key"), "same-request");
    assert.deepEqual(JSON.parse(String(init?.body)), create);
    return Response.json(accepted, { status: 202 });
  };
  assert.deepEqual(await orderPost("/orders", "only-test", create, parseAccepted, "same-request"), accepted);
});
test("timeout/reload retries exact key and body; editing an unresolved request is blocked", async () => {
  const storage = new MemoryStorage();
  let first = "";
  await assert.rejects(mutate(storage, "a", "/orders", create, async (intent) => { first = intent.key; throw new ApiError("timeout", "REQUEST_TIMEOUT", 0); }));
  assert.deepEqual(readPending(storage, "a", "/orders")?.body, create);
  assert.equal(readPending(storage, "b", "/orders"), null);
  await assert.rejects(mutate(storage, "a", "/orders", { ...create, note: "changed" }, async () => assert.fail("must not send")), /PENDING_REQUEST_CHANGED/);
  assert.deepEqual(await mutate(storage, "a", "/orders", structuredClone(create), async (intent) => { assert.equal(intent.key, first); return accepted; }), accepted);
  assert.equal(readPending(storage, "a", "/orders"), null);
});
test("price change clears old intent and explicit new confirmation receives a new key", async () => {
  const storage = new MemoryStorage();
  let first = "";
  await assert.rejects(mutate(storage, "a", "/orders", create, async (intent) => { first = intent.key; throw new ApiError("changed", "PRICE_CHANGED", 409, "test", { quote }); }));
  await mutate(storage, "a", "/orders", { ...create, expectedShippingFeeAmount: "40000" }, async (intent) => { assert.notEqual(intent.key, first); return accepted; });
});
test("5xx and malformed success retain intent; no HTTP if storage cannot persist", async () => {
  for (const error of [new ApiError("busy", "DEPENDENCY_UNAVAILABLE", 503), new ApiError("bad response", "INVALID_RESPONSE", 502)]) {
    const storage = new MemoryStorage();
    await assert.rejects(mutate(storage, "a", "/orders", create, async () => { throw error; }));
    assert.ok(readPending(storage, "a", "/orders"));
  }
  const storage = new MemoryStorage();
  storage.setItem = () => { throw new Error("quota exceeded"); };
  await assert.rejects(mutate(storage, "a", "/orders", create, async () => assert.fail("must not send")), /quota/);
});
test("logout removes pending address data without deleting unrelated browser state", async () => {
  const storage = new MemoryStorage(); storage.setItem("unrelated", "keep");
  await assert.rejects(mutate(storage, "a", "/orders", create, async () => { throw new Error("network"); }));
  clearOrderSession(storage);
  assert.equal(storage.length, 1); assert.equal(storage.getItem("unrelated"), "keep");
});
