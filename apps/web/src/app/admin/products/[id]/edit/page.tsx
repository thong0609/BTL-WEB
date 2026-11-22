"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  ProductPatch,
  ProductStatus,
  fetchAdminCategories,
  fetchAdminProductDetail,
  getSavedAdminToken,
  isValidPriceString,
  isValidSlug,
  patchAdminProduct,
} from "@/lib/catalog";

export default function EditProductPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [categories, setCategories] = useState<Category[]>([]);
  const [reloadTick, setReloadTick] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflictOccurred, setConflictOccurred] = useState(false);

  const [currentVersion, setCurrentVersion] = useState<number>(0);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [sku, setSku] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProductStatus>("DRAFT");
  const [specs, setSpecs] = useState<{ key: string; value: string }[]>([{ key: "", value: "" }]);

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
          setCategories(catRes.items);
          setCurrentVersion(prod.version);
          setName(prod.name);
          setSlug(prod.slug);
          setSku(prod.sku);
          setCategoryId(prod.categoryId);
          setPriceAmount(prod.priceAmount);
          setDescription(prod.description || "");
          setStatus(prod.status);
          if (prod.specifications && Object.keys(prod.specifications).length > 0) {
            setSpecs(
              Object.entries(prod.specifications).map(([key, value]) => ({ key, value }))
            );
          } else {
            setSpecs([{ key: "", value: "" }]);
          }
          setError(null);
          setConflictOccurred(false);
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

  const handleReloadAfterConflict = () => {
    setLoading(true);
    setConflictOccurred(false);
    setError(null);
    setReloadTick((prev) => prev + 1);
  };

  const handleAddSpec = () => {
    setSpecs((prev) => [...prev, { key: "", value: "" }]);
  };

  const handleRemoveSpec = (index: number) => {
    setSpecs((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSpecChange = (index: number, field: "key" | "value", val: string) => {
    setSpecs((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: val };
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setConflictOccurred(false);

    const trimmedName = name.trim();
    const trimmedSlug = slug.trim();
    const trimmedPrice = priceAmount.trim();

    if (!trimmedName) return setError("Tên sản phẩm không được để trống.");
    if (!isValidSlug(trimmedSlug)) {
      return setError("Slug không hợp lệ (chỉ gồm chữ thường a-z, số 0-9 và dấu gạch ngang -).");
    }
    if (!categoryId) return setError("Vui lòng chọn danh mục.");
    if (!isValidPriceString(trimmedPrice)) {
      return setError("Giá sản phẩm phải là số nguyên VND không âm.");
    }

    const specificationsObj: Record<string, string> = {};
    for (const item of specs) {
      if (item.key.trim() && item.value.trim()) {
        specificationsObj[item.key.trim()] = item.value.trim();
      }
    }

    setSubmitting(true);
    try {
      const patch: ProductPatch = {
        expectedVersion: currentVersion,
        name: trimmedName,
        slug: trimmedSlug,
        categoryId,
        priceAmount: String(Number.parseInt(trimmedPrice, 10)),
        currency: "VND",
        description: description.trim(),
        status,
        specifications: specificationsObj,
      };

      await patchAdminProduct(id, patch, getSavedAdminToken());
      router.push(`/admin/products/${id}`);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setConflictOccurred(true);
          setError(
            err.message ||
              "Xung đột phiên bản (expectedVersion)! Sản phẩm đã được cập nhật bởi phiên khác. Không tự ghi đè dữ liệu mới hơn."
          );
        } else {
          setError(err.message);
        }
      } else {
        setError("Lỗi không xác định khi cập nhật sản phẩm.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <Link
            href={`/admin/products/${id}`}
            className="text-xs font-semibold text-neutral-600 hover:text-black underline"
          >
            ← Quay lại chi tiết sản phẩm
          </Link>
          <h1 className="text-2xl font-bold tracking-tight mt-2">Chỉnh sửa sản phẩm</h1>
          <p className="text-sm text-neutral-600 mt-0.5">
            Kiểm soát cập nhật đồng thời bằng expectedVersion:{" "}
            <code className="font-mono bg-neutral-200 px-1.5 py-0.5 rounded text-xs font-bold">
              {currentVersion}
            </code>
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="p-4 mb-6 bg-white border-2 border-black text-black rounded text-sm space-y-2"
          >
            <p className="font-semibold">Lỗi: {error}</p>
            {conflictOccurred && (
              <button
                type="button"
                onClick={handleReloadAfterConflict}
                className="px-3 py-1.5 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800"
              >
                Tải lại dữ liệu mới nhất
              </button>
            )}
          </div>
        )}

        {loading ? (
          <div className="py-20 text-center text-neutral-600 font-medium text-sm">
            Đang tải thông tin sản phẩm...
          </div>
        ) : (
          <form
            onSubmit={handleSubmit}
            className="bg-white p-6 rounded border border-neutral-300 space-y-6"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2">
                <label htmlFor="edit-name" className="block text-xs font-semibold mb-1">
                  Tên sản phẩm *
                </label>
                <input
                  id="edit-name"
                  type="text"
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="edit-sku" className="block text-xs font-semibold mb-1">
                  Mã SKU (Cố định theo hợp đồng)
                </label>
                <input
                  id="edit-sku"
                  type="text"
                  value={sku}
                  disabled
                  className="w-full border border-neutral-300 bg-neutral-100 text-neutral-600 rounded px-3 py-2 text-sm font-mono cursor-not-allowed"
                />
              </div>

              <div>
                <label htmlFor="edit-slug" className="block text-xs font-semibold mb-1">
                  Slug URL *
                </label>
                <input
                  id="edit-slug"
                  type="text"
                  maxLength={180}
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  required
                  className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none font-mono"
                />
              </div>

              <div>
                <label htmlFor="edit-cat" className="block text-xs font-semibold mb-1">
                  Danh mục *
                </label>
                <select
                  id="edit-cat"
                  value={categoryId}
                  onChange={(e) => setCategoryId(e.target.value)}
                  className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none bg-white"
                >
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="edit-price" className="block text-xs font-semibold mb-1">
                  Giá bán (VND - số nguyên) *
                </label>
                <input
                  id="edit-price"
                  type="number"
                  min="0"
                  step="1"
                  value={priceAmount}
                  onChange={(e) => setPriceAmount(e.target.value)}
                  required
                  className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none font-mono"
                />
              </div>

              <div>
                <label htmlFor="edit-status" className="block text-xs font-semibold mb-1">
                  Trạng thái phát hành
                </label>
                <select
                  id="edit-status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as ProductStatus)}
                  className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none bg-white"
                >
                  <option value="DRAFT">DRAFT (Bản nháp - Chưa bán)</option>
                  <option value="ACTIVE">ACTIVE (Hiển thị bán công khai)</option>
                  <option value="DISCONTINUED">DISCONTINUED (Ngừng kinh doanh)</option>
                </select>
              </div>
            </div>

            <div>
              <label htmlFor="edit-desc" className="block text-xs font-semibold mb-1">
                Mô tả chi tiết sản phẩm
              </label>
              <textarea
                id="edit-desc"
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none"
              />
            </div>

            <div className="pt-2 border-t border-neutral-200">
              <div className="flex justify-between items-center mb-2">
                <span className="block text-xs font-semibold">Thông số kỹ thuật</span>
                <button
                  type="button"
                  onClick={handleAddSpec}
                  className="text-xs font-semibold text-black hover:underline"
                >
                  + Thêm dòng thông số
                </button>
              </div>

              <div className="space-y-2">
                {specs.map((item, idx) => (
                  <div key={idx} className="flex items-center space-x-2">
                    <input
                      type="text"
                      placeholder="Tên thông số"
                      value={item.key}
                      onChange={(e) => handleSpecChange(idx, "key", e.target.value)}
                      className="w-1/3 border border-neutral-400 rounded px-3 py-1.5 text-xs focus:border-black focus:outline-none"
                    />
                    <input
                      type="text"
                      placeholder="Giá trị"
                      value={item.value}
                      onChange={(e) => handleSpecChange(idx, "value", e.target.value)}
                      className="flex-1 border border-neutral-400 rounded px-3 py-1.5 text-xs focus:border-black focus:outline-none"
                    />
                    {specs.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveSpec(idx)}
                        className="px-2 py-1 text-xs text-neutral-700 hover:text-black underline"
                      >
                        Xóa
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end space-x-3 pt-4 border-t border-neutral-200">
              <Link
                href={`/admin/products/${id}`}
                className="px-4 py-2 border border-neutral-400 rounded text-sm hover:bg-neutral-100"
              >
                Hủy
              </Link>
              <button
                type="submit"
                disabled={submitting}
                className="px-6 py-2 bg-black text-white rounded text-sm font-semibold hover:bg-neutral-800 disabled:opacity-50"
              >
                {submitting ? "Đang lưu..." : "Lưu thay đổi"}
              </button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
}
