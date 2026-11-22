"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError } from "@/lib/api-client";
import { cartKey, mutate, readPending, saveCart, type PendingRequest } from "@/lib/order-intent";
import { createPayload, formatMoney, object, orderPost, parseAccepted, parseCart, parseQuote, userError, type CartItem, type CreateOrder, type Quote } from "@/lib/orders";
import { SessionGate, type Session } from "./order-session";

function subscribe(listener: () => void) { window.addEventListener("commerce:cart-changed", listener); return () => window.removeEventListener("commerce:cart-changed", listener); }
function snapshot() { try { return sessionStorage.getItem(cartKey) ?? "[]"; } catch { return "[]"; } }
function browserCart(raw: string) { try { return parseCart(JSON.parse(raw)); } catch { return []; } }
export function OrderCheckout() { return <SessionGate>{(session) => <Checkout session={session} />}</SessionGate>; }
function Checkout({ session }: { session: Session }) {
  const router = useRouter();
  const raw = useSyncExternalStore(subscribe, snapshot, () => "[]");
  const cart = browserCart(raw);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [pending, setPending] = useState<PendingRequest | null>(null);
  const active = useRef(false);
  useEffect(() => {
    // Read after hydration; a reload can retry the exact saved body without retyping PII.
    Promise.resolve().then(() => {
      try { setPending(readPending(sessionStorage, session.user.id, "/orders")); }
      catch { setError("Không đọc được yêu cầu đang chờ. Hãy bật bộ nhớ phiên của trình duyệt để đặt hàng an toàn."); }
    });
  }, [session.user.id]);
  async function getQuote() {
    if (active.current || !cart.length) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    try { setQuote(await orderPost("/orders/quote", session.accessToken, { items: cart }, parseQuote)); }
    catch (e) { setError(userError(e)); }
    finally { active.current = false; setBusy(false); }
  }
  async function send(body: unknown) {
    if (active.current) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    let accepted = false;
    try {
      const result = await mutate(sessionStorage, session.user.id, "/orders", body, (intent) => orderPost(intent.path, session.accessToken, intent.body, parseAccepted, intent.key));
      accepted = true;
      setPending(null);
      try { saveCart([]); } catch { /* Accepted order remains navigable if storage becomes full. */ }
      router.push(`/orders/${result.orderId}`);
    } catch (e) {
      try { setPending(readPending(sessionStorage, session.user.id, "/orders")); } catch { /* Keep original error. */ }
      if (e instanceof ApiError && e.code === "PRICE_CHANGED") {
        try { const fresh = parseQuote(object(e.details).quote); setQuote(fresh); setNotice("Giá đã thay đổi. Kiểm tra bảng giá mới và bấm đặt hàng lần nữa nếu đồng ý."); }
        catch { setQuote(null); }
      }
      setError(userError(e));
    } finally {
      if (!accepted) { active.current = false; setBusy(false); }
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!quote || pending) return;
    const data = new FormData(event.currentTarget);
    const body: CreateOrder = createPayload(quote, { name: String(data.get("name")).trim(), phone: String(data.get("phone")).trim(), address: String(data.get("address")).trim() }, data.get("paymentMethod") === "SIMULATED" ? "SIMULATED" : "COD", String(data.get("note")).trim());
    await send(body);
  }
  function changeQuantity(item: CartItem, value: number) {
    if (!Number.isInteger(value) || value < 1 || value > 999) return;
    try { saveCart(cart.map((i) => i.productId === item.productId ? { ...i, quantity: value } : i)); setQuote(null); setNotice(""); }
    catch { setError("Không lưu được giỏ hàng trên trình duyệt."); }
  }
  return <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
    <section className="order-card">
      <h2 className="text-xl font-semibold">Thông tin giao hàng</h2>
      <p className="mt-2 text-sm text-slate-600">Đơn được kiểm tra giá và tồn kho trước khi xác nhận.</p>
      {pending && <div className="mt-5 rounded-lg border border-amber-300 bg-amber-50 p-4" role="status"><p>Yêu cầu đặt hàng trước chưa rõ kết quả. Gửi lại để kiểm tra; hệ thống giữ nguyên yêu cầu cũ.</p><button className="order-button mt-3" disabled={busy} onClick={() => void send(pending.body)}>Gửi lại yêu cầu đặt hàng</button></div>}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <fieldset disabled={busy || !!pending} className="space-y-4">
          <label className="order-label">Họ tên người nhận<input name="name" className="order-input" autoComplete="shipping name" required maxLength={150} /></label>
          <label className="order-label">Số điện thoại<input name="phone" className="order-input" type="tel" autoComplete="shipping tel" required pattern="\+?[0-9]{8,15}" /></label>
          <label className="order-label">Địa chỉ giao hàng<textarea name="address" className="order-input" autoComplete="shipping street-address" required minLength={10} maxLength={1000} rows={3} /></label>
          <label className="order-label">Thanh toán<select name="paymentMethod" className="order-input"><option value="COD">Trả tiền khi nhận hàng (COD)</option><option value="SIMULATED">Thanh toán mô phỏng</option></select></label>
          <label className="order-label">Ghi chú (không bắt buộc)<textarea name="note" className="order-input" rows={2} maxLength={1000} /></label>
        </fieldset>
        {quote && <button className="order-button w-full" disabled={busy || !!pending}>{busy ? "Đang gửi yêu cầu…" : `Đặt hàng · ${formatMoney(quote.totalAmount)}`}</button>}
      </form>
      {notice && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-amber-900">{notice}</p>}
      {error && <p role="alert" className="order-error mt-4">{error}</p>}
    </section>
    <section className="order-card h-fit" aria-label="Giỏ hàng và báo giá">
      <h2 className="text-xl font-semibold">Đơn hàng của bạn</h2>
      {!cart.length && !quote && <p className="mt-6 text-slate-600">Giỏ hàng đang trống. Hãy chọn sản phẩm ở cửa hàng rồi quay lại đây. <Link href="/" className="text-teal-800 underline">Về trang chủ</Link></p>}
      {quote ? <QuoteSummary quote={quote} /> : !!cart.length && <div className="mt-4 space-y-3">{cart.map((item, index) => <label key={item.productId} className="flex items-center justify-between gap-4 text-sm">Sản phẩm {index + 1}<input aria-label={`Số lượng sản phẩm ${index + 1}`} type="number" min={1} max={999} className="order-input w-24" value={item.quantity} disabled={busy || !!pending} onChange={(e) => changeQuantity(item, Number(e.target.value))} /></label>)}</div>}
      {!!cart.length && <button className="order-secondary mt-5 w-full" disabled={busy || !!pending} onClick={() => void getQuote()}>{quote ? "Kiểm tra lại giá" : "Xem giá và phí giao hàng"}</button>}
      <p className="mt-5 text-sm leading-6 text-slate-500">Gửi yêu cầu chưa có nghĩa là đơn đã được xác nhận. Bạn có thể theo dõi kết quả ở trang chi tiết.</p>
    </section>
  </div>;
}
export function QuoteSummary({ quote }: { quote: Pick<Quote, "items" | "subtotalAmount" | "shippingFeeAmount" | "totalAmount"> }) {
  return <div className="mt-5">
    <ul className="divide-y divide-slate-100">{quote.items.map((item) => <li key={item.productId} className="flex justify-between gap-4 py-4"><div><p className="font-medium">{item.name}</p><p className="mt-1 text-sm text-slate-500">{item.quantity} × {formatMoney(item.unitPriceAmount)}</p></div><span className="whitespace-nowrap text-sm">{formatMoney(item.lineTotalAmount)}</span></li>)}</ul>
    <dl className="space-y-3 border-t border-slate-200 pt-4 text-sm"><div className="flex justify-between"><dt>Tiền hàng</dt><dd>{formatMoney(quote.subtotalAmount)}</dd></div><div className="flex justify-between"><dt>Phí giao hàng</dt><dd>{formatMoney(quote.shippingFeeAmount)}</dd></div><div className="flex justify-between text-lg font-semibold"><dt>Tổng cộng</dt><dd>{formatMoney(quote.totalAmount)}</dd></div></dl>
  </div>;
}
