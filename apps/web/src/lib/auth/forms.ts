import { ApiError } from "../api-client";

// Client-side checks for the login and register forms. They only save a round trip:
// the server stays the authority and applies its own rules again.

export const EMAIL_MAX_LENGTH = 254;
export const FULL_NAME_MAX_LENGTH = 150;
export const PASSWORD_MIN_LENGTH = 10;
export const PASSWORD_MAX_LENGTH = 128;

export type FieldErrorCode = "required" | "invalid_email" | "too_long" | "too_short" | "mismatch";

export type FormResult<Value, Field extends string> =
  | { ok: true; value: Value }
  | { ok: false; errors: Partial<Record<Field, FieldErrorCode>> };

export type LoginInput = { email: string; password: string };
export type RegisterInput = {
  fullName: string;
  email: string;
  password: string;
  confirmPassword: string;
};
export type RegisterValue = { fullName: string; email: string; password: string };

// Same rule as the server's JSON Schema maxLength/minLength: count code points, not UTF-16 units.
function length(text: string): number {
  return Array.from(text).length;
}

// Deliberately loose: one "@", no whitespace, a dot in the domain. Real validation is server-side.
const EMAIL_SHAPE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

function checkEmail(raw: string): FieldErrorCode | null {
  const email = raw.trim();
  if (email === "") return "required";
  if (length(email) > EMAIL_MAX_LENGTH) return "too_long";
  if (!EMAIL_SHAPE.test(email)) return "invalid_email";
  return null;
}

// Passwords are never trimmed or altered: spaces at the ends are part of the password.
export function validateLogin(input: LoginInput): FormResult<LoginInput, "email" | "password"> {
  const errors: Partial<Record<"email" | "password", FieldErrorCode>> = {};
  const emailError = checkEmail(input.email);
  if (emailError) errors.email = emailError;
  // No length rules on login: they would leak the policy and reject older passwords.
  if (input.password === "") errors.password = "required";
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return { ok: true, value: { email: input.email.trim(), password: input.password } };
}

export function validateRegister(
  input: RegisterInput,
): FormResult<RegisterValue, "fullName" | "email" | "password" | "confirmPassword"> {
  const errors: Partial<
    Record<"fullName" | "email" | "password" | "confirmPassword", FieldErrorCode>
  > = {};

  const fullName = input.fullName.trim();
  if (fullName === "") errors.fullName = "required";
  else if (length(fullName) > FULL_NAME_MAX_LENGTH) errors.fullName = "too_long";

  const emailError = checkEmail(input.email);
  if (emailError) errors.email = emailError;

  if (input.password === "") errors.password = "required";
  else if (length(input.password) < PASSWORD_MIN_LENGTH) errors.password = "too_short";
  else if (length(input.password) > PASSWORD_MAX_LENGTH) errors.password = "too_long";

  // Only compare once the password itself is acceptable, so one mistake shows one message.
  if (!errors.password && input.confirmPassword !== input.password) {
    errors.confirmPassword = "mismatch";
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: { fullName, email: input.email.trim(), password: input.password },
  };
}

export function fieldErrorMessage(code: FieldErrorCode): string {
  switch (code) {
    case "required":
      return "Vui lòng nhập thông tin này.";
    case "invalid_email":
      return "Email chưa đúng định dạng.";
    case "too_long":
      return "Giá trị quá dài.";
    case "too_short":
      return `Mật khẩu cần ít nhất ${PASSWORD_MIN_LENGTH} ký tự.`;
    case "mismatch":
      return "Mật khẩu nhập lại chưa khớp.";
  }
}

const GENERIC_ERROR = "Đã có lỗi xảy ra. Vui lòng thử lại sau.";
const LOGIN_REJECTED = "Email hoặc mật khẩu không đúng.";
const UNREACHABLE = "Không kết nối được máy chủ. Vui lòng thử lại sau.";

// Turns a failed auth request into one message for the form. It never shows the server's own
// message text, and for login it never says which part was wrong or whether the account exists.
export function describeAuthError(error: unknown, action: "login" | "register"): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR;
  if (["NETWORK_ERROR", "REQUEST_TIMEOUT"].includes(error.code) || error.status === 503) {
    return UNREACHABLE;
  }
  if (action === "login") {
    // 403 is shown the same as 401: a DISABLED account must not be told apart from a bad password.
    if (error.status === 401 || error.status === 403) return LOGIN_REJECTED;
    if (error.status === 400) return LOGIN_REJECTED;
    return GENERIC_ERROR;
  }
  if (error.status === 409) return "Email này đã được đăng ký.";
  if (error.status === 400) return "Thông tin chưa hợp lệ. Vui lòng kiểm tra lại các trường.";
  return GENERIC_ERROR;
}
