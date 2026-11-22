// UI demonstration only. This module is never imported by the app or backend.
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createPayload, parseCart, parseQuote, type Order, type OrderAction, type OrderStatus, type Quote } from "../src/lib/orders";

export type Role = "CUSTOMER" | "ADMIN";
export type DemoReply = { status: number; body: unknown };
const examples = JSON.parse(readFileSync(fileURLToPath(new URL("../../../docs/order/fixtures/http.json", import.meta.url)), "utf8")).examples;
const quote: Quote = parseQuote(examples.find((e: { name: string }) => e.name === "quote").responseBody);
export const demoCart = quote.items.map((i) => ({ productId: i.productId, quantity: i.quantity }));
export const demoAccounts = {
  CUSTOMER: { email: "khach@demo.local", password: "demo123", id: "10000000-0000-4000-8000-000000000001", fullName: "Khách demo" },
  ADMIN: { email: "admin@demo.local", password: "demo123", id: "10000000-0000-4000-8000-000000000003", fullName: "Admin demo" },
} as const;
const recipient = { name: "Khách demo", phone: "0900000001", address: "12 đường Mẫu, phường Demo, TP Hồ Chí Minh" };
const ok = (body: unknown, status = 200): DemoReply => ({ status, body: structuredClone(body) });
const fail = (code: string, status: number, details?: unknown): DemoReply => ({ status, body: { code, message: "Phản hồi dữ liệu demo", requestId: "demo-" + randomUUID(), ...(details ? { details } : {}) } });

export class OrderDemo {
  orders = new Map<string, Order>();
  private jobs = new Map<string, { at: number; kind: string }>();
  private replays = new Map<string, { hash: string; reply: DemoReply }>();
  constructor(private delayMs = 2000) {
    this.seed("COD", "AWAITING_CONFIRMATION");
    this.seed("SIMULATED", "SHIPPING");
  }
  private seed(method: "COD" | "SIMULATED", status: OrderStatus) {
    const id = randomUUID(), now = new Date().toISOString();
    const row: Order = { ...structuredClone(quote), id, orderNumber: `DEMO-${method}-${this.orders.size + 1}`, customerId: demoAccounts.CUSTOMER.id, status, paymentStatus: method === "COD" ? "AWAITING_COLLECTION" : "SUCCEEDED", paymentId: randomUUID(), paymentMethod: method, recipient, note: "Đơn mẫu, không ghi vào Supabase", createdAt: now, workflow: { phase: "IDLE", state: "DONE", requiresAttention: false }, history: [{ fromStatus: null, toStatus: "PROCESSING", reason: null, createdAt: now }, { fromStatus: "PROCESSING", toStatus: "AWAITING_CONFIRMATION", reason: null, createdAt: now }], allowedActions: [] };
    if (status === "SHIPPING") {
      row.history.push({ fromStatus: "AWAITING_CONFIRMATION", toStatus: "PREPARING", reason: null, createdAt: now }, { fromStatus: "PREPARING", toStatus: "SHIPPING", reason: null, createdAt: now });
    }
    this.orders.set(id, row);
  }
  private transition(row: Order, status: OrderStatus, reason: string | null = null) {
    row.history.push({ fromStatus: row.status, toStatus: status, reason, createdAt: new Date().toISOString() });
    row.status = status;
  }
  private settle() {
    for (const [id, job] of this.jobs) {
      if (Date.now() < job.at) continue;
      const row = this.orders.get(id)!;
      if (job.kind === "checkout") { this.transition(row, "AWAITING_CONFIRMATION"); row.paymentStatus = row.paymentMethod === "COD" ? "AWAITING_COLLECTION" : "SUCCEEDED"; }
      if (job.kind === "dispatch") this.transition(row, "SHIPPING");
      if (job.kind === "cancel") { this.transition(row, "CANCELLED"); row.paymentStatus = row.paymentMethod === "COD" ? "CANCELLED" : "REFUNDED"; }
      if (job.kind === "complete") { this.transition(row, "COMPLETED"); row.paymentStatus = "SUCCEEDED"; }
      row.workflow = { phase: "IDLE", state: "DONE", requiresAttention: false };
      this.jobs.delete(id);
    }
  }
  private actions(row: Order, role: Role): OrderAction[] {
    if (row.workflow.phase !== "IDLE") return [];
    if (row.status === "AWAITING_CONFIRMATION") return role === "ADMIN" ? ["CONFIRM", "CANCEL"] : ["CANCEL"];
    if (role === "ADMIN" && row.status === "PREPARING") return ["DISPATCH", "CANCEL"];
    if (role === "ADMIN" && row.status === "SHIPPING") return ["COMPLETE", "RECORD_EXCEPTION"];
    return [];
  }
  private priced(raw: unknown): Quote {
    const items = parseCart(raw);
    if (!items.length || items.some((i) => !quote.items.some((q) => q.productId === i.productId))) throw new Error("Unknown demo cart");
    const lines = items.map((i) => {
      const source = quote.items.find((q) => q.productId === i.productId)!;
      return { ...source, quantity: i.quantity, lineTotalAmount: String(BigInt(source.unitPriceAmount) * BigInt(i.quantity)) };
    });
    const subtotal = lines.reduce((sum, i) => sum + BigInt(i.lineTotalAmount), BigInt(0));
    return parseQuote({ ...quote, items: lines, subtotalAmount: String(subtotal), totalAmount: String(subtotal + BigInt(quote.shippingFeeAmount)), quotedAt: new Date().toISOString() });
  }
  handle(method: string, url: URL, role: Role, body: unknown, key?: string): DemoReply {
    this.settle();
    const path = url.pathname;
    const base = role === "ADMIN" ? "/api/v1/admin/orders" : "/api/v1/orders";
    if (path !== base && !path.startsWith(base + "/")) return fail("FORBIDDEN", 403);
    if (method === "POST" && path === base + "/quote" && role === "CUSTOMER") {
      try { return ok(this.priced((body as { items?: unknown })?.items)); } catch { return fail("VALIDATION_ERROR", 400); }
    }
    if (method === "GET" && path === base) {
      const page = Math.max(1, Number(url.searchParams.get("page") ?? 1)), pageSize = 20;
      const status = url.searchParams.get("status"), query = (url.searchParams.get("q") ?? "").toLowerCase();
      const rows = [...this.orders.values()].reverse().filter((r) => (!status || r.status === status) && (!query || r.orderNumber.toLowerCase().includes(query)));
      return ok({ items: rows.slice((page - 1) * pageSize, page * pageSize), page, pageSize, total: rows.length });
    }
    const [id, action] = path.slice(base.length + 1).split("/");
    const row = this.orders.get(id);
    if (method === "GET" && row && !action) return ok({ ...row, allowedActions: this.actions(row, role) });
    if (method !== "POST") return fail("NOT_FOUND", 404);
    if (!key || key.length > 128) return fail("VALIDATION_ERROR", 400);
    const identity = `${role}:${path}:${key}`, hash = JSON.stringify(body);
    const old = this.replays.get(identity);
    if (old) return old.hash === hash ? structuredClone(old.reply) : fail("IDEMPOTENCY_CONFLICT", 409);
    const reply = path === base && role === "CUSTOMER" ? this.create(body) : row ? this.act(row, role, action, body) : fail("NOT_FOUND", 404);
    if (reply.status < 300) this.replays.set(identity, { hash, reply: structuredClone(reply) });
    return reply;
  }
  private create(raw: unknown): DemoReply {
    try {
      const body = raw as ReturnType<typeof createPayload>;
      const price = this.priced(body.items);
      if (body.expectedShippingFeeAmount !== price.shippingFeeAmount || body.items.some((i, n) => i.expectedUnitPriceAmount !== price.items[n].unitPriceAmount || i.expectedCatalogVersion !== price.items[n].catalogVersion)) return fail("PRICE_CHANGED", 409, { quote: price });
      if (!["COD", "SIMULATED"].includes(body.paymentMethod) || !body.recipient?.name?.trim() || !/^\+?[0-9]{8,15}$/.test(body.recipient.phone) || typeof body.recipient.address !== "string" || body.recipient.address.trim().length < 10) return fail("VALIDATION_ERROR", 400);
      const id = randomUUID(), now = new Date().toISOString();
      const row: Order = { ...price, id, orderNumber: `DEMO-${String(this.orders.size + 1).padStart(4, "0")}`, customerId: demoAccounts.CUSTOMER.id, status: "PROCESSING", paymentStatus: "PENDING", paymentId: randomUUID(), paymentMethod: body.paymentMethod, recipient: structuredClone(body.recipient), note: body.note, createdAt: now, workflow: { phase: "CHECKOUT", state: "WAITING", requiresAttention: false }, history: [{ fromStatus: null, toStatus: "PROCESSING", reason: null, createdAt: now }], allowedActions: [] };
      this.orders.set(id, row); this.jobs.set(id, { at: Date.now() + this.delayMs, kind: "checkout" });
      return ok({ orderId: id, orderNumber: row.orderNumber, status: row.status }, 202);
    } catch { return fail("VALIDATION_ERROR", 400); }
  }
  private act(row: Order, role: Role, action: string, raw: unknown): DemoReply {
    const names: Record<string, OrderAction> = { confirm: "CONFIRM", cancel: "CANCEL", dispatch: "DISPATCH", complete: "COMPLETE", exceptions: "RECORD_EXCEPTION" };
    if (!this.actions(row, role).includes(names[action])) return fail("ORDER_STATE_CONFLICT", 409);
    const body = (raw ?? {}) as { reason?: string; delivered?: boolean; codCollected?: boolean };
    if (["cancel", "exceptions"].includes(action) && (typeof body.reason !== "string" || !body.reason.trim() || body.reason.length > 1000)) return fail("VALIDATION_ERROR", 400);
    if (action === "complete" && (body.delivered !== true || (row.paymentMethod === "COD" && body.codCollected !== true))) return fail("VALIDATION_ERROR", 400);
    if (action === "confirm") this.transition(row, "PREPARING");
    if (action === "exceptions") row.workflow.requiresAttention = true;
    const phases: Record<string, string> = { cancel: "CANCELLATION", dispatch: "DISPATCH", complete: "COMPLETION" };
    if (phases[action]) {
      if (action === "cancel") { this.transition(row, "CANCELLING", body.reason); if (row.paymentMethod === "SIMULATED") row.paymentStatus = "REFUND_PENDING"; }
      row.workflow = { phase: phases[action], state: "WAITING", requiresAttention: false };
      this.jobs.set(row.id, { at: Date.now() + this.delayMs, kind: action });
    }
    return ok({ orderId: row.id, status: row.status, workflowState: row.workflow.state }, phases[action] ? 202 : 200);
  }
}
