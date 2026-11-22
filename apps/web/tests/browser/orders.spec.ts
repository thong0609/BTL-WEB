import { expect, test, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Fake producers/auth exist only in this test harness. Production has no bypass.
const examples = JSON.parse(readFileSync(resolve(process.cwd(), "../../docs/order/fixtures/http.json"), "utf-8")).examples;
const quoted = examples.find((e: { name: string }) => e.name === "quote").responseBody;
const input = examples.find((e: { name: string }) => e.name === "create_cod").requestBody;
const accepted = examples.find((e: { name: string }) => e.name === "create_cod").responseBody;
const customerId = "10000000-0000-4000-8000-000000000001";
function detail(patch: Record<string, unknown> = {}) {
  return { ...quoted, id: accepted.orderId, orderNumber: "ORDER-UI-001", customerId, paymentId: "10000000-0000-4000-8000-000000000201", status: "AWAITING_CONFIRMATION", paymentStatus: "AWAITING_COLLECTION", paymentMethod: "COD", recipient: input.recipient, note: "", createdAt: quoted.quotedAt, workflow: { phase: "IDLE", state: "DONE", requiresAttention: false }, history: [{ fromStatus: "PROCESSING", toStatus: "AWAITING_CONFIRMATION", reason: null, createdAt: quoted.quotedAt }], allowedActions: ["CANCEL"], ...patch };
}
function ok(route: Route, json: unknown, status = 200) { return route.fulfill({ status, json, headers: { "Cache-Control": "no-store" } }); }
function failure(route: Route, code: string, status: number, details?: unknown) { return ok(route, { code, message: "test response", requestId: "ui-test-request", ...(details ? { details } : {}) }, status); }
async function harness(page: Page, admin = false, handle?: (route: Route) => Promise<boolean>) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/login" || path === "/api/v1/auth/refresh") {
      await ok(route, { accessToken: "only-ui-test", expiresIn: 600, user: { id: customerId, email: "ui@example.test", fullName: "Khách kiểm thử", role: admin ? "ADMIN" : "CUSTOMER", status: "ACTIVE" } }); return;
    }
    if (path === "/api/v1/auth/logout") { await route.fulfill({ status: 204 }); return; }
    if (handle && await handle(route)) return;
    if (path === "/api/v1/orders/quote") { await ok(route, quoted); return; }
    if (path.endsWith(`/${accepted.orderId}`)) { await ok(route, detail()); return; }
    await failure(route, "NOT_FOUND", 404);
  });
}
async function login(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Email", { exact: true }).fill("ui@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("test-only-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
}
async function cart(page: Page) {
  await page.addInitScript((items) => sessionStorage.setItem("commerce.cart.v1", JSON.stringify(items)), quoted.items.map((i: { productId: string; quantity: number }) => ({ productId: i.productId, quantity: i.quantity })));
}
async function checkout(page: Page) {
  await cart(page); await login(page, "/checkout");
  await page.getByRole("button", { name: "Xem giá và phí giao hàng" }).click();
  await expect(page.getByText("430.000 ₫", { exact: true }).first()).toBeVisible();
  await page.getByLabel("Họ tên người nhận").fill(input.recipient.name);
  await page.getByLabel("Số điện thoại").fill(input.recipient.phone);
  await page.getByLabel("Địa chỉ giao hàng").fill(input.recipient.address);
}

test("checkout renders quote; timeout and reload retry original body/key without another order", async ({ page }, testInfo) => {
  const attempts: { key: string | undefined; body: unknown }[] = [];
  await harness(page, false, async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/v1/orders") return false;
    attempts.push({ key: route.request().headers()["idempotency-key"], body: route.request().postDataJSON() });
    if (attempts.length === 1) await route.abort("failed"); else await ok(route, accepted, 202);
    return true;
  });
  await checkout(page);
  await page.screenshot({ path: testInfo.outputPath("checkout.png"), fullPage: true });
  await page.getByRole("button", { name: /Đặt hàng ·/ }).click();
  await expect(page.getByRole("button", { name: "Gửi lại yêu cầu đặt hàng" })).toBeVisible();
  await expect(page.getByLabel("Họ tên người nhận")).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "Khôi phục phiên đã đăng nhập" }).click();
  await page.getByRole("button", { name: "Gửi lại yêu cầu đặt hàng" }).click();
  await expect(page).toHaveURL(`/orders/${accepted.orderId}`);
  expect(attempts).toHaveLength(2); expect(attempts[0].key).toBeTruthy(); expect(attempts[1]).toEqual(attempts[0]);
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(storage).not.toContain("only-ui-test"); expect(storage).not.toContain(input.recipient.address);
});

test("price change displays new quote and needs explicit confirmation with a new key", async ({ page }) => {
  const fresh = { ...quoted, shippingFeeAmount: "40000", totalAmount: "440000" };
  const calls: { key: string | undefined; body: { expectedShippingFeeAmount: string } }[] = [];
  await harness(page, false, async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/v1/orders") return false;
    calls.push({ key: route.request().headers()["idempotency-key"], body: route.request().postDataJSON() });
    if (calls.length === 1) await failure(route, "PRICE_CHANGED", 409, { quote: fresh }); else await ok(route, accepted, 202);
    return true;
  });
  await checkout(page);
  await page.getByRole("button", { name: /Đặt hàng ·/ }).click();
  await expect(page.getByRole("button", { name: "Đặt hàng · 440.000 ₫" })).toBeVisible();
  expect(calls).toHaveLength(1);
  await page.getByRole("button", { name: "Đặt hàng · 440.000 ₫" }).click();
  await expect(page).toHaveURL(`/orders/${accepted.orderId}`);
  expect(calls).toHaveLength(2); expect(calls[1].key).not.toEqual(calls[0].key); expect(calls[1].body.expectedShippingFeeAmount).toBe("40000");
});

test("HTTP 202 stays processing and polling waits for producer confirmation", async ({ page }) => {
  let confirmed = false, creates = 0;
  await harness(page, false, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/orders") { creates++; await ok(route, accepted, 202); return true; }
    if (path.endsWith(`/${accepted.orderId}`)) { await ok(route, confirmed ? detail() : detail({ status: "PROCESSING", workflow: { phase: "CHECKOUT", state: "WAITING", requiresAttention: false }, allowedActions: [] })); return true; }
    return false;
  });
  await checkout(page);
  await page.getByRole("button", { name: /Đặt hàng ·/ }).evaluate((button) => { if (button instanceof HTMLButtonElement) { button.click(); button.click(); } });
  await expect(page.getByText("Đang xử lý", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Hủy đơn", exact: true })).toHaveCount(0);
  expect(creates).toBe(1); confirmed = true;
  await expect(page.getByRole("button", { name: "Hủy đơn", exact: true })).toBeVisible({ timeout: 12000 });
});

test("customer cancel retries same key after 503 and shows cancelling, not cancelled", async ({ page }) => {
  let cancelled = false;
  const keys: string[] = [];
  await harness(page, false, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/cancel")) {
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length === 1) await failure(route, "DEPENDENCY_UNAVAILABLE", 503);
      else { cancelled = true; await ok(route, { orderId: accepted.orderId, status: "CANCELLING", workflowState: "WAITING" }, 202); }
      return true;
    }
    if (path.endsWith(`/${accepted.orderId}`)) { await ok(route, cancelled ? detail({ status: "CANCELLING", workflow: { phase: "CANCELLATION", state: "WAITING", requiresAttention: false }, allowedActions: [] }) : detail()); return true; }
    return false;
  });
  await login(page, `/orders/${accepted.orderId}`);
  await page.getByRole("button", { name: "Hủy đơn", exact: true }).click();
  await page.getByLabel("Lý do").fill("Không còn nhu cầu");
  await page.getByRole("button", { name: "Xác nhận thao tác" }).click();
  await page.getByRole("button", { name: "Gửi lại thao tác" }).click();
  await expect(page.getByText("Đang hủy", { exact: true })).toBeVisible();
  expect(keys).toHaveLength(2); expect(keys[1]).toBe(keys[0]);
});

for (const method of ["COD", "SIMULATED"]) test(`admin confirms, dispatches and completes ${method} with required delivery/collection`, async ({ page }) => {
  let state = detail({ paymentMethod: method, paymentStatus: method === "COD" ? "AWAITING_COLLECTION" : "SUCCEEDED", allowedActions: ["CONFIRM", "CANCEL"] });
  const actions: string[] = [];
  await harness(page, true, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith(`/${accepted.orderId}`)) { await ok(route, state); return true; }
    if (path.startsWith(`/api/v1/admin/orders/${accepted.orderId}/`)) {
      const action = path.split("/").at(-1)!; actions.push(action);
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      if (action === "confirm") state = { ...state, status: "PREPARING", allowedActions: ["DISPATCH", "CANCEL"] };
      if (action === "dispatch") state = { ...state, status: "SHIPPING", allowedActions: ["COMPLETE", "RECORD_EXCEPTION"] };
      if (action === "complete") {
        expect(route.request().postDataJSON()).toEqual(method === "COD" ? { delivered: true, codCollected: true } : { delivered: true });
        state = { ...state, status: "COMPLETED", paymentStatus: "SUCCEEDED", allowedActions: [] };
      }
      await ok(route, { orderId: accepted.orderId, status: action === "dispatch" ? "PREPARING" : state.status, workflowState: action === "dispatch" ? "WAITING" : "DONE" }, action === "confirm" ? 200 : 202); return true;
    }
    return false;
  });
  await login(page, `/admin/orders/${accepted.orderId}`);
  for (const action of ["Xác nhận đơn", "Bàn giao vận chuyển", "Hoàn thành đơn"]) {
    await page.getByRole("button", { name: action, exact: true }).click();
    if (action === "Hoàn thành đơn") {
      await page.getByRole("button", { name: "Xác nhận thao tác" }).click(); expect(actions).not.toContain("complete");
      await page.getByLabel("Đã giao hàng cho người nhận").check();
      if (method === "COD") { await page.getByRole("button", { name: "Xác nhận thao tác" }).click(); expect(actions).not.toContain("complete"); await page.getByLabel("Đã thu đủ số tiền của đơn").check(); }
      else await expect(page.getByLabel("Đã thu đủ số tiền của đơn")).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Xác nhận thao tác" }).click();
  }
  await expect(page.getByText("Hoàn thành", { exact: true })).toBeVisible();
  expect(actions).toEqual(["confirm", "dispatch", "complete"]);
});

test("list filters and pagination work; stored snapshot name and money stay unchanged", async ({ page }) => {
  const requests: string[] = [];
  await harness(page, false, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/orders") {
      requests.push(url.search);
      const data = detail(); await ok(route, { items: [data], page: Number(url.searchParams.get("page")), pageSize: 20, total: 21 }); return true;
    }
    return false;
  });
  await login(page, "/orders");
  await page.getByLabel("Trạng thái").selectOption("AWAITING_CONFIRMATION");
  await page.getByRole("button", { name: "Trang sau" }).click();
  await expect(page.getByText("21 đơn · Trang 2")).toBeVisible();
  expect(requests.at(-1)).toContain("page=2"); expect(requests.at(-1)).toContain("status=AWAITING_CONFIRMATION");
  await page.getByRole("link", { name: "ORDER-UI-001" }).click();
  await expect(page.getByText("Chuột thử nghiệm", { exact: true })).toBeVisible();
  await expect(page.getByText("430.000 ₫", { exact: true })).toBeVisible();
});

test("foreign order is not displayed; customer cannot open admin UI or forge admin headers", async ({ page }) => {
  await harness(page, false, async (route) => {
    if (new URL(route.request().url()).pathname.endsWith(`/${accepted.orderId}`)) { await ok(route, detail({ customerId: "10000000-0000-4000-8000-000000000002" })); return true; }
    return false;
  });
  await login(page, `/orders/${accepted.orderId}`);
  await expect(page.locator("main").getByRole("alert")).toBeVisible();
  await expect(page.getByText(input.recipient.address)).toHaveCount(0);
  await page.goto("/admin/orders"); await page.getByRole("button", { name: "Khôi phục phiên đã đăng nhập" }).click();
  await expect(page.getByText("Trang này chỉ dành cho quản trị viên.", { exact: false })).toBeVisible();
});

test("empty cart has no create button; unavailable login never fabricates a session", async ({ page }) => {
  await page.route("**/api/v1/auth/**", (route) => failure(route, "AUTH_UNAVAILABLE", 503));
  await login(page, "/checkout");
  await expect(page.locator("main").getByRole("alert")).toContainText("Đăng nhập chưa sẵn sàng");
  await expect(page.getByRole("button", { name: /Đặt hàng ·/ })).toHaveCount(0);
  await page.unrouteAll(); await harness(page);
  await page.getByRole("button", { name: "Khôi phục phiên đã đăng nhập" }).click();
  await expect(page.getByText("Giỏ hàng đang trống.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: /Đặt hàng ·/ })).toHaveCount(0);
});
