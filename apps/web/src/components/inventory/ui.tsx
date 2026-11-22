"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ApiError } from "@/lib/api-client";
import { inventoryError } from "@/lib/inventory";

export function Icon({
  name,
  size = 20,
}: {
  name:
    | "box"
    | "grid"
    | "search"
    | "plus"
    | "refresh"
    | "history"
    | "edit"
    | "close"
    | "check"
    | "alert"
    | "logout"
    | "menu"
    | "layers";
  size?: number;
}) {
  const paths = {
    box: (
      <>
        <path d="m12 3 9 5-9 5-9-5 9-5Z" />
        <path d="M3 8v9l9 5 9-5V8M12 13v9M7.5 5.5l9 5" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: (
      <>
        <path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5" />
      </>
    ),
    history: (
      <>
        <path d="M3 11a9 9 0 1 1 2.5 7M3 4v7h7" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    edit: (
      <>
        <path d="m15 4 5 5M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15l-1 6 1-1Z" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    alert: (
      <>
        <path d="m12 3 10 18H2L12 3Z" />
        <path d="M12 9v5m0 3h.01" />
      </>
    ),
    logout: (
      <>
        <path d="M9 4H4v16h5m5-12 4 4-4 4m-6-4h12" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    layers: (
      <>
        <path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  return (
    <div className="inv-error" role="alert">
      <Icon name="alert" />
      <div>
        <p>{inventoryError(error)}</p>
        {error instanceof ApiError && error.requestId && (
          <small>Mã yêu cầu: {error.requestId}</small>
        )}
      </div>
    </div>
  );
}

export function Modal({
  title,
  subtitle,
  children,
  onClose,
  locked = false,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  locked?: boolean;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`inv-modal ${wide ? "inv-modal-wide" : ""}`}
      aria-labelledby="inv-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!locked) onClose();
      }}
    >
      <div className="inv-modal-heading">
        <div>
          <p className="inv-eyebrow">QUẢN LÝ KHO</p>
          <h2 id="inv-dialog-title">{title}</h2>
          {subtitle && <p className="inv-muted">{subtitle}</p>}
        </div>
        <button
          type="button"
          className="inv-icon-button"
          aria-label="Đóng cửa sổ"
          onClick={onClose}
          disabled={locked}
        >
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export const number = (value: number) =>
  new Intl.NumberFormat("vi-VN").format(value);
export const dateTime = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Bangkok",
  }).format(new Date(value));
