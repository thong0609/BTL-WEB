import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/lib/api-client";
import {
  describeAuthError,
  fieldErrorMessage,
  validateLogin,
  validateRegister,
  type FieldErrorCode,
} from "../src/lib/auth/forms";

const validRegister = {
  fullName: "Nguyễn Văn A",
  email: "user@example.com",
  password: "correct-horse",
  confirmPassword: "correct-horse",
};

test("login accepts a valid pair and trims only the email", () => {
  const result = validateLogin({ email: "  user@example.com ", password: " pass with spaces " });
  assert.deepEqual(result, {
    ok: true,
    value: { email: "user@example.com", password: " pass with spaces " },
  });
});

test("login reports an empty email and an empty password separately", () => {
  assert.deepEqual(validateLogin({ email: " ", password: "" }), {
    ok: false,
    errors: { email: "required", password: "required" },
  });
});

test("login does not apply password length rules", () => {
  assert.equal(validateLogin({ email: "a@b.co", password: "x" }).ok, true);
});

for (const [email, code] of [
  ["plain", "invalid_email"],
  ["a@b", "invalid_email"],
  ["a b@example.com", "invalid_email"],
  ["a@@example.com", "invalid_email"],
  ["a@example..com", "invalid_email"],
  ["@example.com", "invalid_email"],
  ["a@.com", "invalid_email"],
] as const) {
  test(`email shape rejects ${JSON.stringify(email)}`, () => {
    assert.deepEqual(validateLogin({ email, password: "x" }), {
      ok: false,
      errors: { email: code },
    });
  });
}

test("email length is limited to 254 and padding does not count", () => {
  const at254 = `${"a".repeat(254 - "@example.com".length)}@example.com`;
  assert.equal(validateLogin({ email: ` ${at254} `, password: "x" }).ok, true);
  const result = validateLogin({ email: `a${at254}`, password: "x" });
  assert.deepEqual(result, { ok: false, errors: { email: "too_long" } });
});

test("register returns trimmed name and email and the untouched password", () => {
  const result = validateRegister({
    ...validRegister,
    fullName: "  Nguyễn Văn A  ",
    email: " user@example.com ",
  });
  assert.deepEqual(result, {
    ok: true,
    value: { fullName: "Nguyễn Văn A", email: "user@example.com", password: "correct-horse" },
  });
});

test("register name must be 1 to 150 characters after trimming", () => {
  assert.deepEqual(validateRegister({ ...validRegister, fullName: "   " }), {
    ok: false,
    errors: { fullName: "required" },
  });
  assert.equal(validateRegister({ ...validRegister, fullName: "a".repeat(150) }).ok, true);
  assert.deepEqual(validateRegister({ ...validRegister, fullName: "a".repeat(151) }), {
    ok: false,
    errors: { fullName: "too_long" },
  });
});

test("register password must be 10 to 128 characters", () => {
  const nine = "a".repeat(9);
  assert.deepEqual(validateRegister({ ...validRegister, password: nine, confirmPassword: nine }), {
    ok: false,
    errors: { password: "too_short" },
  });
  const ten = "a".repeat(10);
  assert.equal(validateRegister({ ...validRegister, password: ten, confirmPassword: ten }).ok, true);
  const max = "a".repeat(128);
  assert.equal(validateRegister({ ...validRegister, password: max, confirmPassword: max }).ok, true);
  const over = "a".repeat(129);
  assert.deepEqual(
    validateRegister({ ...validRegister, password: over, confirmPassword: over }),
    { ok: false, errors: { password: "too_long" } },
  );
});

test("register counts code points, so an emoji is one character", () => {
  const nineAndEmoji = `${"a".repeat(9)}😀`;
  assert.equal(nineAndEmoji.length, 11);
  assert.equal(
    validateRegister({ ...validRegister, password: nineAndEmoji, confirmPassword: nineAndEmoji }).ok,
    true,
  );
  const eightAndEmoji = `${"a".repeat(8)}😀`;
  assert.deepEqual(
    validateRegister({ ...validRegister, password: eightAndEmoji, confirmPassword: eightAndEmoji }),
    { ok: false, errors: { password: "too_short" } },
  );
});

test("register password is not trimmed", () => {
  const password = "  spaced-pass  ";
  const result = validateRegister({ ...validRegister, password, confirmPassword: password });
  assert.deepEqual(result, {
    ok: true,
    value: { fullName: "Nguyễn Văn A", email: "user@example.com", password },
  });
});

test("register confirmation must match exactly", () => {
  assert.deepEqual(validateRegister({ ...validRegister, confirmPassword: "correct-horsE" }), {
    ok: false,
    errors: { confirmPassword: "mismatch" },
  });
  assert.deepEqual(validateRegister({ ...validRegister, confirmPassword: "" }), {
    ok: false,
    errors: { confirmPassword: "mismatch" },
  });
});

test("register shows no mismatch while the password itself is invalid", () => {
  assert.deepEqual(validateRegister({ ...validRegister, password: "short", confirmPassword: "x" }), {
    ok: false,
    errors: { password: "too_short" },
  });
});

test("register collects every field error at once", () => {
  assert.deepEqual(
    validateRegister({ fullName: "", email: "nope", password: "", confirmPassword: "" }),
    {
      ok: false,
      errors: { fullName: "required", email: "invalid_email", password: "required" },
    },
  );
});

test("every error code has a Vietnamese message", () => {
  const codes: FieldErrorCode[] = ["required", "invalid_email", "too_long", "too_short", "mismatch"];
  for (const code of codes) assert.ok(fieldErrorMessage(code).length > 0);
  assert.match(fieldErrorMessage("too_short"), /10/);
});

const apiError = (status: number, code = "X", message = "server text") =>
  new ApiError(message, code, status, "req-1");

test("login treats 401, 403 and 400 as the same generic message", () => {
  const messages = [401, 403, 400].map((s) => describeAuthError(apiError(s), "login"));
  assert.equal(new Set(messages).size, 1);
  assert.equal(messages[0], "Email hoặc mật khẩu không đúng.");
});

test("register maps 409 to email taken and 400 to invalid fields", () => {
  assert.equal(describeAuthError(apiError(409), "register"), "Email này đã được đăng ký.");
  assert.match(describeAuthError(apiError(400), "register"), /chưa hợp lệ/);
});

test("conflict on login is a generic error, not an email-taken message", () => {
  assert.doesNotMatch(describeAuthError(apiError(409), "login"), /đã được đăng ký/);
});

test("unreachable server is reported the same for both forms", () => {
  for (const action of ["login", "register"] as const) {
    const expected = describeAuthError(apiError(503), action);
    assert.match(expected, /kết nối/);
    assert.equal(describeAuthError(apiError(0, "NETWORK_ERROR"), action), expected);
    assert.equal(describeAuthError(apiError(0, "REQUEST_TIMEOUT"), action), expected);
  }
});

test("unknown errors give a generic message and never leak server text", () => {
  const generic = describeAuthError(new Error("boom"), "login");
  assert.equal(describeAuthError("nope", "register"), generic);
  assert.equal(describeAuthError(apiError(500, "X", "stack trace here"), "login"), generic);
  assert.doesNotMatch(generic, /boom|stack/);
  assert.doesNotMatch(describeAuthError(apiError(409, "X", "secret detail"), "register"), /secret/);
});
