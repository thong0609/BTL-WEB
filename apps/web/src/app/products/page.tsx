"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  Product,
  SortOption,
  fetchCategories,
  fetchProducts,
  formatVND,
} from "@/lib/catalog";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 12;

  // Draft filter inputs
  const [searchInput, setSearchInput] = useState("");
  const [minPriceInput, setMinPriceInput] = useState("");
  const [maxPriceInput, setMaxPriceInput] = useState("");

  // Active applied filters
  const [appliedSearch, setAppliedSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [appliedMinPrice, setAppliedMinPrice] = useState("");
  const [appliedMaxPrice, setAppliedMaxPrice] = useState("");
  const [sort, setSort] = useState<SortOption>("NEWEST");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchCategories(1, 100, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) setCategories(res.items);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchProducts(
      {
        page,
        pageSize,
        q: appliedSearch || undefined,
        categoryId: selectedCategory || undefined,
        minPrice: appliedMinPrice || undefined,
        maxPrice: appliedMaxPrice || undefined,
        sort,
      },
      controller.signal
    )
      .then((res) => {
        if (!controller.signal.aborted) {
          setProducts(res.items);
          setTotal(res.total);
          setError(null);
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
  }, [page, pageSize, appliedSearch, selectedCategory, appliedMinPrice, appliedMaxPrice, sort]);

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
    setAppliedMinPrice("");
    setAppliedMaxPrice("");
    setSort("NEWEST");
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Danh mục sản phẩm</h1>
          <p className="text-sm text-neutral-600 mt-1">
            Danh sách sản phẩm đang kinh doanh (ACTIVE).
          </p>
        </div>

        <form
          onSubmit={handleFilterSubmit}
          className="bg-white p-4 rounded border border-neutral-300 mb-6 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label htmlFor="search" className="block text-xs font-semibold mb-1">
                Tìm kiếm
              </label>
              <input
                id="search"
                type="text"
                placeholder="Tên sản phẩm hoặc SKU..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full border border-neutral-300 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none"
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
                className="w-full border border-neutral-300 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none bg-white"
              >
                <option value="">Tất cả danh mục</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex space-x-2">
              <div className="w-1/2">
                <label htmlFor="min-price" className="block text-xs font-semibold mb-1">
                  Giá từ (VND)
                </label>
                <input
                  id="min-price"
                  type="number"
                  min="0"
                  placeholder="0"
                  value={minPriceInput}
                  onChange={(e) => setMinPriceInput(e.target.value)}
                  className="w-full border border-neutral-300 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none"
                />
              </div>
              <div className="w-1/2">
                <label htmlFor="max-price" className="block text-xs font-semibold mb-1">
                  Đến (VND)
                </label>
                <input
                  id="max-price"
                  type="number"
                  min="0"
                  placeholder="Tối đa"
                  value={maxPriceInput}
                  onChange={(e) => setMaxPriceInput(e.target.value)}
                  className="w-full border border-neutral-300 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none"
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
                className="w-full border border-neutral-300 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none bg-white"
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
              className="px-4 py-1.5 text-sm text-neutral-600 hover:text-black underline"
            >
              Đặt lại
            </button>
            <button
              type="submit"
              className="px-5 py-1.5 text-sm font-semibold bg-black text-white rounded hover:bg-neutral-800"
            >
              Áp dụng lọc
            </button>
          </div>
        </form>

        {error && (
          <div
            role="alert"
            className="p-4 mb-6 bg-white border-2 border-black text-black rounded text-sm font-medium"
          >
            Lỗi: {error}
          </div>
        )}

        {loading ? (
          <div className="py-16 text-center text-neutral-600 text-sm font-medium">
            Đang tải danh sách sản phẩm...
          </div>
        ) : products.length === 0 ? (
          <div className="py-16 text-center bg-white rounded border border-neutral-300">
            <p className="text-neutral-600 text-sm font-medium">
              Không tìm thấy sản phẩm nào phù hợp.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {products.map((p) => {
              const primaryImage = p.images?.[0];
              const category = categories.find((c) => c.id === p.categoryId);
              return (
                <Link
                  key={p.id}
                  href={`/products/${p.id}`}
                  className="group bg-white rounded border border-neutral-300 overflow-hidden hover:border-black transition flex flex-col"
                >
                  <div className="aspect-square bg-neutral-100 relative overflow-hidden flex items-center justify-center border-b border-neutral-200">
                    {primaryImage ? (
                      <Image
                        src={primaryImage.url}
                        alt={primaryImage.altText || p.name}
                        width={320}
                        height={320}
                        unoptimized
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <span className="text-xs text-neutral-500">Chưa có ảnh</span>
                    )}
                  </div>
                  <div className="p-4 flex-1 flex flex-col justify-between">
                    <div>
                      {category && (
                        <p className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-1">
                          {category.name}
                        </p>
                      )}
                      <h2 className="font-bold text-sm line-clamp-2 group-hover:underline">
                        {p.name}
                      </h2>
                      <p className="text-xs text-neutral-500 mt-1 font-mono">SKU: {p.sku}</p>
                    </div>
                    <div className="mt-4 pt-2 border-t border-neutral-200 flex items-center justify-between">
                      <span className="text-base font-bold">{formatVND(p.priceAmount)}</span>
                      <span className="text-xs px-2 py-0.5 rounded border border-neutral-400 text-neutral-800 font-medium">
                        {p.availability === "IN_STOCK"
                          ? "Còn hàng"
                          : p.availability === "OUT_OF_STOCK"
                            ? "Hết hàng"
                            : "Đang bán"}
                      </span>
                    </div>
                  </div>
                </Link>
              );
            })}
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
            <span className="px-3 py-1.5 text-neutral-700 font-medium">
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
