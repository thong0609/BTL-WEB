"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { formatMoney, orderBase, orderGet, parsePage, paymentLabels, statusLabels, userError, type OrderPage, type OrderStatus } from "@/lib/orders";
import { SessionGate, type Session } from "./order-session";

export function OrderList({ admin = false }: { admin?: boolean }) { return <SessionGate admin={admin}>{(session) => <List session={session} admin={admin} />}</SessionGate>; }
function List({ session, admin }: { session: Session; admin: boolean }) {
  const [filter, setFilter] = useState(""), [query, setQuery] = useState(""), [page, setPage] = useState(1), [reload, setReload] = useState(0);
  const [state, setState] = useState<{ data?: OrderPage; error?: string; key?: string }>({});
  const params = new URLSearchParams({ page: String(page), pageSize: "20", ...(filter ? { status: filter } : {}), ...(admin && query ? { q: query } : {}) });
  const path = `${orderBase(admin)}?${params}`;
  const key = `${path}:${reload}`;
  const loading = state.key !== key;
  useEffect(() => {
    const controller = new AbortController();
    orderGet(path, session.accessToken, parsePage, controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ data, key });
    }).catch((e) => { if (!controller.signal.aborted) setState({ error: userError(e), key }); });
    return () => controller.abort();
  }, [path, key, session.accessToken]);
  return <section className="order-card" aria-busy={loading}>
    <div className="flex flex-wrap items-end gap-4">
      <label className="order-label">Trạng thái<select className="order-input" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }}><option value="">Tất cả</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {admin && <form onSubmit={(e) => { e.preventDefault(); setQuery(String(new FormData(e.currentTarget).get("q")).trim()); setPage(1); }} className="flex items-end gap-2"><label className="order-label">Tìm mã đơn<input name="q" className="order-input" maxLength={100} type="search" /></label><button className="order-secondary">Tìm</button></form>}
      <button className="order-secondary ml-auto" disabled={loading} onClick={() => setReload((n) => n + 1)}>Tải lại</button>
    </div>
    <div role="status" aria-live="polite" className="mt-6">{loading && "Đang tải đơn hàng…"}</div>
    {!loading && state.error && <p role="alert" className="order-error">{state.error}</p>}
    {!loading && state.data && <>
      {!state.data.items.length ? <p className="py-8 text-center text-slate-500">Chưa có đơn hàng phù hợp.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><caption className="sr-only">Danh sách đơn hàng</caption><thead className="border-b border-slate-200 text-slate-500"><tr>{["Mã đơn", "Ngày đặt", "Trạng thái", "Thanh toán", "Tổng tiền"].map((label) => <th key={label} className="px-3 py-4 font-medium">{label}</th>)}</tr></thead><tbody>{state.data.items.map((order) => <tr key={order.id} className="border-b border-slate-100"><td className="px-3 py-5"><Link href={`${orderBase(admin)}/${order.id}`} className="font-semibold text-teal-800 underline">{order.orderNumber}</Link></td><td className="px-3 py-5">{new Date(order.createdAt).toLocaleDateString("vi-VN")}</td><td className="px-3 py-5"><StatusBadge status={order.status} /></td><td className="px-3 py-5">{order.paymentStatus ? paymentLabels[order.paymentStatus] : "Đang khởi tạo"}</td><td className="px-3 py-5 whitespace-nowrap">{formatMoney(order.totalAmount)}</td></tr>)}</tbody></table></div>}
      <div className="mt-6 flex items-center justify-between gap-4 text-sm"><span>{state.data.total} đơn · Trang {page}</span><div className="flex gap-2"><button className="order-secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Trang trước</button><button className="order-secondary" disabled={page * state.data.pageSize >= state.data.total} onClick={() => setPage(page + 1)}>Trang sau</button></div></div>
    </>}
  </section>;
}
export function StatusBadge({ status }: { status: OrderStatus }) { return <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${["COMPLETED"].includes(status) ? "bg-teal-50 text-teal-800" : ["CANCELLED", "REJECTED"].includes(status) ? "bg-slate-100 text-slate-600" : "bg-amber-50 text-amber-900"}`}>{statusLabels[status]}</span>; }
