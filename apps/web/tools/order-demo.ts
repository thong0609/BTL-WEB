/** Launch an isolated, interactive browser with demo-only API responses.
 * No mock endpoint or auth bypass is added to Next, Gateway or Order.
 */
import type { BrowserContext, Page } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { demoAccounts, demoCart, OrderDemo, type Role } from "./order-demo-model";

const origin = new URL(process.env.ORDER_DEMO_ORIGIN ?? "http://localhost:3100");
if (origin.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(origin.hostname) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) throw new Error("Demo requires a loopback HTTP origin");
const localBrowsers = fileURLToPath(new URL("../../../infra/.local/order-step1516/browsers", import.meta.url));
if (!process.env.PLAYWRIGHT_BROWSERS_PATH && existsSync(localBrowsers)) process.env.PLAYWRIGHT_BROWSERS_PATH = localBrowsers;
const verify = process.argv.includes("--verify");
const store = new OrderDemo(verify ? 0 : 2000);

async function intercept(context: BrowserContext) {
  let principal: Role | null = null;
  // Next dev can fully reload during compilation. Restore only the fake session
  // belonging to this controlled browser context, through its mocked refresh API.
  context.on("page", (page) => {
    page.on("load", () => {
      if (!principal) return;
      void page.getByRole("button", { name: "Khôi phục phiên đã đăng nhập" }).waitFor({ timeout: 2000 }).then(async () => {
        if (principal) await page.getByRole("button", { name: "Khôi phục phiên đã đăng nhập" }).click({ timeout: 2000 });
      }).catch(() => { /* Already authenticated or the window was closed. */ });
    });
  });
  await context.route("**/api/v1/**", async (route) => {
    const request = route.request(), url = new URL(request.url());
    let body: unknown;
    try { body = request.postData() ? request.postDataJSON() : {}; } catch { body = {}; }
    const reply = async (status: number, payload: unknown) => {
      if (verify) console.log("Demo API:", request.method(), url.pathname, status);
      return route.fulfill({ status, json: payload, headers: { "Cache-Control": "no-store" } });
    };
    const error = (status: number, code: string) => reply(status, { code, message: "Demo response only", requestId: "demo-browser" });
    const token = () => {
      const account = demoAccounts[principal!];
      return { accessToken: `demo-only-${principal}`, expiresIn: 3600, user: { id: account.id, email: account.email, fullName: account.fullName, role: principal, status: "ACTIVE" } };
    };
    if (request.method() === "POST" && url.pathname === "/api/v1/auth/login") {
      const input = body as { email?: unknown; password?: unknown };
      const role = (Object.keys(demoAccounts) as Role[]).find((r) => demoAccounts[r].email === input.email && demoAccounts[r].password === input.password);
      if (!role) { await error(401, "AUTH_INVALID"); return; }
      principal = role; await reply(200, token()); return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/auth/refresh") {
      if (principal) await reply(200, token()); else await error(401, "AUTH_INVALID");
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/auth/logout") { principal = null; await route.fulfill({ status: 204 }); return; }
    if (!principal || request.headers().authorization !== `Bearer demo-only-${principal}`) { await error(401, "AUTH_INVALID"); return; }
    // Every API request is fulfilled here, including unknown URLs. Never forward to real services.
    const result = store.handle(request.method(), url, principal, body, request.headers()["idempotency-key"]);
    await reply(result.status, result.body);
  });
}

async function decorate(context: BrowserContext, role: Role) {
  // Plain JS avoids serializing tsx/esbuild helper closures into the browser.
  await context.addInitScript({ content: `(() => {
    const cart = ${JSON.stringify(demoCart)};
    const role = ${JSON.stringify(role)};
    if (!sessionStorage.getItem("commerce.demo.seeded")) {
      sessionStorage.setItem("commerce.cart.v1", JSON.stringify(cart));
      sessionStorage.setItem("commerce.demo.seeded", "yes");
    }
    function banner() {
      if (!document.body || document.getElementById("commerce-demo-banner")) return;
      const bar = document.createElement("aside");
      bar.id = "commerce-demo-banner"; bar.setAttribute("aria-label", "Bản demo Order");
      bar.style.cssText = "position:fixed;inset:0 0 auto;z-index:99999;display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:12px 20px;background:#fff3cd;color:#563d00;border-bottom:2px solid #e3ac00;font:14px Arial;box-shadow:0 2px 6px #0002";
      const label = document.createElement("strong");
      label.textContent = "DEMO · " + (role === "ADMIN" ? "ADMIN" : "KHÁCH") + " · Dữ liệu giả, không ghi Supabase";
      bar.append(label);
      if (role === "CUSTOMER") {
        const add = document.createElement("button"); add.textContent = "Thêm giỏ mẫu";
        add.style.cssText = "padding:7px 12px;border:1px solid #927000;border-radius:6px;background:white;color:#563d00;cursor:pointer";
        add.onclick = () => {
          sessionStorage.setItem("commerce.cart.v1", JSON.stringify(cart));
          window.dispatchEvent(new Event("commerce:cart-changed"));
          const link = document.querySelector('nav a[href="/checkout"]');
          if (link instanceof HTMLAnchorElement) link.click();
        };
        bar.append(add);
      }
      document.body.style.paddingTop = "70px";
      document.body.append(bar);
      if (!document.title.startsWith("DEMO")) document.title = "DEMO · " + document.title;
    }
    window.addEventListener("load", () => {
      setTimeout(() => {
        banner();
        setInterval(banner, 1000);
      }, 700);
    });
  })();` });
}

async function open(context: BrowserContext, role: Role) {
  await intercept(context); await decorate(context, role);
  const page = await context.newPage();
  await page.goto(origin.origin + (role === "ADMIN" ? "/admin/orders" : "/orders"));
  await page.getByLabel("Email", { exact: true }).fill(demoAccounts[role].email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(demoAccounts[role].password);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await page.getByRole("link", { name: "DEMO-COD-1" }).waitFor();
  return page;
}
async function check(customer: Page, admin: Page) {
  await customer.getByRole("button", { name: "Thêm giỏ mẫu" }).click();
  await customer.getByRole("button", { name: "Xem giá và phí giao hàng" }).click();
  await customer.getByLabel("Họ tên người nhận").fill("Khách demo mới");
  await customer.getByLabel("Số điện thoại").fill("0900000001");
  await customer.getByLabel("Địa chỉ giao hàng").fill("12 đường Mẫu, khu Demo, TP Hồ Chí Minh");
  await customer.getByRole("button", { name: /Đặt hàng ·/ }).click();
  await customer.waitForURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(customer.url()).pathname.split("/").at(-1)!;
  await customer.getByRole("button", { name: "Hủy đơn", exact: true }).waitFor();
  try { await admin.goto(origin.origin + "/admin/orders/" + id); }
  catch (error) { if (!(error instanceof Error) || !error.message.includes("ERR_ABORTED")) throw error; }
  for (const label of ["Xác nhận đơn", "Bàn giao vận chuyển", "Hoàn thành đơn"]) {
    await admin.getByRole("button", { name: label, exact: true }).click();
    if (label === "Hoàn thành đơn") {
      await admin.getByLabel("Đã giao hàng cho người nhận").check();
      await admin.getByLabel("Đã thu đủ số tiền của đơn").check();
    }
    await admin.getByRole("button", { name: "Xác nhận thao tác" }).click();
  }
  await admin.getByText("Hoàn thành", { exact: true }).first().waitFor();
  const artifacts = fileURLToPath(new URL("../../../infra/.local/order-demo", import.meta.url));
  mkdirSync(artifacts, { recursive: true });
  await admin.screenshot({ path: artifacts + "/admin-verified.png", fullPage: true });
  console.log("PASS: isolated browser demo, customer creates COD, admin confirms/dispatches/completes; no backend API forwarded");
}

async function main() {
  let response: Response;
  try {
    response = await fetch(origin.origin + "/orders", { signal: AbortSignal.timeout(30000) });
  } catch {
    throw new Error(`Chưa kết nối được frontend tại ${origin.origin}.\nMở terminal khác ở D:\\BTL-WEB và chạy:\n  npm.cmd --prefix apps/web run dev\nGiữ terminal đó mở, đợi dòng Ready rồi chạy lại demo:orders.`);
  }
  if (!response.ok) throw new Error(`Frontend trả HTTP ${response.status} tại ${origin.origin}/orders. Kiểm tra terminal chạy frontend rồi thử lại demo:orders.`);
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch({ headless: verify });
  try {
    const customer = await open(await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" }), "CUSTOMER");
    const admin = await open(await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" }), "ADMIN");
    if (verify) {
      try { await check(customer, admin); }
      catch (error) {
        const artifacts = fileURLToPath(new URL("../../../infra/.local/order-demo", import.meta.url));
        mkdirSync(artifacts, { recursive: true });
        await customer.screenshot({ path: artifacts + "/failed.png", fullPage: true });
        console.error("Demo UI alerts:", await customer.locator('main [role="alert"]').allTextContents());
        throw error;
      }
      return;
    }
    await customer.bringToFront();
    console.log("DEMO_READY: opened customer and admin windows, already signed in.");
    console.log("Only these controlled browser windows use fake data. Normal localhost pages keep real authentication.");
    console.log("Customer: khach@demo.local / demo123; admin: admin@demo.local / demo123 (demo windows only).");
    console.log("Close both demo windows or press Ctrl+C to stop; all sample changes are discarded.");
    process.once("SIGINT", () => { void browser.close(); });
    await new Promise<void>((resolve) => browser.once("disconnected", () => resolve()));
  } finally { await browser.close(); }
}
main().catch((error: unknown) => { console.error(error instanceof Error ? error.message : "Unable to open demo"); process.exitCode = 1; });
