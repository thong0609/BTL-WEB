"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { getCatalogHealth } from "@/lib/health";

type State =
  | { kind: "idle" | "loading" }
  | { kind: "success"; checkedAt: string }
  | { kind: "error"; message: string; requestId?: string };

export function ConnectionCheck() {
  const [state, setState] = useState<State>({ kind: "idle" });
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function check() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState({ kind: "loading" });
    try {
      await getCatalogHealth(controller.signal);
      if (!controller.signal.aborted) {
        setState({ kind: "success", checkedAt: new Date().toLocaleTimeString("vi-VN") });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setState({ kind: "error", message: error instanceof ApiError ? error.message : "Không kiểm tra được kết nối.", requestId: error instanceof ApiError ? error.requestId : undefined });
      }
    }
  }

  return (
    <section aria-label="Kết quả kiểm tra" aria-busy={state.kind === "loading"} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div role="status" aria-live="polite" className="min-h-24">
        {state.kind === "idle" && <><h2 className="font-semibold">Sẵn sàng kiểm tra</h2><p className="mt-2 text-sm text-slate-600">Bấm nút bên dưới để gửi yêu cầu.</p></>}
        {state.kind === "loading" && <p className="font-medium text-sky-700">Đang kiểm tra kết nối…</p>}
        {state.kind === "success" && <><h2 className="font-semibold text-teal-700">Kết nối thành công</h2><p className="mt-2 text-sm text-slate-600">Catalog đang hoạt động · Kiểm tra lúc {state.checkedAt}</p></>}
        {state.kind === "error" && <><h2 className="font-semibold text-red-700">Kiểm tra thất bại</h2><p className="mt-2 text-sm text-slate-600">{state.message}</p>{state.requestId && <p className="mt-2 break-all text-xs text-slate-500">Mã yêu cầu: {state.requestId}</p>}</>}
      </div>
      <button type="button" onClick={check} disabled={state.kind === "loading"} className="mt-5 rounded-lg bg-teal-700 px-5 py-3 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60">
        {state.kind === "loading" ? "Đang kiểm tra…" : state.kind === "idle" ? "Kiểm tra kết nối" : "Kiểm tra lại"}
      </button>
    </section>
  );
}
