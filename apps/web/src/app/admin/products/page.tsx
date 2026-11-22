"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  Product,
  ProductStatus,
  SortOption,
  fetchAdminCategories,
  fetchAdminProducts,
  formatVND,
  getSavedAdminToken,
  patchAdminProduct,
} from "@/lib/catalog";

export default function AdminProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [reloadTick, setReloadTick] = useState(0);
  const pageSize = 15;

  const [searchInput, setSearchInput] = useState("");
  const [minPriceInput, setMinPriceInput] = useState("");
  const [maxPriceInput, setMaxPriceInput] = useState("");

  const [appliedSearch, setAppliedSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("");
  const [appliedMinPrice, setAppliedMinPrice] = useState("");
  const [appliedMaxPrice, setAppliedMaxPrice] = useState("");
  const [sort, setSort] = useState<SortOption>("NEWEST");

  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const token = getSavedAdminToken();
    Promise.all([
      fetchAdminProducts(
        token,
        {
          page,
          pageSize,
          q: appliedSearch || undefined,
          categoryId: selectedCategory || undefined,
          status: (selectedStatus as ProductStatus) || undefined,
          minPrice: appliedMinPrice || undefined,
          maxPrice: appliedMaxPrice || undefined,
          sort,
        },
        controller.signal
      ),
      fetchAdminCategories(token, 1, 100, controller.signal).catch(() => ({ items: [] })),
    ])
      .then(([prodRes, catRes]) => {
        if (!controller.signal.aborted) {
          setProducts(prodRes.items);
          setTotal(prodRes.total);
          setCategories(catRes.items);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof ApiError ? err.message : "Không thể tải danh sách sản phẩm.");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [
    page,
    pageSize,
    appliedSearch,
    selectedCategory,
    selectedStatus,
    appliedMinPrice,
    appliedMaxPrice,
    sort,
    reloadTick,
  ]);

  const triggerReload = () => {
    setLoading(true);
    setReloadTick((prev) => prev + 1);
  };

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (
      minPriceInput &&
      maxPriceInput &&
      Number.parseInt(minPriceInput, 10) > Number.parseInt(maxPriceInput, 10)
    ) {
      setError("Giá tối thiểu không được lớn hơn giá tối đa.");
      return;
    }
    setLoading(true);
    setError(null);
    setPage(1);
    setAppliedSearch(searchInput.trim());
    setAppliedMinPrice(minPriceInput.trim());
    setAppliedMaxPrice(maxPriceInput.trim());
  };

  const handleReset = () => {
    setLoading(true);
    setError(null);
    setSearchInput("");
    setMinPriceInput("");
    setMaxPriceInput("");
    setAppliedSearch("");
    setSelectedCategory("");
    setSelectedStatus("");
    setAppliedMinPrice("");
    setAppliedMaxPrice("");
    setSort("NEWEST");
    setPage(1);
  };

  const handleQuickStatusChange = async (product: Product, newStatus: ProductStatus) => {
    if (product.status === newStatus) return;
    if (
      newStatus === "DISCONTINUED" &&
      !window.confirm(`Xác nhận ngừng kinh doanh sản phẩm "${product.name}"?`)
    ) {
      return;
    }
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await patchAdminProduct(
        product.id,
        {
          expectedVersion: product.version,
          status: newStatus,
        },
        getSavedAdminToken()
      );
      setSuccessMsg(`Đã chuyển trạng thái "${product.name}" sang ${newStatus}.`);
      triggerReload();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Xung đột phiên bản (expectedVersion)! Vui lòng bấm Tải lại để lấy dữ liệu mới nhất.");
      } else {
        setError(err instanceof ApiError ? err.message : "Lỗi khi cập nhật trạng thái.");
      }
    } finally {
      setActionLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Quản trị sản phẩm</h1>
            <p className="text-sm text-neutral-600 mt-1">
              Quản lý toàn bộ sản phẩm cửa hàng (DRAFT, ACTIVE, DISCONTINUED).
            </p>
          </div>
          <div className="flex space-x-2">
            <button
              type="button"
              onClick={triggerReload}
              className="px-3 py-2 border border-black rounded text-sm font-medium hover:bg-neutral-100"
            >
              Tải lại
            </button>
            <Link
              href="/admin/products/new"
              className="px-4 py-2 bg-black text-white rounded text-sm font-semibold hover:bg-neutral-800"
            >
              + Tạo sản phẩm mới
            </Link>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="p-4 mb-6 bg-white border-2 border-black text-black rounded text-sm font-medium"
          >
            Lỗi: {error}
          </div>
        )}
        {successMsg && (
          <div
            role="status"
            className="p-4 mb-6 bg-neutral-100 border border-black text-black rounded text-sm font-medium"
          >
            {successMsg}
          </div>
        )}

        <form
          onSubmit={handleFilterSubmit}
          className="bg-white p-4 rounded border border-neutral-300 mb-6 space-y-4 text-sm"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <div>
              <label htmlFor="search" className="block text-xs font-semibold mb-1">
                Tìm kiếm
              </label>
              <input
                id="search"
                type="text"
                placeholder="Tên, SKU..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full border border-neutral-300 rounded px-3 py-1.5 focus:border-black focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="category" className="block text-xs font-semibold mb-1">
                Danh mục
              </label>
              <select
                id="category"
                value={selectedCategory}
                onChange={(e) => {
                  setLoading(true);
                  setSelectedCategory(e.target.value);
                  setPage(1);
                }}
                className="w-full border border-neutral-300 rounded px-3 py-1.5 focus:border-black focus:outline-none bg-white"
              >
                <option value="">Tất cả danh mục</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="status" className="block text-xs font-semibold mb-1">
                Trạng thái
              </label>
              <select
                id="status"
                value={selectedStatus}
                onChange={(e) => {
                  setLoading(true);
                  setSelectedStatus(e.target.value);
                  setPage(1);
                }}
                className="w-full border border-neutral-300 rounded px-3 py-1.5 focus:border-black focus:outline-none bg-white"
              >
                <option value="">Tất cả trạng thái</option>
                <option value="DRAFT">DRAFT (Bản nháp)</option>
                <option value="ACTIVE">ACTIVE (Đang bán)</option>
                <option value="DISCONTINUED">DISCONTINUED (Ngừng bán)</option>
              </select>
            </div>

            <div className="flex space-x-1.5">
              <div className="w-1/2">
                <label htmlFor="min-price" className="block text-xs font-semibold mb-1">
                  Giá từ
                </label>
                <input
                  id="min-price"
                  type="number"
                  min="0"
                  placeholder="0"
                  value={minPriceInput}
                  onChange={(e) => setMinPriceInput(e.target.value)}
                  className="w-full border border-neutral-300 rounded px-2 py-1.5 focus:border-black focus:outline-none text-xs"
                />
              </div>
              <div className="w-1/2">
                <label htmlFor="max-price" className="block text-xs font-semibold mb-1">
                  Đến
                </label>
                <input
                  id="max-price"
                  type="number"
                  min="0"
                  placeholder="VND"
                  value={maxPriceInput}
                  onChange={(e) => setMaxPriceInput(e.target.value)}
                  className="w-full border border-neutral-300 rounded px-2 py-1.5 focus:border-black focus:outline-none text-xs"
                />
              </div>
            </div>

            <div>
              <label htmlFor="sort" className="block text-xs font-semibold mb-1">
                Sắp xếp
              </label>
              <select
                id="sort"
                value={sort}
                onChange={(e) => {
                  setLoading(true);
                  setSort(e.target.value as SortOption);
                  setPage(1);
                }}
                className="w-full border border-neutral-300 rounded px-3 py-1.5 focus:border-black focus:outline-none bg-white"
              >
                <option value="NEWEST">Mới nhất</option>
                <option value="PRICE_ASC">Giá tăng dần</option>
                <option value="PRICE_DESC">Giá giảm dần</option>
              </select>
            </div>
          </div>

          <div className="flex justify-end space-x-3 pt-2 border-t border-neutral-100">
            <button
              type="button"
              onClick={handleReset}
              className="px-3 py-1 text-neutral-600 hover:text-black underline"
            >
              Đặt lại
            </button>
            <button
              type="submit"
              className="px-4 py-1 font-semibold bg-black text-white rounded hover:bg-neutral-800"
            >
              Lọc kết quả
            </button>
          </div>
        </form>

        {loading ? (
          <div className="py-16 text-center text-neutral-600 font-medium text-sm">
            Đang tải sản phẩm...
          </div>
        ) : products.length === 0 ? (
          <div className="py-16 text-center bg-white rounded border border-neutral-300">
            <p className="text-neutral-600 font-medium text-sm">Chưa có sản phẩm nào phù hợp.</p>
          </div>
        ) : (
          <div className="bg-white rounded border border-neutral-300 overflow-x-auto">
            <table className="min-w-full divide-y divide-neutral-200 text-sm">
              <thead className="bg-neutral-100 text-black font-semibold text-xs uppercase tracking-wider text-left">
                <tr>
                  <th className="px-4 py-3">Ảnh</th>
                  <th className="px-4 py-3">Tên sản phẩm</th>
                  <th className="px-4 py-3">SKU</th>
                  <th className="px-4 py-3">Danh mục</th>
                  <th className="px-4 py-3">Giá bán</th>
                  <th className="px-4 py-3">Trạng thái</th>
                  <th className="px-4 py-3">Ver</th>
                  <th className="px-4 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 bg-white">
                {products.map((p) => {
                  const primaryImg = p.images?.[0];
                  const cat = categories.find((c) => c.id === p.categoryId);
                  return (
                    <tr key={p.id} className="hover:bg-neutral-50">
                      <td className="px-4 py-3">
                        <div className="w-12 h-12 bg-neutral-100 rounded overflow-hidden flex items-center justify-center border border-neutral-300">
                          {primaryImg ? (
                            <Image
                              src={primaryImg.url}
                              alt={primaryImg.altText || p.name}
                              width={48}
                              height={48}
                              unoptimized
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <span className="text-[10px] text-neutral-500">Trống</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        <Link
                          href={`/admin/products/${p.id}`}
                          className="font-bold hover:underline line-clamp-1"
                        >
                          {p.name}
                        </Link>
                        <p className="text-xs text-neutral-500 font-mono">{p.slug}</p>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-neutral-800 whitespace-nowrap">
                        {p.sku}
                      </td>
                      <td className="px-4 py-3 text-xs text-neutral-700 whitespace-nowrap">
                        {cat ? cat.name : "—"}
                      </td>
                      <td className="px-4 py-3 font-bold whitespace-nowrap">
                        {formatVND(p.priceAmount)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <select
                          aria-label={`Đổi trạng thái ${p.name}`}
                          value={p.status}
                          disabled={actionLoading}
                          onChange={(e) =>
                            handleQuickStatusChange(p, e.target.value as ProductStatus)
                          }
                          className={`text-xs font-semibold px-2 py-1 rounded border ${
                            p.status === "ACTIVE"
                              ? "bg-black text-white border-black"
                              : "bg-white text-black border-neutral-400"
                          }`}
                        >
                          <option value="DRAFT">DRAFT</option>
                          <option value="ACTIVE">ACTIVE</option>
                          <option value="DISCONTINUED">DISCONTINUED</option>
                        </select>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-neutral-600">{p.version}</td>
                      <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap text-xs">
                        <Link
                          href={`/admin/products/${p.id}`}
                          className="font-medium text-neutral-800 hover:text-black underline"
                        >
                          Chi tiết & Ảnh ({p.images?.length || 0})
                        </Link>
                        <Link
                          href={`/admin/products/${p.id}/edit`}
                          className="px-2.5 py-1 bg-black text-white rounded font-semibold hover:bg-neutral-800 inline-block"
                        >
                          Chỉnh sửa
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {!loading && totalPages > 1 && (
          <div className="mt-8 flex justify-center items-center space-x-3 text-sm">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => {
                setLoading(true);
                setPage((prev) => prev - 1);
              }}
              className="px-3 py-1.5 border border-black rounded disabled:opacity-40 hover:bg-neutral-100"
            >
              Trước
            </button>
            <span className="px-3 py-1.5 text-neutral-700">
              Trang {page} / {totalPages} (Tổng {total})
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => {
                setLoading(true);
                setPage((prev) => prev + 1);
              }}
              className="px-3 py-1.5 border border-black rounded disabled:opacity-40 hover:bg-neutral-100"
            >
              Sau
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
