import assert from "node:assert/strict";
import { test } from "node:test";
import { safeRedirectPath } from "../src/lib/auth/redirect";

test("keeps a plain internal path, query and hash", () => {
  assert.equal(safeRedirectPath("/checkout"), "/checkout");
  assert.equal(safeRedirectPath("/products?q=shirt&page=2"), "/products?q=shirt&page=2");
  assert.equal(safeRedirectPath("/orders/123#items"), "/orders/123#items");
  assert.equal(safeRedirectPath("/"), "/");
});

test("returns the fallback for missing or empty input", () => {
  assert.equal(safeRedirectPath(null), "/");
  assert.equal(safeRedirectPath(undefined), "/");
  assert.equal(safeRedirectPath(""), "/");
  assert.equal(safeRedirectPath(undefined, "/account"), "/account");
});

for (const raw of [
  "checkout",
  " /checkout",
  "//evil.com",
  "//evil.com/path",
  "///evil.com",
  "/\\evil.com",
  "\\\\evil.com",
  "/a\\b",
  "https://evil.com",
  "http://evil.com/checkout",
  "javascript:alert(1)",
  "data:text/html,x",
  "/\t/evil.com",
  "/\n/evil.com",
  "/\r/evil.com",
  "/a\u0000b",
  "/a\u007fb",
  "/a\u001fb",
  "/a\u0001b",
  "/..//evil.com",
  "/.//evil.com",
  "/a/..//evil.com",
]) {
  test(`rejects ${JSON.stringify(raw)}`, () => {
    assert.equal(safeRedirectPath(raw), "/");
  });
}

test("normalises dot segments that stay inside the site", () => {
  assert.equal(safeRedirectPath("/a/../checkout"), "/checkout");
  assert.equal(safeRedirectPath("/a/./b"), "/a/b");
});

test("keeps percent-encoded characters as they are", () => {
  assert.equal(safeRedirectPath("/search?q=%2F%2Fevil.com"), "/search?q=%2F%2Fevil.com");
  assert.equal(safeRedirectPath("/%2Fevil.com"), "/%2Fevil.com");
});

test("rejects login and register pages to avoid a loop, but not look-alikes", () => {
  for (const raw of ["/login", "/login?next=/x", "/login/", "/login/x", "/register", "/register#a"]) {
    assert.equal(safeRedirectPath(raw, "/home"), "/home", raw);
  }
  assert.equal(safeRedirectPath("/loginx"), "/loginx");
  assert.equal(safeRedirectPath("/registered"), "/registered");
  assert.equal(safeRedirectPath("/account/login"), "/account/login");
});

test("length limit is 2048 characters", () => {
  const ok = `/${"a".repeat(2047)}`;
  assert.equal(ok.length, 2048);
  assert.equal(safeRedirectPath(ok), ok);
  assert.equal(safeRedirectPath(`${ok}a`), "/");
});

test("a custom fallback is returned as given", () => {
  assert.equal(safeRedirectPath("//evil.com", "/checkout"), "/checkout");
});
