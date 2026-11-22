"use client";

import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  Product,
  ProductStatus,
  deleteProductImage,
  fetchAdminCategories,
  fetchAdminProductDetail,
  formatVND,
  getSavedAdminToken,
  patchAdminProduct,
  uploadProductImage,
} from "@/lib/catalog";

export default function AdminProductDetailPage() {
  const params = useParams();
  const id = params?.id as string;

  const [product, setProduct] = useState<Product | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [reloadTick, setReloadTick] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [altText, setAltText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deletingImageId, setDeletingImageId] = useState<string | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    const token = getSavedAdminToken();
    Promise.all([
      fetchAdminProductDetail(id, token, controller.signal),
      fetchAdminCategories(token, 1, 100, controller.signal).catch(() => ({ items: [] })),
    ])
      .then(([prod, catRes]) => {
        if (!controller.signal.aborted) {
          setProduct(prod);
          setCategories(catRes.items);
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
  }, [id, reloadTick]);

  const triggerReload = () => {
    setLoading(true);
    setReloadTick((prev) => prev + 1);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      setSelectedFile(null);
      setPreviewUrl(null);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("Dung lượng file vượt quá giới hạn tối đa 5 MiB.");
      e.target.value = "";
      setSelectedFile(null);
      setPreviewUrl(null);
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Chỉ nhận ảnh raster định dạng JPEG, PNG hoặc WebP.");
      e.target.value = "";
      setSelectedFile(null);
      setPreviewUrl(null);
      return;
    }
    setError(null);
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
  };

  const handleUploadImage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !product) return;
    if (product.images && product.images.length >= 5) {
      setError("Sản phẩm đã đạt giới hạn tối đa 5 ảnh.");
      return;
    }
    setUploading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await uploadProductImage(
        product.id,
        selectedFile,
        altText.trim() || undefined,
        getSavedAdminToken()
      );
      setSuccessMsg("Tải ảnh lên thành công.");
      setSelectedFile(null);
      setPreviewUrl(null);
      setAltText("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      triggerReload();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Lỗi khi tải ảnh lên.");
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteImage = async (imageId: string) => {
    if (!product) return;
    if (!window.confirm("Xác nhận xóa ảnh này khỏi sản phẩm?")) return;

    setDeletingImageId(imageId);
    setError(null);
    setSuccessMsg(null);
    try {
      await deleteProductImage(product.id, imageId, getSavedAdminToken());
      setSuccessMsg("Đã xóa ảnh.");
      triggerReload();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Lỗi khi xóa ảnh.");
    } finally {
      setDeletingImageId(null);
    }
  };

  const handleMoveImage = async (index: number, direction: "up" | "down") => {
    if (!product || !product.images) return;
    const targetIdx = direction === "up" ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= product.images.length) return;

    const newOrder = [...product.images];
    const temp = newOrder[index];
    newOrder[index] = newOrder[targetIdx];
    newOrder[targetIdx] = temp;

    setSavingOrder(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await patchAdminProduct(
        product.id,
        {
          expectedVersion: product.version,
          imageIds: newOrder.map((img) => img.id),
        },
        getSavedAdminToken()
      );
      setSuccessMsg("Đã cập nhật thứ tự hiển thị ảnh.");
      triggerReload();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Xung đột phiên bản (expectedVersion)! Vui lòng tải lại dữ liệu mới nhất.");
      } else {
        setError(err instanceof ApiError ? err.message : "Lỗi khi đổi thứ tự ảnh.");
      }
    } finally {
      setSavingOrder(false);
    }
  };

  const handleStatusChange = async (newStatus: ProductStatus) => {
    if (!product || product.status === newStatus) return;
    if (
      newStatus === "DISCONTINUED" &&
      !window.confirm(`Xác nhận ngừng kinh doanh sản phẩm "${product.name}"?`)
    ) {
      return;
    }
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
      setSuccessMsg(`Đã chuyển trạng thái sang ${newStatus}.`);
      triggerReload();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Xung đột phiên bản (expectedVersion)! Vui lòng bấm Tải lại.");
      } else {
        setError(err instanceof ApiError ? err.message : "Lỗi khi cập nhật trạng thái.");
      }
    }
  };

  const category = categories.find((c) => c.id === product?.categoryId);

  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <Link
              href="/admin/products"
              className="text-xs font-semibold text-neutral-600 hover:text-black underline"
            >
              ← Quay lại danh sách quản trị
            </Link>
            <h1 className="text-2xl font-bold tracking-tight mt-1">
              Chi tiết sản phẩm: {product?.name || "..."}
            </h1>
          </div>
          {product && (
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={triggerReload}
                className="px-3 py-2 border border-black rounded text-sm font-medium hover:bg-neutral-100"
              >
                Tải lại
              </button>
              <Link
                href={`/admin/products/${product.id}/edit`}
                className="px-4 py-2 bg-black text-white rounded text-sm font-semibold hover:bg-neutral-800"
              >
                Chỉnh sửa sản phẩm
              </Link>
              <Link
                href={`/products/${product.id}`}
                className="px-4 py-2 border border-black rounded text-sm font-semibold hover:bg-neutral-100"
              >
                Xem trang khách ↗
              </Link>
            </div>
          )}
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

        {loading ? (
          <div className="py-20 text-center text-neutral-600 font-medium text-sm">
            Đang tải sản phẩm...
          </div>
        ) : !product ? (
          <div className="bg-white p-8 rounded border border-neutral-300 text-center">
            <p className="text-neutral-600 text-sm">Không tìm thấy sản phẩm.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2 space-y-6">
              <div className="bg-white p-6 rounded border border-neutral-300 space-y-4">
                <h2 className="text-base font-bold border-b border-neutral-200 pb-2">
                  Thông tin định danh & Giá
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-xs text-neutral-500 block">Tên sản phẩm</span>
                    <strong className="text-base">{product.name}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-500 block">Giá niêm yết</span>
                    <strong className="text-base font-mono">
                      {formatVND(product.priceAmount)} ({product.currency})
                    </strong>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-500 block">Mã SKU</span>
                    <code className="text-xs font-mono bg-neutral-100 px-2 py-0.5 rounded border border-neutral-300">
                      {product.sku}
                    </code>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-500 block">Slug URL</span>
                    <code className="text-xs font-mono bg-neutral-100 px-2 py-0.5 rounded border border-neutral-300">
                      {product.slug}
                    </code>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-500 block">Danh mục</span>
                    <span>{category ? category.name : product.categoryId}</span>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-500 block">
                      Phiên bản dữ liệu (expectedVersion)
                    </span>
                    <span className="font-mono font-bold">{product.version}</span>
                  </div>
                </div>

                <div className="pt-3 border-t border-neutral-200 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-neutral-600">
                    Đổi trạng thái sản phẩm:
                  </span>
                  <div className="space-x-2">
                    {(["DRAFT", "ACTIVE", "DISCONTINUED"] as ProductStatus[]).map((st) => (
                      <button
                        key={st}
                        type="button"
                        onClick={() => handleStatusChange(st)}
                        className={`text-xs px-3 py-1 rounded font-semibold border ${
                          product.status === st
                            ? "bg-black text-white border-black"
                            : "bg-white text-black border-neutral-400 hover:bg-neutral-100"
                        }`}
                      >
                        {st}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bg-white p-6 rounded border border-neutral-300 space-y-4">
                <h2 className="text-base font-bold border-b border-neutral-200 pb-2">
                  Mô tả & Thông số kỹ thuật
                </h2>
                <div>
                  <h3 className="text-xs font-semibold uppercase text-neutral-500 mb-1">Mô tả</h3>
                  <p className="text-sm text-neutral-800 whitespace-pre-line leading-relaxed">
                    {product.description || "Chưa có mô tả."}
                  </p>
                </div>

                {product.specifications &&
                  Object.keys(product.specifications).length > 0 && (
                    <div className="pt-3 border-t border-neutral-200">
                      <h3 className="text-xs font-semibold uppercase text-neutral-500 mb-2">
                        Thông số kỹ thuật
                      </h3>
                      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                        {Object.entries(product.specifications).map(([k, v]) => (
                          <div
                            key={k}
                            className="p-2 bg-neutral-50 rounded border border-neutral-200"
                          >
                            <dt className="text-neutral-500 font-medium">{k}</dt>
                            <dd className="font-semibold text-black mt-0.5">{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
              </div>
            </div>

            <div className="space-y-6">
              <div className="bg-white p-6 rounded border border-neutral-300 space-y-4">
                <div className="flex justify-between items-center border-b border-neutral-200 pb-2">
                  <h2 className="text-base font-bold">
                    Quản lý ảnh ({product.images?.length || 0}/5)
                  </h2>
                  <span className="text-xs text-neutral-500">Tối đa 5 ảnh · ≤ 5MiB</span>
                </div>

                <form
                  onSubmit={handleUploadImage}
                  className="space-y-3 p-3 bg-neutral-50 rounded border border-neutral-300"
                >
                  <div>
                    <label
                      htmlFor="image-upload-input"
                      className="block text-xs font-semibold mb-1"
                    >
                      Chọn file ảnh (JPEG, PNG, WebP)
                    </label>
                    <input
                      id="image-upload-input"
                      ref={fileInputRef}
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      onChange={handleFileChange}
                      disabled={uploading || (product.images && product.images.length >= 5)}
                      className="block w-full text-xs text-neutral-700 file:mr-2 file:py-1 file:px-2.5 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-black file:text-white hover:file:bg-neutral-800 disabled:opacity-50"
                    />
                  </div>

                  {previewUrl && (
                    <div className="w-20 h-20 bg-neutral-200 rounded overflow-hidden border border-neutral-400">
                      <Image
                        src={previewUrl}
                        alt="Xem trước ảnh"
                        width={80}
                        height={80}
                        unoptimized
                        className="w-full h-full object-cover"
                      />
                    </div>
                  )}

                  <div>
                    <input
                      type="text"
                      maxLength={255}
                      placeholder="Mô tả thay thế (altText)..."
                      value={altText}
                      onChange={(e) => setAltText(e.target.value)}
                      disabled={uploading || !selectedFile}
                      className="w-full border border-neutral-400 rounded px-2.5 py-1 text-xs focus:border-black focus:outline-none bg-white"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={
                      uploading ||
                      !selectedFile ||
                      Boolean(product.images && product.images.length >= 5)
                    }
                    className="w-full py-1.5 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800 disabled:opacity-40"
                  >
                    {uploading ? "Đang tải lên..." : "Tải ảnh lên"}
                  </button>
                </form>

                <div className="space-y-3 pt-2">
                  {!product.images || product.images.length === 0 ? (
                    <p className="text-xs text-neutral-500 text-center py-4">
                      Sản phẩm chưa có hình ảnh.
                    </p>
                  ) : (
                    product.images.map((img, idx) => (
                      <div
                        key={img.id}
                        className="flex items-center space-x-3 p-2 rounded border border-neutral-300"
                      >
                        <div className="w-14 h-14 bg-neutral-100 rounded overflow-hidden flex-shrink-0 border border-neutral-300">
                          <Image
                            src={img.url}
                            alt={img.altText || `Ảnh ${idx + 1}`}
                            width={56}
                            height={56}
                            unoptimized
                            className="w-full h-full object-cover"
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-semibold truncate">
                            Thứ tự #{idx + 1}{" "}
                            {idx === 0 && <span className="underline">(Ảnh đại diện)</span>}
                          </p>
                          <p className="text-[11px] text-neutral-600 truncate">
                            {img.altText || "Không có altText"}
                          </p>
                          <div className="flex space-x-2 mt-1">
                            <button
                              type="button"
                              disabled={savingOrder || idx === 0}
                              onClick={() => handleMoveImage(idx, "up")}
                              className="text-[11px] text-black underline disabled:opacity-30"
                            >
                              ↑ Lên
                            </button>
                            <button
                              type="button"
                              disabled={
                                savingOrder || idx === (product.images?.length || 1) - 1
                              }
                              onClick={() => handleMoveImage(idx, "down")}
                              className="text-[11px] text-black underline disabled:opacity-30"
                            >
                              ↓ Xuống
                            </button>
                          </div>
                        </div>
                        <button
                          type="button"
                          disabled={deletingImageId === img.id}
                          onClick={() => handleDeleteImage(img.id)}
                          className="text-xs text-black hover:underline font-semibold px-2 py-1 border border-black rounded"
                        >
                          {deletingImageId === img.id ? "..." : "Xóa"}
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
