import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError, createApiClient } from "../src/lib/api-client";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test("same-origin request keeps caller headers, disables caching and preserves JSON money", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/api/v1/products?q=shirt");
    assert.equal(init?.cache, "no-store");
    assert.equal(init?.credentials, "same-origin");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Authorization"), "Bearer test-only");
    assert.equal(headers.get("X-Request-Id"), "test-id");
    return Response.json({ price: "9007199254740993" });
  };
  const result = await createApiClient()<{ price: string }>("/products?q=shirt", {
    headers: { Authorization: "Bearer test-only", "X-Request-Id": "test-id" },
  });
  assert.equal(result.price, "9007199254740993");
});

test("backend error envelope retains status, code, details and requestId", async () => {
  globalThis.fetch = async () => Response.json({ code: "UPSTREAM_UNAVAILABLE", message: "Catalog is unavailable", requestId: "request-123", details: { field: "test" } }, { status: 503 });
  await assert.rejects(createApiClient()("/health/catalog"), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.equal(error.code, "UPSTREAM_UNAVAILABLE");
    assert.equal(error.requestId, "request-123");
    assert.deepEqual(error.details, { field: "test" });
    return true;
  });
});

test("non-JSON proxy errors are sanitized and retain request header", async () => {
  globalThis.fetch = async () => new Response("<html>private proxy failure</html>", { status: 502, headers: { "X-Request-Id": "proxy-id" } });
  await assert.rejects(createApiClient()("/health/catalog"), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "HTTP_ERROR");
    assert.equal(error.requestId, "proxy-id");
    assert.ok(!error.message.includes("private"));
    return true;
  });
});

test("invalid successful JSON is rejected; 204 is supported", async () => {
  globalThis.fetch = async () => new Response("invalid-json");
  await assert.rejects(createApiClient()("/products"), { code: "INVALID_RESPONSE" });
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await createApiClient()("/products"), undefined);
});

test("connection failure is sanitized", async () => {
  globalThis.fetch = async () => { throw new Error("private URL"); };
  await assert.rejects(createApiClient()("/health/catalog"), { code: "NETWORK_ERROR" });
});

test("timeout aborts the request; caller cancellation stays distinct", async () => {
  globalThis.fetch = async (_input, init) => new Promise((_resolve, reject) => {
    if (init?.signal?.aborted) reject(new Error("abort"));
    else init?.signal?.addEventListener("abort", () => reject(new Error("abort")), { once: true });
  });
  await assert.rejects(createApiClient()("/health/catalog", { timeoutMs: 10 }), { code: "REQUEST_TIMEOUT" });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(createApiClient()("/health/catalog", { signal: controller.signal }), { code: "REQUEST_ABORTED" });
});

test("rejects absolute URLs and traversal before fetching", async () => {
  assert.throws(() => createApiClient("https://example.com"));
  for (const path of ["https://example.com", "//example.com", "/../admin", "/%2e%2e/admin", "/products#fragment"]) {
    await assert.rejects(createApiClient()(path), /API path/);
  }
});
