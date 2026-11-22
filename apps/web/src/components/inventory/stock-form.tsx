"use client";

import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import {
  InventoryAttempt,
  MAX_INTEGER,
  UUID_PATTERN,
  unknownOutcome,
  type InventoryApi,
  type Stock,
  type StockAdjustment,
  type StockCreate,
} from "@/lib/inventory";
import { previewProducts } from "@/lib/inventory-preview";
import { ErrorNotice, Icon, Modal, number } from "./ui";

export function StockForm({
  stock,
  title,
  api,
  preview,
  onClose,
  onSuccess,
  onConflict,
}: {
  stock?: Stock;
  title?: string;
  api: InventoryApi;
  preview: boolean;
  onClose: () => void;
  onSuccess: (stock: Stock) => void;
  onConflict: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [uncertain, setUncertain] = useState(false);
  const [direction, setDirection] = useState("receipt");
  const [quantity, setQuantity] = useState("");
  const attempt = useRef<InventoryAttempt | null>(null);
  const sending = useRef(false);
  const delta = (direction === "receipt" ? 1 : -1) * Number(quantity);
  const next = stock ? stock.onHandQuantity + delta : 0;
  const belowReserved = !!stock && next < stock.reservedQuantity;
  const conflict =
    error instanceof ApiError &&
    ["STOCK_VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT"].includes(error.code);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current || conflict) return;
    const fields = new FormData(event.currentTarget);
    let body: StockCreate | StockAdjustment;
    if (uncertain && attempt.current) body = attempt.current.body;
    else if (stock) {
      if (
        !Number.isInteger(delta) ||
        delta === 0 ||
        Math.abs(delta) > MAX_INTEGER ||
        belowReserved ||
        next > MAX_INTEGER
      )
        return;
      body = {
        productId: stock.productId,
        delta,
        reason: String(fields.get("reason")).trim(),
        expectedVersion: stock.version,
      };
    } else {
      const productId = String(fields.get("productId")).trim();
      if (!UUID_PATTERN.test(productId)) {
        setError(
          new ApiError(
            "Mã sản phẩm phải là UUID hợp lệ.",
            "VALIDATION_ERROR",
            400,
          ),
        );
        return;
      }
      body = { productId, lowStockThreshold: Number(fields.get("threshold")) };
    }
    if (
      !attempt.current ||
      JSON.stringify(attempt.current.body) !== JSON.stringify(body)
    )
      attempt.current = new InventoryAttempt(body);
    sending.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const result =
        "delta" in body
          ? await api.adjust(body, attempt.current.key)
          : await api.initialize(body, attempt.current.key);
      onSuccess(result);
    } catch (cause) {
      setError(cause);
      setUncertain(unknownOutcome(cause));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return (
    <Modal
      title={stock ? "Điều chỉnh tồn kho" : "Khởi tạo mặt hàng"}
      subtitle={
        stock
          ? title
          : "Thêm sản phẩm từ danh mục vào kho, với tồn ban đầu bằng 0."
      }
      onClose={onClose}
      locked={busy || uncertain}
    >
      <form onSubmit={submit} className="inv-form">
        <fieldset disabled={busy || uncertain || conflict}>
          {stock ? (
            <>
              <div className="inv-stock-summary">
                <div>
                  <span>Tồn thực tế</span>
                  <strong>{number(stock.onHandQuantity)}</strong>
                </div>
                <div>
                  <span>Đang giữ</span>
                  <strong>{number(stock.reservedQuantity)}</strong>
                </div>
                <div>
                  <span>Có thể bán</span>
                  <strong>{number(stock.availableQuantity)}</strong>
                </div>
              </div>
              <div
                className="inv-segment"
                role="group"
                aria-label="Loại điều chỉnh"
              >
                <button
                  type="button"
                  aria-pressed={direction === "receipt"}
                  onClick={() => setDirection("receipt")}
                >
                  <Icon name="plus" /> Nhập thêm hàng
                </button>
                <button
                  type="button"
                  aria-pressed={direction === "reduce"}
                  onClick={() => setDirection("reduce")}
                >
                  <Icon name="edit" /> Giảm tồn kho
                </button>
              </div>
              <label>
                Số lượng (bắt buộc)
                <input
                  type="number"
                  min="1"
                  max={MAX_INTEGER}
                  step="1"
                  required
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="Nhập số lượng"
                  autoFocus
                />
              </label>
              <label>
                Lý do điều chỉnh (bắt buộc)
                <textarea
                  name="reason"
                  required
                  maxLength={1000}
                  rows={3}
                  placeholder="Ví dụ: Nhập hàng từ nhà cung cấp, kiểm kê thực tế…"
                  onChange={(e) =>
                    e.target.setCustomValidity(
                      e.target.value.trim() ? "" : "Vui lòng nhập lý do.",
                    )
                  }
                />
              </label>
              <div
                className={`inv-after ${belowReserved ? "inv-after-error" : ""}`}
              >
                <span>Tồn thực tế sau điều chỉnh</span>
                <strong>{number(next)}</strong>
              </div>
              {belowReserved ? (
                <p className="inv-field-error" role="alert">
                  Tồn thực tế phải từ {number(stock.reservedQuantity)} trở lên
                  vì đã có hàng được giữ cho đơn.
                </p>
              ) : (
                <p className="inv-help">
                  Lượng đang giữ được cập nhật theo đơn hàng, không chỉnh trực
                  tiếp tại đây.
                </p>
              )}
            </>
          ) : (
            <>
              {preview ? (
                <label>
                  Sản phẩm (bắt buộc)
                  <select name="productId" required defaultValue="">
                    <option value="" disabled>
                      Chọn sản phẩm từ danh mục
                    </option>
                    {previewProducts.map((p) => (
                      <option key={p.productId} value={p.productId}>
                        {p.sku} · {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label>
                  Mã sản phẩm (bắt buộc)
                  <input
                    name="productId"
                    required
                    pattern={UUID_PATTERN.source}
                    placeholder="UUID của sản phẩm trong danh mục"
                    autoFocus
                  />
                  <span className="inv-help">
                    Sản phẩm cần tồn tại trong danh mục trước khi khởi tạo kho.
                  </span>
                </label>
              )}
              <label>
                Ngưỡng cảnh báo sắp hết
                <input
                  type="number"
                  name="threshold"
                  min="0"
                  max={MAX_INTEGER}
                  step="1"
                  defaultValue="5"
                  required
                />
                <span className="inv-help">
                  Cảnh báo khi lượng có thể bán bằng hoặc thấp hơn ngưỡng này.
                </span>
              </label>
              <div className="inv-info">
                <Icon name="box" />
                <p>
                  Khởi tạo không tự nhập hàng. Sau khi thêm mặt hàng, chọn{" "}
                  <strong>Điều chỉnh</strong> để ghi nhận lượng nhập.
                </p>
              </div>
            </>
          )}
        </fieldset>
        {error !== undefined && <ErrorNotice error={error} />}
        {uncertain && (
          <p className="inv-help" role="status">
            Chưa xác định yêu cầu đã được lưu hay chưa. Giữ nguyên nội dung và
            bấm kiểm tra lại để tránh nhập hàng hai lần.
          </p>
        )}
        <div className="inv-modal-actions">
          <button
            type="button"
            className="inv-button inv-button-plain"
            onClick={onClose}
            disabled={busy || uncertain}
          >
            Hủy
          </button>
          {conflict ? (
            <button
              type="button"
              className="inv-button inv-button-primary"
              onClick={onConflict}
            >
              Đóng và tải tồn mới
            </button>
          ) : (
            <button
              className="inv-button inv-button-primary"
              type="submit"
              disabled={
                busy ||
                (!uncertain &&
                  (belowReserved || (!!stock && (!quantity || delta === 0))))
              }
            >
              {busy
                ? "Đang lưu…"
                : uncertain
                  ? "Kiểm tra lại yêu cầu"
                  : stock
                    ? "Xác nhận điều chỉnh"
                    : "Khởi tạo mặt hàng"}
            </button>
          )}
        </div>
      </form>
    </Modal>
  );
}
