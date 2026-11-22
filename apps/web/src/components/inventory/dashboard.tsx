"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import {
  createInventoryApi,
  loginInventory,
  type AdminAccount,
  type Page,
  type Stock,
} from "@/lib/inventory";
import {
  createPreviewInventory,
  previewProducts,
} from "@/lib/inventory-preview";
import { History } from "./history";
import { StockForm } from "./stock-form";
import { ErrorNotice, Icon, number } from "./ui";

type DialogState =
  { kind: "initialize" } | { kind: "adjust" | "history"; stock: Stock };
type ListState = {
  loading: boolean;
  data?: Page<Stock>;
  error?: unknown;
  updatedAt?: string;
};

function SignIn({
  onSuccess,
  onPreview,
}: {
  onSuccess: (session: { accessToken: string; user: AdminAccount }) => void;
  onPreview: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError(undefined);
    try {
      const session = await loginInventory(
        String(fields.get("email")).trim(),
        String(fields.get("password")),
      );
      form.reset();
      onSuccess(session);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="inv-signin">
      <div className="inv-gate-icon">
        <Icon name="box" size={28} />
      </div>
      <p className="inv-eyebrow">KHÔNG GIAN QUẢN TRỊ</p>
      <h2>Kho hàng trong tầm tay</h2>
      <p className="inv-muted">
        Đăng nhập bằng tài khoản quản trị để xem và cập nhật tồn kho của cửa
        hàng.
      </p>
      <form className="inv-form" onSubmit={submit}>
        <fieldset disabled={busy}>
          <label>
            Email
            <input
              name="email"
              type="email"
              autoComplete="username"
              placeholder="quantri@cuahang.vn"
              required
            />
          </label>
          <label>
            Mật khẩu
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="Nhập mật khẩu"
              required
            />
          </label>
        </fieldset>
        {error !== undefined && <ErrorNotice error={error} />}
        <button
          type="submit"
          className="inv-button inv-button-primary"
          disabled={busy}
        >
          {busy ? "Đang đăng nhập…" : "Đăng nhập quản trị"}
        </button>
      </form>
      <div className="inv-signin-preview">
        <span>Muốn khám phá trước?</span>
        <button type="button" onClick={onPreview}>
          Xem thử với dữ liệu mẫu
        </button>
      </div>
    </div>
  );
}

export function InventoryDashboard({
  initialPreview = false,
}: {
  initialPreview?: boolean;
}) {
  const [mode, setMode] = useState<"live" | "preview">(
    initialPreview ? "preview" : "live",
  );
  const [previewApi] = useState(createPreviewInventory);
  const [session, setSession] = useState<{
    accessToken: string;
    user: AdminAccount;
  } | null>(null);
  const [state, setState] = useState<ListState>({ loading: initialPreview });
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [toast, setToast] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const api = useMemo(
    () =>
      mode === "preview"
        ? previewApi
        : session
          ? createInventoryApi(session.accessToken)
          : null,
    [mode, previewApi, session],
  );
  const preview = mode === "preview";
  const labels = useMemo(
    () => new Map(previewProducts.map((p) => [p.productId, p])),
    [],
  );
  const label = (stock: Stock) =>
    preview
      ? (labels.get(stock.productId)?.name ?? stock.productId)
      : `Sản phẩm ${stock.productId.slice(0, 8)}`;

  useEffect(() => {
    if (!api) return;
    const controller = new AbortController();
    api
      .list(
        {
          page,
          pageSize,
          lowStock:
            filter === "low" ? true : filter === "healthy" ? false : undefined,
        },
        controller.signal,
      )
      .then((data) => {
        if (!controller.signal.aborted)
          setState({
            loading: false,
            data,
            updatedAt: new Date().toLocaleTimeString("vi-VN", {
              hour: "2-digit",
              minute: "2-digit",
            }),
          });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ loading: false, error });
      });
    return () => controller.abort();
  }, [api, page, pageSize, filter, revision]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6000);
    return () => clearTimeout(timer);
  }, [toast]);

  function refresh() {
    setState({ loading: true });
    setRevision((x) => x + 1);
  }
  function switchMode(next: "live" | "preview") {
    setMode(next);
    setDialog(null);
    setQuery("");
    setPage(1);
    setFilter("all");
    setToast("");
    setState({ loading: next === "preview" || !!session });
  }
  function changeFilter(next: string) {
    setFilter(next);
    setPage(1);
    setQuery("");
    setState({ loading: true });
  }
  function navigate(next: number) {
    setPage(next);
    setQuery("");
    setState({ loading: true });
  }
  const items = state.data?.items ?? [];
  const visible = items.filter((stock) =>
    `${label(stock)} ${stock.productId} ${preview ? labels.get(stock.productId)?.sku : ""}`
      .toLocaleLowerCase("vi")
      .includes(query.toLocaleLowerCase("vi").trim()),
  );
  const stats = [
    {
      label: "Mặt hàng",
      value: state.data ? items.length : null,
      icon: "box" as const,
      help: "Số mặt hàng trong trang",
    },
    {
      label: "Tồn thực tế",
      value: state.data
        ? items.reduce((sum, s) => sum + s.onHandQuantity, 0)
        : null,
      icon: "layers" as const,
      help: "Tổng số đơn vị trong trang",
    },
    {
      label: "Đang giữ cho đơn",
      value: state.data
        ? items.reduce((sum, s) => sum + s.reservedQuantity, 0)
        : null,
      icon: "history" as const,
      help: "Số đơn vị đã được giữ",
    },
    {
      label: "Cần bổ sung",
      value: state.data
        ? items.filter((s) => s.availableQuantity <= s.lowStockThreshold).length
        : null,
      icon: "alert" as const,
      help: "Mặt hàng chạm ngưỡng cảnh báo",
    },
  ];
  const expired = state.error instanceof ApiError && state.error.status === 401;

  return (
    <div className="inv-app">
      <a href="#inventory-main" className="inv-skip">
        Đến nội dung chính
      </a>
      <aside className={`inv-sidebar ${menuOpen ? "inv-sidebar-open" : ""}`}>
        <Link href="/" className="inv-brand">
          <span className="inv-brand-icon">
            <Icon name="box" size={25} />
          </span>
          <span>
            commerce<span className="inv-brand-sub">KHÔNG GIAN QUẢN TRỊ</span>
          </span>
        </Link>
        <div className="inv-store">
          <span className="inv-store-avatar">C</span>
          <div>
            <strong>Cửa hàng của bạn</strong>
            <small>Một cửa hàng · một kho</small>
          </div>
        </div>
        <p className="inv-nav-label">VẬN HÀNH CỬA HÀNG</p>
        <nav aria-label="Điều hướng quản trị">
          <a
            href="/admin/inventory"
            className="inv-nav-active"
            aria-current="page"
          >
            <Icon name="box" /> Tồn kho
            <span className="inv-nav-mark" />
          </a>
        </nav>
        <div className="inv-sidebar-note">
          <Icon name="layers" size={27} />
          <strong>Mọi biến động, một nơi.</strong>
          <p>
            Theo dõi lượng hàng và lịch sử để mỗi lần nhập, xuất đều rõ ràng.
          </p>
        </div>
        <div className="inv-sidebar-bottom">
          <Link href="/">Kiểm tra kết nối hệ thống</Link>
          <span>Commerce · Quản trị cửa hàng</span>
        </div>
      </aside>
      {menuOpen && (
        <button
          className="inv-mobile-backdrop"
          aria-label="Đóng menu"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <div className="inv-workspace">
        <header className="inv-topbar">
          <div className="inv-breadcrumb">
            <button
              className="inv-icon-button inv-menu-toggle"
              aria-label="Mở menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <Icon name="menu" />
            </button>
            <Icon name="grid" size={17} />
            <span>Quản trị</span>
            <span className="inv-breadcrumb-slash">/</span>
            <strong>Tồn kho</strong>
          </div>
          <div className="inv-account">
            <span className="inv-account-avatar">
              {preview
                ? "M"
                : (session?.user.name ?? session?.user.email ?? "Q")
                    .charAt(0)
                    .toUpperCase()}
            </span>
            <div>
              <strong>
                {preview
                  ? "Tài khoản minh họa"
                  : (session?.user.name ??
                    session?.user.email ??
                    "Quản trị cửa hàng")}
              </strong>
              <small>
                {preview
                  ? "Chế độ xem thử"
                  : session
                    ? "Quản trị viên"
                    : "Chưa đăng nhập"}
              </small>
            </div>
            {session && !preview && (
              <button
                className="inv-icon-button"
                aria-label="Kết thúc phiên quản trị"
                onClick={() => {
                  setSession(null);
                  setState({ loading: false });
                }}
              >
                <Icon name="logout" size={18} />
              </button>
            )}
          </div>
        </header>
        <main id="inventory-main" className="inv-main">
          <div className="inv-page-heading">
            <div>
              <p className="inv-eyebrow">VẬN HÀNH / TỒN KHO</p>
              <h1>
                Quản lý tồn kho<span className="inv-heading-dot">.</span>
              </h1>
              <p className="inv-muted">
                Nắm rõ lượng hàng. Chủ động mỗi lần nhập, xuất.
              </p>
            </div>
            <div className="inv-heading-actions">
              <button
                className="inv-button"
                onClick={() => switchMode(preview ? "live" : "preview")}
              >
                {preview ? "Kết nối dữ liệu thật" : "Xem thử giao diện"}
              </button>
              <button
                className="inv-button inv-button-primary"
                disabled={!api || state.loading}
                onClick={() => setDialog({ kind: "initialize" })}
              >
                <Icon name="plus" size={18} />
                Khởi tạo mặt hàng
              </button>
            </div>
          </div>
          {preview && (
            <div className="inv-preview-banner">
              <span className="inv-preview-label">XEM THỬ</span>
              <p>
                Đang dùng dữ liệu minh họa. Các thao tác chỉ thay đổi dữ liệu
                trong phiên này.
              </p>
            </div>
          )}
          <section
            className="inv-stat-grid"
            aria-label="Thống kê của trang hiện tại"
          >
            {stats.map((stat, i) => (
              <div
                className={`inv-stat ${i === 3 ? "inv-stat-alert" : ""}`}
                key={stat.label}
              >
                <div className="inv-stat-top">
                  <span>{stat.label}</span>
                  <span className="inv-stat-icon">
                    <Icon name={stat.icon} size={19} />
                  </span>
                </div>
                <strong>
                  {stat.value === null ? "—" : number(stat.value)}
                </strong>
                <small>{stat.help}</small>
              </div>
            ))}
          </section>
          {!api ? (
            <SignIn
              onPreview={() => switchMode("preview")}
              onSuccess={(result) => {
                setSession(result);
                setState({ loading: true });
              }}
            />
          ) : (
            <section className="inv-panel" aria-labelledby="inv-stock-heading">
              <div className="inv-panel-heading">
                <div>
                  <h2 id="inv-stock-heading">
                    Danh sách tồn kho{" "}
                    <span className="inv-count">
                      {state.data ? number(state.data.total) : "—"}
                    </span>
                  </h2>
                  <p>Có thể bán = tồn thực tế − đang giữ</p>
                </div>
                <button
                  className="inv-button inv-button-plain"
                  disabled={state.loading}
                  onClick={refresh}
                >
                  <Icon name="refresh" size={16} />
                  <span>{state.loading ? "Đang tải…" : "Làm mới"}</span>
                </button>
              </div>
              <div className="inv-toolbar">
                <div
                  className="inv-tabs"
                  role="group"
                  aria-label="Lọc theo tình trạng tồn"
                >
                  <button
                    aria-pressed={filter === "all"}
                    onClick={() => changeFilter("all")}
                    disabled={state.loading}
                  >
                    Tất cả
                  </button>
                  <button
                    aria-pressed={filter === "low"}
                    onClick={() => changeFilter("low")}
                    disabled={state.loading}
                  >
                    Cần bổ sung
                  </button>
                  <button
                    aria-pressed={filter === "healthy"}
                    onClick={() => changeFilter("healthy")}
                    disabled={state.loading}
                  >
                    Đủ hàng
                  </button>
                </div>
                <label className="inv-search">
                  <Icon name="search" size={18} />
                  <span className="inv-sr-only">
                    Tìm sản phẩm trong trang hiện tại
                  </span>
                  <input
                    type="search"
                    value={query}
                    disabled={state.loading}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Tìm trong trang hiện tại…"
                  />
                </label>
              </div>
              <div aria-busy={state.loading}>
                {state.loading ? (
                  <div className="inv-loading" role="status">
                    <div className="inv-skeleton-heading" />
                    {[0, 1, 2, 3, 4].map((i) => (
                      <div className="inv-skeleton-row" key={i}>
                        <span />
                        <span />
                        <span />
                      </div>
                    ))}
                    <span className="inv-sr-only">Đang tải tồn kho…</span>
                  </div>
                ) : state.error ? (
                  <div className="inv-panel-message">
                    <ErrorNotice error={state.error} />
                    <button
                      className="inv-button"
                      onClick={
                        expired
                          ? () => {
                              setSession(null);
                              setState({ loading: false });
                            }
                          : refresh
                      }
                    >
                      {expired ? "Đăng nhập lại" : "Thử tải lại"}
                    </button>
                  </div>
                ) : !visible.length ? (
                  <div className="inv-empty">
                    <span className="inv-empty-icon">
                      <Icon name={query ? "search" : "box"} size={28} />
                    </span>
                    <h3>
                      {query
                        ? "Không có kết quả trong trang này"
                        : filter === "all"
                          ? "Kho đang trống"
                          : "Chưa có mặt hàng trong bộ lọc"}
                    </h3>
                    <p>
                      {query
                        ? "Thử tìm bằng tên, SKU hoặc mã sản phẩm khác."
                        : "Khởi tạo một mặt hàng hoặc chọn bộ lọc khác để tiếp tục."}
                    </p>
                    {query ? (
                      <button
                        className="inv-button"
                        onClick={() => setQuery("")}
                      >
                        Xóa tìm kiếm
                      </button>
                    ) : (
                      <button
                        className="inv-button"
                        onClick={() =>
                          filter === "all"
                            ? setDialog({ kind: "initialize" })
                            : changeFilter("all")
                        }
                      >
                        {filter === "all" ? "Khởi tạo mặt hàng" : "Xem tất cả"}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="inv-table-scroll" tabIndex={0} role="region" aria-label="Bảng tồn kho, cuộn ngang để xem đầy đủ">
                    <table className="inv-table inv-stock-table">
                      <caption className="inv-sr-only">
                        Tồn kho theo từng sản phẩm
                      </caption>
                      <thead>
                        <tr>
                          <th>Sản phẩm</th>
                          <th>Tồn thực tế</th>
                          <th>Đang giữ</th>
                          <th>Có thể bán</th>
                          <th>Ngưỡng</th>
                          <th>Tình trạng</th>
                          <th>
                            <span className="inv-sr-only">Thao tác</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((stock, i) => {
                          const low =
                            stock.availableQuantity <= stock.lowStockThreshold;
                          const product = preview
                            ? labels.get(stock.productId)
                            : undefined;
                          return (
                            <tr key={stock.productId}>
                              <td>
                                <div className="inv-product">
                                  <span
                                    className={`inv-product-art inv-product-art-${i % 4}`}
                                  >
                                    <Icon name="box" size={23} />
                                  </span>
                                  <div>
                                    <strong>{label(stock)}</strong>
                                    <span>
                                      {product
                                        ? `${product.sku} · ${product.category}`
                                        : stock.productId}
                                    </span>
                                  </div>
                                </div>
                              </td>
                              <td className="inv-cell-number">
                                {number(stock.onHandQuantity)}
                              </td>
                              <td className="inv-cell-muted">
                                {number(stock.reservedQuantity)}
                              </td>
                              <td>
                                <strong
                                  className={`inv-available ${low ? "inv-available-low" : ""}`}
                                >
                                  {number(stock.availableQuantity)}
                                </strong>
                              </td>
                              <td className="inv-cell-muted">
                                {number(stock.lowStockThreshold)}
                              </td>
                              <td>
                                <span
                                  className={`inv-badge ${stock.availableQuantity === 0 ? "inv-badge-red" : low ? "inv-badge-amber" : "inv-badge-green"}`}
                                >
                                  {stock.availableQuantity === 0
                                    ? "Hết hàng"
                                    : low
                                      ? "Sắp hết"
                                      : "Đủ hàng"}
                                </span>
                              </td>
                              <td>
                                <div className="inv-row-actions">
                                  <button
                                    className="inv-icon-button"
                                    aria-label={`Lịch sử ${label(stock)}`}
                                    title="Xem lịch sử"
                                    onClick={() =>
                                      setDialog({ kind: "history", stock })
                                    }
                                  >
                                    <Icon name="history" size={18} />
                                  </button>
                                  <button
                                    className="inv-row-edit"
                                    aria-label={`Điều chỉnh ${label(stock)}`}
                                    onClick={() =>
                                      setDialog({ kind: "adjust", stock })
                                    }
                                  >
                                    <Icon name="edit" size={16} />
                                    <span>Điều chỉnh</span>
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              {state.data && !state.loading && (
                <div className="inv-pagination">
                  <div>
                    <span>
                      {query ? `${visible.length} kết quả trong trang · ` : ""}
                      {state.data.total
                        ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, state.data.total)}`
                        : "0"}{" "}
                      / {number(state.data.total)} mặt hàng
                    </span>
                    <label className="inv-page-size">
                      <span className="inv-sr-only">Số mặt hàng mỗi trang</span>
                      <select
                        value={pageSize}
                        onChange={(e) => {
                          setPageSize(Number(e.target.value));
                          navigate(1);
                        }}
                      >
                        {[10, 20, 50].map((size) => (
                          <option key={size} value={size}>
                            {size} / trang
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div>
                    <button
                      onClick={() => navigate(page - 1)}
                      disabled={page <= 1}
                    >
                      Trước
                    </button>
                    <span className="inv-page-current">{page}</span>
                    <button
                      onClick={() => navigate(page + 1)}
                      disabled={page * pageSize >= state.data.total}
                    >
                      Sau
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
          <footer className="inv-footer">
            <span>
              <Icon name="check" size={15} /> Lượng đang giữ được bảo vệ theo
              đơn hàng.
            </span>
            <span>
              {state.updatedAt
                ? `Cập nhật lúc ${state.updatedAt} · Số liệu thống kê trong trang hiện tại`
                : "Số liệu thống kê theo trang đang xem"}
            </span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="inv-toast" role="status">
          <Icon name="check" />
          <span>{toast}</span>
          <button aria-label="Đóng thông báo" onClick={() => setToast("")}>
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
      {dialog &&
        api &&
        (dialog.kind === "history" ? (
          <History
            stock={dialog.stock}
            title={label(dialog.stock)}
            api={api}
            onClose={() => setDialog(null)}
          />
        ) : (
          <StockForm
            stock={dialog.kind === "adjust" ? dialog.stock : undefined}
            title={dialog.kind === "adjust" ? label(dialog.stock) : undefined}
            api={api}
            preview={preview}
            onClose={() => setDialog(null)}
            onConflict={() => {
              setDialog(null);
              refresh();
            }}
            onSuccess={() => {
              setToast(
                dialog.kind === "initialize"
                  ? "Đã khởi tạo mặt hàng. Bạn có thể nhập hàng ngay."
                  : "Đã cập nhật tồn kho và ghi nhận lịch sử.",
              );
              setDialog(null);
              refresh();
            }}
          />
        ))}
    </div>
  );
}
