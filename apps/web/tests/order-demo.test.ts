import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/lib/api-client";
import { createPayload, parseAccepted, parseOrder, parseQuote, userError } from "../src/lib/orders";
import { demoCart, OrderDemo } from "../tools/order-demo-model";

const url = (path: string) => new URL("http://localhost:3100/api/v1" + path);
test("missing Identity route reports authentication unavailable instead of missing order", () => {
  const error = new ApiError("Not found", "NOT_FOUND", 404);
  assert.match(userError(error, "auth"), /Đăng nhập chưa sẵn sàng/);
  assert.doesNotMatch(userError(error, "auth"), /Không tìm thấy đơn hàng/);
  assert.match(userError(error), /Không tìm thấy đơn hàng/);
});
test("demo replay uses one sample order and customer cannot access admin actions", () => {
  const demo = new OrderDemo(0);
  assert.equal(demo.handle("GET", url("/admin/orders"), "CUSTOMER", {}).status, 403);
  const quote = parseQuote(demo.handle("POST", url("/orders/quote"), "CUSTOMER", { items: demoCart }).body);
  const body = createPayload(quote, { name: "Demo", phone: "0900000001", address: "Địa chỉ mẫu trong demo" }, "COD", "");
  const first = demo.handle("POST", url("/orders"), "CUSTOMER", body, "one");
  assert.equal(first.status, 202);
  const accepted = parseAccepted(first.body);
  assert.deepEqual(demo.handle("POST", url("/orders"), "CUSTOMER", body, "one"), first);
  assert.equal(demo.orders.size, 3);
  assert.equal(demo.handle("POST", url("/orders"), "CUSTOMER", { ...body, note: "changed" }, "one").status, 409);
  const order = parseOrder(demo.handle("GET", url("/orders/" + accepted.orderId), "CUSTOMER", {}).body);
  assert.equal(order.status, "AWAITING_CONFIRMATION");
  assert.equal(order.totalAmount, quote.totalAmount);
  assert.deepEqual(order.allowedActions, ["CANCEL"]);
  assert.equal(demo.handle("POST", url(`/orders/${order.id}/confirm`), "CUSTOMER", {}, "bad").status, 409);
});
test("demo COD requires collection confirmation and models cancellation separately", () => {
  const demo = new OrderDemo(0);
  const shipping = [...demo.orders.values()].find((r) => r.status === "SHIPPING")!;
  shipping.paymentMethod = "COD";
  const path = `/admin/orders/${shipping.id}/complete`;
  assert.equal(demo.handle("POST", url(path), "ADMIN", { delivered: true }, "done").status, 400);
  assert.equal(demo.handle("POST", url(path), "ADMIN", { delivered: true, codCollected: true }, "done").status, 202);
  assert.equal(parseOrder(demo.handle("GET", url(`/admin/orders/${shipping.id}`), "ADMIN", {}).body).status, "COMPLETED");
  const waiting = [...demo.orders.values()].find((r) => r.status === "AWAITING_CONFIRMATION")!;
  const cancellation = demo.handle("POST", url(`/orders/${waiting.id}/cancel`), "CUSTOMER", { reason: "Hủy mẫu" }, "cancel");
  assert.equal(cancellation.status, 202);
  assert.equal((cancellation.body as { status: string }).status, "CANCELLING");
  assert.equal(parseOrder(demo.handle("GET", url(`/orders/${waiting.id}`), "CUSTOMER", {}).body).status, "CANCELLED");
});
