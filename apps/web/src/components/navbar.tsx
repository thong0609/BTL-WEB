"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { getSavedAdminToken } from "@/lib/catalog";

export function Navbar() {
  const pathname = usePathname();
  const [adminToken, setAdminToken] = useState<string>(() => getSavedAdminToken());
  const [showTokenInput, setShowTokenInput] = useState<boolean>(false);

  const saveToken = (val: string) => {
    setAdminToken(val);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("catalog_admin_token", val);
    }
  };

  return (
    <header className="border-b border-black bg-white sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-14 items-center">
          <div className="flex items-center space-x-6">
            <Link href="/" className="font-bold text-lg tracking-tight text-black">
              COMMERCE·CATALOG
            </Link>
            <nav className="flex space-x-2 text-sm font-medium">
              <Link
                href="/products"
                className={`px-3 py-1.5 rounded ${
                  pathname.startsWith("/products")
                    ? "bg-black text-white"
                    : "text-black hover:bg-neutral-100"
                }`}
              >
                Sản phẩm
              </Link>
              <Link
                href="/admin/products"
                className={`px-3 py-1.5 rounded ${
                  pathname.startsWith("/admin/products")
                    ? "bg-black text-white"
                    : "text-black hover:bg-neutral-100"
                }`}
              >
                Quản trị SP
              </Link>
              <Link
                href="/admin/categories"
                className={`px-3 py-1.5 rounded ${
                  pathname.startsWith("/admin/categories")
                    ? "bg-black text-white"
                    : "text-black hover:bg-neutral-100"
                }`}
              >
                Quản trị Danh mục
              </Link>
            </nav>
          </div>
          <button
            type="button"
            onClick={() => setShowTokenInput((prev) => !prev)}
            className="text-xs border border-black px-2.5 py-1 rounded hover:bg-neutral-100 font-medium"
          >
            {adminToken ? "Token Admin: Đã cấu hình" : "Cấu hình Token Admin"}
          </button>
        </div>

        {showTokenInput && (
          <div className="p-3 bg-neutral-50 border-t border-neutral-200 flex items-center space-x-3 text-xs">
            <label htmlFor="admin-token" className="font-semibold whitespace-nowrap">
              Bearer Token (ADMIN):
            </label>
            <input
              id="admin-token"
              type="text"
              placeholder="Nhập JWT Bearer token cho các thao tác quản trị..."
              value={adminToken}
              onChange={(e) => saveToken(e.target.value)}
              className="border border-black px-2.5 py-1 rounded w-full max-w-md bg-white font-mono"
            />
            {adminToken && (
              <button
                type="button"
                onClick={() => saveToken("")}
                className="text-neutral-600 hover:text-black underline"
              >
                Xóa
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
