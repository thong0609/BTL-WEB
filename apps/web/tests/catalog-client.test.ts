import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  createAdminCategory,
  createAdminProduct,
  deleteProductImage,
  fetchAdminCategories,
  fetchAdminProductDetail,
  fetchAdminProducts,
  fetchCategories,
  fetchProductDetail,
  fetchProducts,
  formatVND,
  generateSlug,
  isValidPriceString,
  isValidSlug,
  patchAdminCategory,
  patchAdminProduct,
  uploadProductImage,
} from "../src/lib/catalog";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("fetchCategories sends GET with page and pageSize", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/api/v1/categories?page=1&pageSize=50");
    assert.equal(init?.method ?? "GET", "GET");
    return Response.json({ items: [], page: 1, pageSize: 50, total: 0 });
  };
  const res = await fetchCategories(1, 50);
  assert.equal(res.total, 0);
});

test("fetchProducts formats query string with filters", async () => {
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    assert.equal(url.pathname, "/api/v1/products");
    assert.equal(url.searchParams.get("q"), "keyboard");
    assert.equal(url.searchParams.get("minPrice"), "100000");
    assert.equal(url.searchParams.get("sort"), "PRICE_ASC");
    return Response.json({ items: [], page: 1, pageSize: 20, total: 0 });
  };
  const res = await fetchProducts({
    q: "keyboard",
    minPrice: "100000",
    sort: "PRICE_ASC",
  });
  assert.equal(res.total, 0);
});

test("fetchProductDetail requests public product endpoint", async () => {
  globalThis.fetch = async (input) => {
    assert.equal(input, "/api/v1/products/prod-01");
    return Response.json({
      id: "prod-01",
      sku: "KB-01",
      slug: "kb-01",
      name: "Phím cơ",
      categoryId: "cat-01",
      description: "Mô tả",
      specifications: {},
      priceAmount: "430000",
      currency: "VND",
      status: "ACTIVE",
      version: 0,
      images: [],
      availability: "UNKNOWN",
    });
  };
  const prod = await fetchProductDetail("prod-01");
  assert.equal(prod.id, "prod-01");
  assert.equal(prod.priceAmount, "430000");
});

test("fetchAdminCategories, createAdminCategory and patchAdminCategory use admin endpoints", async () => {
  globalThis.fetch = async (input, init) => {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Authorization"), "Bearer admin-token");
    if (init?.method === "POST") {
      assert.equal(input, "/api/v1/admin/categories");
      const body = JSON.parse(String(init.body));
      return Response.json({ id: "cat-1", description: null, isVisible: true, ...body }, { status: 201 });
    }
    if (init?.method === "PATCH") {
      assert.equal(input, "/api/v1/admin/categories/cat-1");
      const body = JSON.parse(String(init.body));
      return Response.json({
        id: "cat-1",
        name: "Bàn phím",
        slug: "ban-phim",
        description: null,
        isVisible: Boolean(body.isVisible),
      });
    }
    assert.equal(input, "/api/v1/admin/categories?page=1&pageSize=20");
    return Response.json({ items: [], page: 1, pageSize: 20, total: 0 });
  };

  const list = await fetchAdminCategories("admin-token", 1, 20);
  assert.equal(list.total, 0);

  const created = await createAdminCategory({ name: "Bàn phím", slug: "ban-phim" }, "admin-token");
  assert.equal(created.slug, "ban-phim");

  const patched = await patchAdminCategory("cat-1", { isVisible: false }, "admin-token");
  assert.equal(patched.isVisible, false);
});

test("fetchAdminProducts and fetchAdminProductDetail attach Authorization header", async () => {
  globalThis.fetch = async (input, init) => {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Authorization"), "Bearer admin-secret-token");
    if (String(input).startsWith("/api/v1/admin/products/prod-99")) {
      return Response.json({ id: "prod-99", sku: "SKU-99", status: "DRAFT" });
    }
    return Response.json({ items: [], page: 1, pageSize: 20, total: 0 });
  };
  const res = await fetchAdminProducts("admin-secret-token", { status: "DRAFT" });
  assert.equal(res.items.length, 0);
  const detail = await fetchAdminProductDetail("prod-99", "admin-secret-token");
  assert.equal(detail.id, "prod-99");
});

test("createAdminProduct sends JSON body with VND currency", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/api/v1/admin/products");
    assert.equal(init?.method, "POST");
    const body = JSON.parse(String(init?.body));
    assert.equal(body.sku, "KB-01");
    assert.equal(body.priceAmount, "250000");
    assert.equal(body.currency, "VND");
    return Response.json({ id: "prod-1", ...body, version: 0, images: [], availability: "UNKNOWN" });
  };
  const res = await createAdminProduct(
    {
      sku: "KB-01",
      slug: "kb-01",
      name: "Phím cơ",
      categoryId: "11111111-1111-1111-1111-111111111111",
      description: "Bàn phím cơ nhỏ gọn",
      priceAmount: "250000",
    },
    "admin-token"
  );
  assert.equal(res.sku, "KB-01");
});

test("patchAdminProduct sends expectedVersion and changes", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/api/v1/admin/products/prod-123");
    assert.equal(init?.method, "PATCH");
    const body = JSON.parse(String(init?.body));
    assert.equal(body.expectedVersion, 3);
    assert.equal(body.priceAmount, "300000");
    return Response.json({ id: "prod-123", version: 4 });
  };
  const res = await patchAdminProduct(
    "prod-123",
    { expectedVersion: 3, priceAmount: "300000" },
    "admin-token"
  );
  assert.equal(res.version, 4);
});

test("uploadProductImage and deleteProductImage handle multipart and 204", async () => {
  globalThis.fetch = async (input, init) => {
    if (init?.method === "POST") {
      assert.equal(input, "/api/v1/admin/products/p1/images");
      assert.ok(init.body instanceof FormData);
      return Response.json(
        { id: "img1", url: "/api/v1/catalog/images/p1/img1.png", altText: "Alt", sortOrder: 0 },
        { status: 201 }
      );
    }
    assert.equal(input, "/api/v1/admin/products/p1/images/img1");
    assert.equal(init?.method, "DELETE");
    return new Response(null, { status: 204 });
  };
  const file = new File([new Uint8Array([137, 80, 78, 71])], "test.png", { type: "image/png" });
  const uploaded = await uploadProductImage("p1", file, "Alt", "admin-token");
  assert.equal(uploaded.id, "img1");

  const deleted = await deleteProductImage("p1", "img1", "admin-token");
  assert.equal(deleted, undefined);
});

test("formatVND, generateSlug, isValidSlug and isValidPriceString validate inputs", () => {
  assert.ok(formatVND("430000").includes("430.000"));
  assert.ok(formatVND(1000000).includes("1.000.000"));
  assert.equal(formatVND("invalid"), "0 ₫");

  assert.equal(generateSlug("Bàn phím cơ Đen 75%"), "ban-phim-co-den-75");
  assert.equal(isValidSlug("ban-phim-co-01"), true);
  assert.equal(isValidSlug("Invalid Slug"), false);
  assert.equal(isValidPriceString("430000"), true);
  assert.equal(isValidPriceString("-100"), false);
});
