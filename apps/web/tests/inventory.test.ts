import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError } from "../src/lib/api-client";
import {
  createInventoryApi,
  InventoryAttempt,
  loginInventory,
  unknownOutcome,
} from "../src/lib/inventory";
import {
  createPreviewInventory,
  previewProducts,
} from "../src/lib/inventory-preview";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("inventory writes preserve bearer, body, version and idempotency key on retry", async () => {
  const body = {
    productId: previewProducts[0].productId,
    delta: 4,
    reason: "Nhập hàng",
    expectedVersion: 3,
  };
  const attempt = new InventoryAttempt(body);
  let calls = 0;
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/api/v1/admin/inventory/adjustments");
    assert.equal(
      new Headers(init?.headers).get("Authorization"),
      "Bearer admin-session",
    );
    assert.equal(
      new Headers(init?.headers).get("Idempotency-Key"),
      attempt.key,
    );
    assert.deepEqual(JSON.parse(String(init?.body)), body);
    if (calls++ === 0) throw new Error("lost response");
    return Response.json({
      productId: body.productId,
      onHandQuantity: 10,
      reservedQuantity: 2,
      availableQuantity: 8,
      lowStockThreshold: 5,
      version: 4,
    });
  };
  const api = createInventoryApi("admin-session");
  await assert.rejects(api.adjust(body, attempt.key), (error: unknown) =>
    unknownOutcome(error),
  );
  const result = await api.adjust(body, attempt.key);
  assert.equal(result.version, 4);
});

test("inventory filters and movement pagination stay on the public gateway", async () => {
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return Response.json({ items: [], page: 2, pageSize: 10, total: 0 });
  };
  const api = createInventoryApi("session");
  await api.list({ page: 2, pageSize: 10, lowStock: false });
  await api.movements(previewProducts[0].productId, 2);
  assert.deepEqual(urls, [
    "/api/v1/admin/inventory?page=2&pageSize=10&lowStock=false",
    `/api/v1/admin/inventory/${previewProducts[0].productId}/movements?page=2&pageSize=10`,
  ]);
});

test("preview adjustments are isolated, versioned and replayed exactly once", async () => {
  const api = createPreviewInventory();
  const { items } = await api.list({ page: 1, pageSize: 10 });
  const stock = items[0];
  const body = {
    productId: stock.productId,
    delta: 2,
    reason: "Kiểm kê",
    expectedVersion: stock.version,
  };
  const first = await api.adjust(body, "one-attempt");
  assert.deepEqual(await api.adjust(body, "one-attempt"), first);
  assert.equal(first.onHandQuantity, stock.onHandQuantity + 2);
  assert.equal(first.version, stock.version + 1);
  await assert.rejects(api.adjust({ ...body, delta: 3 }, "one-attempt"), {
    code: "IDEMPOTENCY_CONFLICT",
  });
  await assert.rejects(api.adjust(body, "new-attempt"), {
    code: "STOCK_VERSION_CONFLICT",
  });
  const untouched = await createPreviewInventory().list({
    page: 1,
    pageSize: 10,
  });
  assert.equal(untouched.items[0].version, stock.version);
});

test("preview protects reserved stock and records movements after receipt", async () => {
  const api = createPreviewInventory();
  const stock = (await api.list({ page: 1, pageSize: 10 })).items[1];
  await assert.rejects(
    api.adjust(
      {
        productId: stock.productId,
        delta: -4,
        reason: "Kiểm kê",
        expectedVersion: stock.version,
      },
      "below-reserved",
    ),
    { code: "INSUFFICIENT_STOCK" },
  );
  const result = await api.adjust(
    {
      productId: stock.productId,
      delta: 4,
      reason: "Nhập thêm",
      expectedVersion: stock.version,
    },
    "receipt",
  );
  const history = await api.movements(stock.productId, 1);
  assert.equal(history.items[0].onHandDelta, 4);
  assert.equal(history.items[0].onHandAfter, result.onHandQuantity);
  assert.equal(result.reservedQuantity, stock.reservedQuantity);
});

test("preview initialization does not reset an existing stock and supports low-stock filtering", async () => {
  const api = createPreviewInventory();
  const productId = previewProducts[6].productId;
  assert.equal(
    (await api.initialize({ productId, lowStockThreshold: 5 }, "new-item"))
      .onHandQuantity,
    0,
  );
  await api.adjust(
    { productId, delta: 10, reason: "Nhập đầu kỳ", expectedVersion: 0 },
    "first-receipt",
  );
  assert.equal(
    (await api.initialize({ productId, lowStockThreshold: 5 }, "existing-item"))
      .onHandQuantity,
    10,
  );
  const low = await api.list({ page: 1, pageSize: 10, lowStock: true });
  assert.ok(low.items.every((s) => s.availableQuantity <= s.lowStockThreshold));
  assert.ok(!low.items.some((s) => s.productId === productId));
});

test("live mode refuses a customer account and keeps tokens out of URLs", async () => {
  globalThis.fetch = async (input) => {
    if (String(input).endsWith("/auth/login"))
      return Response.json({ accessToken: "test-token" });
    assert.equal(input, "/api/v1/users/me");
    return Response.json({
      id: "customer",
      role: "CUSTOMER",
      status: "ACTIVE",
    });
  };
  await assert.rejects(loginInventory("customer@example.test", "test-only"), {
    code: "FORBIDDEN",
  });
  assert.equal(
    unknownOutcome(new ApiError("version", "STOCK_VERSION_CONFLICT", 409)),
    false,
  );
});
