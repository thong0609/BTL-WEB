"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api-client";
import { mutate, readPending, type PendingRequest } from "@/lib/order-intent";
import { actionLabels, actionPath, isUuid, orderBase, orderGet, orderPost, parseAction, parseOrder, paymentLabels, shouldPoll, statusLabels, userError, type Order, type OrderAction } from "@/lib/orders";
import { QuoteSummary } from "./order-checkout";
import { StatusBadge } from "./order-list";
import { SessionGate, type Session } from "./order-session";

export function OrderDetail({ id, admin = false }: { id: string; admin?: boolean }) {
  if (!isUuid(id)) return <p role="alert" className="order-card">Mã đơn không hợp lệ.</p>;
  return <SessionGate admin={admin}>{(session) => <Detail key={id} session={session} id={id} admin={admin} />}</SessionGate>;
}
function Detail({ session, id, admin }: { session: Session; id: string; admin: boolean }) {
  const [order, setOrder] = useState<Order | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0), [busy, setBusy] = useState(false), [needsRead, setNeedsRead] = useState(false);
  const [selected, setSelected] = useState<OrderAction | null>(null), [pending, setPending] = useState<PendingRequest | null>(null);
  const active = useRef(false);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      try {
        for (const action of Object.keys(actionLabels) as OrderAction[]) {
          if (!admin && action !== "CANCEL") continue;
          const found = readPending(sessionStorage, session.user.id, actionPath(id, action, admin));
          if (found && !cancelled) { setPending(found); break; }
        }
      } catch { if (!cancelled) setError("Không đọc được thao tác đang chờ trên trình duyệt."); }
    });
    return () => { cancelled = true; };
  }, [id, admin, session.user.id]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      let poll = true;
      try {
        const result = await orderGet(`${orderBase(admin)}/${id}`, session.accessToken, parseOrder, controller.signal);
        if (result.id !== id || (!admin && result.customerId !== session.user.id)) throw new ApiError("Invalid order reference", "INVALID_RESPONSE", 502);
        if (!controller.signal.aborted) { setOrder(result); setError(""); setNeedsRead(false); poll = shouldPoll(result); }
      } catch (e) {
        if (!controller.signal.aborted) { setError(userError(e)); poll = !(e instanceof ApiError && [401, 403, 404].includes(e.status)); }
      } finally {
        if (!controller.signal.aborted && poll) timer = setTimeout(() => { if (document.visibilityState === "visible") setRevision((n) => n + 1); else timer = setTimeout(() => setRevision((n) => n + 1), 15000); }, 5000);
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, admin, revision, session.accessToken, session.user.id]);
  async function send(path: string, body: unknown) {
    if (active.current) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await mutate(sessionStorage, session.user.id, path, body, (intent) => orderPost(intent.path, session.accessToken, intent.body, (value) => {
        const parsed = parseAction(value);
        if (parsed.orderId !== id) throw new ApiError("Invalid action reference", "INVALID_RESPONSE", 502);
        return parsed;
      }, intent.key));
      setPending(null); setSelected(null); setNeedsRead(true);
      setNotice(result.workflowState === "DONE" ? "Thao tác đã được ghi nhận." : "Đã tiếp nhận yêu cầu. Đơn chỉ hoàn tất bước này sau khi hệ thống xử lý xong.");
    } catch (e) {
      try { setPending(readPending(sessionStorage, session.user.id, path)); } catch { /* Preserve the original error. */ }
      setError(userError(e));
    } finally { active.current = false; setBusy(false); setRevision((n) => n + 1); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !order || pending) return;
    const data = new FormData(event.currentTarget);
    const body = selected === "CANCEL" || selected === "RECORD_EXCEPTION" ? { reason: String(data.get("reason")).trim() } : selected === "COMPLETE" ? { delivered: data.get("delivered") === "on", ...(order.paymentMethod === "COD" ? { codCollected: data.get("codCollected") === "on" } : {}) } : {};
    await send(actionPath(id, selected, admin), body);
  }
  return <>
    <div className="mb-6 flex flex-wrap items-center gap-4"><Link href={orderBase(admin)} className="text-sm text-teal-800 underline">← Danh sách đơn</Link><button className="order-secondary ml-auto" disabled={busy} onClick={() => setRevision((n) => n + 1)}>Tải lại trạng thái</button></div>
    {error && <p role="alert" className="order-error mb-6">{error}</p>}
    {notice && <p role="status" className="mb-6 rounded-lg bg-teal-50 p-4 text-teal-900">{notice}</p>}
    {pending && <div role="status" className="order-card mb-6 border-amber-300"><p>Thao tác trước chưa rõ kết quả. Gửi lại đúng yêu cầu để kiểm tra an toàn.</p><button className="order-button mt-4" disabled={busy} onClick={() => void send(pending.path, pending.body)}>Gửi lại thao tác</button></div>}
    {!order ? !error && <p role="status">Đang tải chi tiết đơn…</p> : <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <div className="space-y-6">
        <section className="order-card"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">{order.orderNumber}</h2><StatusBadge status={order.status} /></div><p className="mt-2 text-sm text-slate-500">Đặt lúc {new Date(order.createdAt).toLocaleString("vi-VN")}</p>
          {shouldPoll(order) && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Hệ thống đang xử lý yêu cầu. Trạng thái được tự cập nhật; vui lòng không tạo lại đơn.</p>}
          {order.workflow.requiresAttention && <p role="status" className="order-error mt-4">Đơn cần được cửa hàng kiểm tra. Trạng thái hàng và tiền được giữ nguyên cho đến khi xác minh xong.</p>}
          <QuoteSummary quote={order} />
        </section>
        <section className="order-card"><h2 className="text-lg font-semibold">Lịch sử đơn hàng</h2><ol className="mt-4 space-y-5">{order.history.map((history, index) => <li key={`${history.createdAt}-${index}`} className="border-l-2 border-teal-200 pl-4"><p className="font-medium">{statusLabels[history.toStatus]}</p><p className="mt-1 text-xs text-slate-500">{new Date(history.createdAt).toLocaleString("vi-VN")}</p>{history.reason && <p className="mt-2 break-words text-sm">{history.reason}</p>}</li>)}</ol></section>
      </div>
      <div className="space-y-6">
        <section className="order-card"><h2 className="text-lg font-semibold">Người nhận</h2><address className="mt-4 space-y-2 break-words text-sm not-italic"><p>{order.recipient.name}</p><p>{order.recipient.phone}</p><p>{order.recipient.address}</p></address>{order.note && <p className="mt-4 break-words text-sm text-slate-500">Ghi chú: {order.note}</p>}<hr className="my-5 border-slate-100" /><h3 className="font-medium">Thanh toán</h3><p className="mt-2 text-sm">{order.paymentMethod === "COD" ? "Trả tiền khi nhận hàng" : "Thanh toán mô phỏng"}</p><p className="mt-1 text-sm text-slate-600">{order.paymentStatus ? paymentLabels[order.paymentStatus] : "Đang khởi tạo"}</p></section>
        <section className="order-card"><h2 className="text-lg font-semibold">Thao tác</h2>
          {!order.allowedActions.length && <p className="mt-4 text-sm text-slate-500">Chưa có thao tác phù hợp với trạng thái đơn hiện tại.</p>}
          <div className="mt-4 flex flex-wrap gap-2">{order.allowedActions.map((action) => <button key={action} disabled={busy || !!pending || needsRead} className={action === "CANCEL" ? "order-secondary text-red-800" : "order-secondary"} onClick={() => setSelected(action)}>{actionLabels[action]}</button>)}</div>
          {selected && order.allowedActions.includes(selected) && !pending && <form className="mt-5 space-y-4 border-t border-slate-200 pt-5" onSubmit={submit}>
            <h3 className="font-medium">{actionLabels[selected]}</h3>
            {(selected === "CANCEL" || selected === "RECORD_EXCEPTION") && <label className="order-label">Lý do<textarea name="reason" className="order-input" required minLength={1} maxLength={1000} disabled={busy} /></label>}
            {selected === "DISPATCH" && <p className="text-sm text-slate-600">Đơn chỉ chuyển Đang giao khi kho xác nhận đã xuất hàng.</p>}
            {selected === "COMPLETE" && <><label className="flex gap-3 text-sm"><input type="checkbox" name="delivered" required disabled={busy} />Đã giao hàng cho người nhận</label>{order.paymentMethod === "COD" && <label className="flex gap-3 text-sm"><input type="checkbox" name="codCollected" required disabled={busy} />Đã thu đủ số tiền của đơn</label>}</>}
            <div className="flex gap-3"><button className="order-button" disabled={busy || needsRead}>{busy ? "Đang gửi…" : "Xác nhận thao tác"}</button><button type="button" className="order-secondary" disabled={busy} onClick={() => setSelected(null)}>Quay lại</button></div>
          </form>}
        </section>
      </div>
    </div>}
  </>;
}
