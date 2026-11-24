import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/lib/api-client";
import { createSessionManager, type AuthUser, type Requester, type TokenResponse } from "../src/lib/auth/session";

type Options = NonNullable<Parameters<Requester>[1]>;
type Call = { path: string; method: string; auth: string | null; body?: BodyInit | null };

const user: AuthUser = { id: "11111111-1111-4111-8111-111111111111", email: "a@example.com", fullName: "An", role: "CUSTOMER", status: "ACTIVE" };
const token = (n: number): TokenResponse => ({ accessToken: `at${n}`, expiresIn: 900, user });
const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
const unauthorized = () => new ApiError("expired", "AUTH_INVALID", 401, "req-1");

function setup(handler: (call: Call) => unknown, extra: { lock?: Parameters<typeof createSessionManager>[0] } = {}) {
  const calls: Call[] = [];
  let time = 1_000_000;
  const request: Requester = async <T>(path: string, options: Options = {}) => {
    const call: Call = { path, method: options.method ?? "GET", auth: new Headers(options.headers).get("Authorization"), body: options.body };
    calls.push(call);
    return (await handler(call)) as T;
  };
  const manager = createSessionManager({ request, now: () => time, ...extra.lock });
  return { manager, calls, advance: (ms: number) => { time += ms; }, refreshCount: () => calls.filter((c) => c.path === "/auth/refresh").length };
}

test("login keeps the token in memory only and exposes just the user", async () => {
  const { manager, calls } = setup((call) => (call.path === "/auth/login" ? token(1) : undefined));
  assert.equal(manager.getState().status, "unknown");
  assert.deepEqual(await manager.login("a@example.com", "secret-password"), user);
  assert.equal(manager.getState().status, "authenticated");
  assert.equal(await manager.getAccessToken(), "at1");
  assert.ok(!JSON.stringify(manager.getState()).includes("at1"));
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].body)), { email: "a@example.com", password: "secret-password" });
});

test("register only creates the account and does not start a session", async () => {
  const { manager, calls } = setup(() => user);
  assert.deepEqual(await manager.register("a@example.com", "An", "secret-password"), user);
  assert.equal(manager.getState().status, "unknown");
  assert.equal(calls[0].path, "/auth/register");
  assert.deepEqual(JSON.parse(String(calls[0].body)), { email: "a@example.com", fullName: "An", password: "secret-password" });
});

test("restore: success authenticates, 401 becomes anonymous, network error keeps the state", async () => {
  const ok = setup(() => token(1));
  assert.equal((await ok.manager.restore()).status, "authenticated");

  const ended = setup(() => { throw new ApiError("gone", "SESSION_EXPIRED", 401); });
  assert.equal((await ended.manager.restore()).status, "anonymous");

  const down = setup(() => { throw new ApiError("net", "NETWORK_ERROR", 0); });
  await assert.rejects(down.manager.restore(), { code: "NETWORK_ERROR" });
  assert.equal(down.manager.getState().status, "unknown");
});

test("access token near expiry is refreshed once even for concurrent callers", async () => {
  const s = setup(async (call) => {
    if (call.path === "/auth/login") return token(1);
    await tick();
    return token(2);
  });
  await s.manager.login("a@example.com", "secret-password");
  assert.equal(await s.manager.getAccessToken(), "at1");
  assert.equal(s.refreshCount(), 0);
  s.advance(900_000 - 10_000); // inside the 30 s skew
  const [a, b] = await Promise.all([s.manager.getAccessToken(), s.manager.getAccessToken()]);
  assert.deepEqual([a, b], ["at2", "at2"]);
  assert.equal(s.refreshCount(), 1);
});

test("refresh failing on the network keeps a still-valid token instead of logging out", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    throw new ApiError("net", "NETWORK_ERROR", 0);
  });
  await s.manager.login("a@example.com", "secret-password");
  s.advance(900_000 - 10_000);
  assert.equal(await s.manager.getAccessToken(), "at1");
  assert.equal(s.manager.getState().status, "authenticated");
  s.advance(20_000); // now really expired
  await assert.rejects(s.manager.getAccessToken(), { code: "NETWORK_ERROR" });
});

test("authorizedRequest sends the bearer token and needs a session", async () => {
  const anonymous = setup(() => undefined);
  await assert.rejects(anonymous.manager.authorizedRequest("/orders"), { code: "AUTH_REQUIRED" });
  assert.equal(anonymous.calls.length, 0);

  const s = setup((call) => (call.path === "/auth/login" ? token(1) : { auth: call.auth }));
  await s.manager.login("a@example.com", "secret-password");
  assert.deepEqual(await s.manager.authorizedRequest("/orders"), { auth: "Bearer at1" });
});

test("a 401 triggers one refresh and one retry with the new token", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    if (call.path === "/auth/refresh") return token(2);
    if (call.auth === "Bearer at1") throw unauthorized();
    return { auth: call.auth };
  });
  await s.manager.login("a@example.com", "secret-password");
  assert.deepEqual(await s.manager.authorizedRequest("/orders"), { auth: "Bearer at2" });
  assert.deepEqual(s.calls.map((c) => c.path), ["/auth/login", "/orders", "/auth/refresh", "/orders"]);
});

test("parallel 401s share a single refresh and are all retried", async () => {
  const s = setup(async (call) => {
    if (call.path === "/auth/login") return token(1);
    if (call.path === "/auth/refresh") { await tick(20); return token(2); }
    if (call.auth === "Bearer at1") { await tick(); throw unauthorized(); }
    return { auth: call.auth, path: call.path };
  });
  await s.manager.login("a@example.com", "secret-password");
  const results = await Promise.all([s.manager.authorizedRequest("/a"), s.manager.authorizedRequest("/b"), s.manager.authorizedRequest("/c")]);
  assert.deepEqual(results.map((r) => (r as { auth: string }).auth), ["Bearer at2", "Bearer at2", "Bearer at2"]);
  assert.equal(s.refreshCount(), 1);
});

test("a second 401 after refreshing is returned, not retried in a loop", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    if (call.path === "/auth/refresh") return token(2);
    throw unauthorized();
  });
  await s.manager.login("a@example.com", "secret-password");
  await assert.rejects(s.manager.authorizedRequest("/orders"), { status: 401, code: "AUTH_INVALID" });
  assert.equal(s.refreshCount(), 1);
  assert.equal(s.calls.filter((c) => c.path === "/orders").length, 2);
});

test("when the refresh session is gone the user is logged out and the original error is thrown", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    if (call.path === "/auth/refresh") throw new ApiError("revoked", "SESSION_EXPIRED", 401);
    throw unauthorized();
  });
  await s.manager.login("a@example.com", "secret-password");
  await assert.rejects(s.manager.authorizedRequest("/orders"), { code: "AUTH_INVALID" });
  assert.equal(s.manager.getState().status, "anonymous");
  assert.equal(await s.manager.getAccessToken(), null);
});

test("errors other than 401 pass through without refreshing", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    throw new ApiError("no", "FORBIDDEN", 403);
  });
  await s.manager.login("a@example.com", "secret-password");
  await assert.rejects(s.manager.authorizedRequest("/admin"), { status: 403 });
  assert.equal(s.refreshCount(), 0);
});

test("logout during an in-flight refresh is not undone by the late response", async () => {
  const s = setup(async (call) => {
    if (call.path === "/auth/refresh") { await tick(20); return token(9); }
    return undefined;
  });
  await Promise.all([s.manager.restore(), s.manager.logout()]);
  assert.equal(s.manager.getState().status, "anonymous");
  assert.equal(await s.manager.getAccessToken(), null);
});

test("logout clears local state even when the server call fails, and reports the error", async () => {
  const s = setup((call) => {
    if (call.path === "/auth/login") return token(1);
    throw new ApiError("down", "DEPENDENCY_UNAVAILABLE", 503);
  });
  await s.manager.login("a@example.com", "secret-password");
  await assert.rejects(s.manager.logout(), { status: 503 });
  assert.equal(s.manager.getState().status, "anonymous");
  assert.equal(await s.manager.getAccessToken(), null);
});

test("refresh runs inside the cross-tab lock", async () => {
  const events: string[] = [];
  const lock = async <T>(task: () => Promise<T>) => { events.push("lock-enter"); try { return await task(); } finally { events.push("lock-exit"); } };
  const s = setup((call) => { events.push(call.path); return token(1); }, { lock: { lock } });
  await s.manager.restore();
  assert.deepEqual(events, ["lock-enter", "/auth/refresh", "lock-exit"]);
});

test("subscribers are notified on changes and can unsubscribe", async () => {
  const s = setup(() => token(1));
  let notified = 0;
  const unsubscribe = s.manager.subscribe(() => { notified += 1; });
  await s.manager.login("a@example.com", "secret-password");
  assert.equal(notified, 1);
  unsubscribe();
  await s.manager.logout().catch(() => undefined);
  assert.equal(notified, 1);
});

test("a late 401 for a request sent with the old token reuses the token refreshed meanwhile", async () => {
  const s = setup(async (call) => {
    if (call.path === "/auth/login") return token(1);
    if (call.path === "/auth/refresh") { await tick(5); return token(2); }
    if (call.auth === "Bearer at1") {
      if (call.path === "/slow") await tick(60);
      throw unauthorized();
    }
    return { auth: call.auth };
  });
  await s.manager.login("a@example.com", "secret-password");
  const [slow, fast] = await Promise.all([s.manager.authorizedRequest("/slow"), s.manager.authorizedRequest("/fast")]);
  assert.deepEqual([slow, fast], [{ auth: "Bearer at2" }, { auth: "Bearer at2" }]);
  assert.equal(s.refreshCount(), 1);
});
