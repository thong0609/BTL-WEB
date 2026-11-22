"use client";

import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  Product,
  fetchCategories,
  fetchProductDetail,
  formatVND,
} from "@/lib/catalog";

export default function ProductDetailPage() {
  const params = useParams();
  const id = params?.id as string;

  const [product, setProduct] = useState<Product | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeImageIdx, setActiveImageIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    Promise.all([
      fetchProductDetail(id, controller.signal),
      fetchCategories(1, 100, controller.signal).catch(() => ({ items: [] })),
    ])
      .then(([prod, catRes]) => {
        if (!controller.signal.aborted) {
          setProduct(prod);
          setCategories(catRes.items);
          setActiveImageIdx(0);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof ApiError ? err.message : "Không thể tải thông tin sản phẩm.");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [id]);

  const category = categories.find((c) => c.id === product?.categoryId);

  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <Link
            href="/products"
            className="text-xs font-semibold text-neutral-600 hover:text-black underline"
          >
            ← Quay lại danh sách sản phẩm
          </Link>
        </div>

        {loading ? (
          <div className="py-20 text-center text-neutral-600 text-sm font-medium">
            Đang tải chi tiết sản phẩm...
          </div>
        ) : error || !product ? (
          <div className="bg-white p-8 rounded border border-neutral-300 text-center max-w-lg mx-auto my-8">
            <h1 className="text-base font-bold mb-2">Không tìm thấy sản phẩm</h1>
            <p className="text-sm text-neutral-600 mb-6">
              {error || "Sản phẩm không tồn tại hoặc đã ngừng kinh doanh."}
            </p>
            <Link
              href="/products"
              className="inline-block px-4 py-2 text-sm font-semibold bg-black text-white rounded hover:bg-neutral-800"
            >
              Về danh sách sản phẩm
            </Link>
          </div>
        ) : (
          <div className="bg-white rounded border border-neutral-300 p-6 lg:p-8">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <div>
                <div className="aspect-square bg-neutral-100 rounded border border-neutral-200 flex items-center justify-center overflow-hidden">
                  {product.images && product.images.length > 0 ? (
                    <Image
                      src={product.images[activeImageIdx]?.url || product.images[0].url}
                      alt={
                        product.images[activeImageIdx]?.altText ||
                        product.name
                      }
                      width={520}
                      height={520}
                      unoptimized
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <span className="text-sm text-neutral-500">Sản phẩm chưa có ảnh</span>
                  )}
                </div>

                {product.images && product.images.length > 1 && (
                  <div className="mt-4 flex space-x-3 overflow-x-auto pb-2">
                    {product.images.map((img, idx) => (
                      <button
                        key={img.id}
                        type="button"
                        onClick={() => setActiveImageIdx(idx)}
                        className={`w-16 h-16 rounded border overflow-hidden flex-shrink-0 ${
                          idx === activeImageIdx
                            ? "border-black ring-2 ring-black"
                            : "border-neutral-300 hover:border-black"
                        }`}
                      >
                        <Image
                          src={img.url}
                          alt={img.altText || `Ảnh ${idx + 1}`}
                          width={64}
                          height={64}
                          unoptimized
                          className="w-full h-full object-cover"
                        />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col justify-between">
                <div>
                  {category && (
                    <span className="inline-block px-2.5 py-0.5 rounded text-xs font-semibold border border-black uppercase tracking-wider mb-2">
                      {category.name}
                    </span>
                  )}
                  <h1 className="text-2xl lg:text-3xl font-bold tracking-tight mb-2">
                    {product.name}
                  </h1>
                  <p className="text-xs text-neutral-600 mb-4 font-mono">
                    SKU: {product.sku} · Slug: {product.slug}
                  </p>

                  <div className="p-4 bg-neutral-50 rounded border border-neutral-300 mb-6">
                    <span className="text-xs text-neutral-600 block mb-0.5">Giá bán niêm yết</span>
                    <span className="text-3xl font-extrabold">
                      {formatVND(product.priceAmount)}
                    </span>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <h2 className="text-xs font-bold uppercase tracking-wider text-neutral-900 mb-1">
                        Mô tả sản phẩm
                      </h2>
                      <div className="text-sm text-neutral-800 whitespace-pre-line leading-relaxed">
                        {product.description || "Chưa có mô tả chi tiết."}
                      </div>
                    </div>

                    {product.specifications &&
                      Object.keys(product.specifications).length > 0 && (
                        <div className="pt-4 border-t border-neutral-200">
                          <h2 className="text-xs font-bold uppercase tracking-wider text-neutral-900 mb-2">
                            Thông số kỹ thuật
                          </h2>
                          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
                            {Object.entries(product.specifications).map(([k, v]) => (
                              <div key={k} className="border-b border-neutral-200 pb-1">
                                <dt className="text-neutral-500 font-medium">{k}</dt>
                                <dd className="text-black font-semibold">{v}</dd>
                              </div>
                            ))}
                          </dl>
                        </div>
                      )}
                  </div>
                </div>

                <div className="mt-8 pt-4 border-t border-neutral-200 flex items-center justify-between text-xs text-neutral-600">
                  <span>
                    Trạng thái: <strong className="text-black">{product.status}</strong>
                  </span>
                  <span>
                    Tồn kho:{" "}
                    <strong className="text-black">
                      {product.availability === "IN_STOCK"
                        ? "Còn hàng"
                        : product.availability === "OUT_OF_STOCK"
                          ? "Hết hàng"
                          : "Chưa xác định (UNKNOWN)"}
                    </strong>
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
