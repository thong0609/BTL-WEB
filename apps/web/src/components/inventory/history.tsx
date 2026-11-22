"use client";

import { useEffect, useState } from "react";
import type { InventoryApi, Movement, Page, Stock } from "@/lib/inventory";
import { ErrorNotice, Icon, Modal, dateTime, number } from "./ui";

const labels: Record<string, string> = {
  RECEIPT: "Nhập hàng",
  ADJUSTMENT: "Điều chỉnh",
  RESERVE: "Giữ hàng",
  RELEASE: "Giải phóng",
  COMMIT: "Xuất hàng",
};
const signed = (value: number) => `${value > 0 ? "+" : ""}${number(value)}`;

export function History({
  stock,
  title,
  api,
  onClose,
}: {
  stock: Stock;
  title: string;
  api: InventoryApi;
  onClose: () => void;
}) {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<{
    data?: Page<Movement>;
    error?: unknown;
    loading: boolean;
  }>({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    api
      .movements(stock.productId, page, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ error, loading: false });
      });
    return () => controller.abort();
  }, [api, stock.productId, page, retry]);
  function navigate(next: number) {
    setState({ loading: true });
    setPage(next);
  }
  return (
    <Modal title="Lịch sử biến động" subtitle={title} onClose={onClose} wide>
      <div className="inv-history-body" aria-busy={state.loading}>
        <p className="inv-help inv-history-id">
          Mã sản phẩm: {stock.productId}
        </p>
        {state.loading ? (
          <div className="inv-empty" role="status">
            <span className="inv-spinner" />
            Đang tải lịch sử…
          </div>
        ) : state.error ? (
          <>
            <ErrorNotice error={state.error} />
            <button
              className="inv-button"
              onClick={() => {
                setState({ loading: true });
                setRetry((x) => x + 1);
              }}
            >
              Thử lại
            </button>
          </>
        ) : !state.data?.items.length ? (
          <div className="inv-empty">
            <Icon name="history" size={32} />
            <h3>Chưa có biến động</h3>
            <p>Lịch sử sẽ xuất hiện sau khi nhập hàng hoặc xử lý đơn.</p>
          </div>
        ) : (
          <>
            <div className="inv-table-scroll" tabIndex={0} role="region" aria-label="Lịch sử kho, cuộn ngang để xem đầy đủ">
              <table className="inv-table inv-history-table">
                <caption className="inv-sr-only">Nhật ký biến động kho</caption>
                <thead>
                  <tr>
                    <th>Thời gian / lý do</th>
                    <th>Thao tác</th>
                    <th>Tồn thực tế</th>
                    <th>Đang giữ</th>
                    <th>
                      Sau thao tác
                      <br />
                      <small>Thực tế / giữ</small>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {state.data.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <strong>{dateTime(row.createdAt)}</strong>
                        <span className="inv-history-reason">{row.reason}</span>
                      </td>
                      <td>
                        <span
                          className={`inv-badge ${row.movementType === "RECEIPT" ? "inv-badge-green" : "inv-badge-neutral"}`}
                        >
                          {labels[row.movementType] ?? row.movementType}
                        </span>
                      </td>
                      <td className={row.onHandDelta > 0 ? "inv-positive" : ""}>
                        {signed(row.onHandDelta)}
                      </td>
                      <td>{signed(row.reservedDelta)}</td>
                      <td>
                        {number(row.onHandAfter)} / {number(row.reservedAfter)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="inv-pagination">
              <span>{number(state.data.total)} biến động</span>
              <div>
                <button
                  onClick={() => navigate(page - 1)}
                  disabled={page === 1}
                >
                  Trước
                </button>
                <span>Trang {page}</span>
                <button
                  onClick={() => navigate(page + 1)}
                  disabled={page * 10 >= state.data.total}
                >
                  Sau
                </button>
              </div>
            </div>
          </>
        )}
      </div>
      <div className="inv-modal-actions">
        <button className="inv-button" onClick={onClose}>
          Đóng lịch sử
        </button>
      </div>
    </Modal>
  );
}
