"use client";

import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { apiRequest, ApiError } from "@/lib/api-client";
import { clearOrderSession } from "@/lib/order-intent";
import { isUuid, object, userError } from "@/lib/orders";

export type Session = { accessToken: string; expiresIn: number; user: { id: string; fullName: string; role: "CUSTOMER" | "ADMIN"; status: "ACTIVE" } };
export function parseSession(value: unknown): Session {
  const row = object(value), user = object(row.user);
  if (typeof row.accessToken !== "string" || !row.accessToken.trim() || typeof row.expiresIn !== "number" || !Number.isSafeInteger(row.expiresIn) || row.expiresIn < 1 || row.expiresIn > 86400 || !isUuid(user.id) || typeof user.fullName !== "string" || !["CUSTOMER", "ADMIN"].includes(user.role as string) || user.status !== "ACTIVE") throw new ApiError("Phiên đăng nhập không hợp lệ.", "AUTH_INVALID", 401);
  return row as Session;
}
type SessionContext = { session: Session | null; busy: boolean; error: string; login: (email: string, password: string) => Promise<void>; resume: () => Promise<void>; logout: () => Promise<void> };
const Context = createContext<SessionContext | null>(null);
export function OrderSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(() => { setSession(null); setError("Phiên đã hết hạn. Đăng nhập hoặc khôi phục phiên để tiếp tục."); }, session.expiresIn * 1000);
    return () => clearTimeout(timer);
  }, [session]);
  async function authenticate(path: string, body?: unknown) {
    if (active.current) return;
    active.current = true; setBusy(true); setError("");
    try {
      const next = parseSession(await apiRequest(path, { method: "POST", headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) }));
      setSession(next);
    } catch (e) { setError(userError(e, "auth")); }
    finally { active.current = false; setBusy(false); }
  }
  async function logout() {
    if (active.current) return;
    active.current = true; setBusy(true); setSession(null);
    // Access token stays in memory. Explicit logout clears this tab's pending address data.
    try { clearOrderSession(sessionStorage); } catch { /* Storage can be unavailable. */ }
    try { await apiRequest("/auth/logout", { method: "POST" }); setError(""); }
    catch { setError("Đã khóa phiên trên trình duyệt này. Chưa xác nhận được việc đăng xuất trên hệ thống; hãy thử lại khi kết nối phục hồi."); }
    finally { active.current = false; setBusy(false); }
  }
  return <Context.Provider value={{ session, busy, error, login: (email, password) => authenticate("/auth/login", { email, password }), resume: () => authenticate("/auth/refresh"), logout }}>
    <header className="border-b border-slate-200 bg-white">
      <nav aria-label="Điều hướng chính" className="mx-auto flex max-w-6xl flex-wrap items-center gap-5 px-6 py-5 text-sm">
        <Link href="/" className="mr-auto text-xl font-bold text-teal-800">Commerce</Link>
        <Link href="/checkout">Đặt hàng</Link><Link href="/orders">Đơn của tôi</Link>
        {session?.user.role === "ADMIN" && <Link href="/admin/orders">Quản lý đơn</Link>}
        {session && <><span>{session.user.fullName}</span><button type="button" disabled={busy} onClick={() => void logout()} className="text-teal-800 underline">Đăng xuất</button></>}
      </nav>
    </header>
    {children}
  </Context.Provider>;
}
export function useOrderSession() { const value = useContext(Context); if (!value) throw new Error("OrderSessionProvider is required"); return value; }
export function SessionGate({ admin = false, children }: { admin?: boolean; children: (session: Session) => ReactNode }) {
  const { session, busy, error, login, resume } = useOrderSession();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget, data = new FormData(form);
    const email = String(data.get("email")), password = String(data.get("password"));
    form.reset();
    await login(email, password);
  }
  if (!session) return <section className="order-card mx-auto max-w-md">
    <h2 className="text-xl font-semibold">Đăng nhập để tiếp tục</h2>
    <p className="mt-2 text-sm text-slate-600">Sử dụng tài khoản cửa hàng để xem và xử lý đơn hàng.</p>
    <form onSubmit={submit} className="mt-6 space-y-4">
      <label className="order-label">Email<input className="order-input" name="email" type="email" autoComplete="username" required disabled={busy} /></label>
      <label className="order-label">Mật khẩu<input className="order-input" name="password" type="password" autoComplete="current-password" required disabled={busy} /></label>
      <button className="order-button w-full" disabled={busy}>{busy ? "Đang kết nối…" : "Đăng nhập"}</button>
    </form>
    <button className="mt-4 text-sm text-teal-800 underline" disabled={busy} onClick={() => void resume()}>Khôi phục phiên đã đăng nhập</button>
    {error && <p role="alert" className="order-error mt-4">{error}</p>}
  </section>;
  if (admin !== (session.user.role === "ADMIN")) return <div className="order-card" role="alert">{admin ? "Trang này chỉ dành cho quản trị viên." : "Tài khoản quản trị viên không dùng để đặt hàng. Mở trang quản lý đơn để tiếp tục."} <Link href={admin ? "/orders" : "/admin/orders"} className="text-teal-800 underline">Về trang đơn hàng</Link></div>;
  return <div key={session.user.id}>{children(session)}</div>;
}
