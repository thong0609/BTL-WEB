"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  ProductInput,
  ProductStatus,
  createAdminProduct,
  fetchAdminCategories,
  generateSlug,
  getSavedAdminToken,
  isValidPriceString,
  isValidSlug,
} from "@/lib/catalog";

export default function CreateProductPage() {
  const router = useRouter();

  const [categories, setCategories] = useState<Category[]>([]);
  const [loadingCats, setLoadingCats] = useState(true);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [sku, setSku] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProductStatus>("DRAFT");
  const [specs, setSpecs] = useState<{ key: string; value: string }[]>([{ key: "", value: "" }]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchAdminCategories(getSavedAdminToken(), 1, 100, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setCategories(res.items);
          if (res.items.length > 0) {
            setCategoryId(res.items[0].id);
          }
          setLoadingCats(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoadingCats(false);
      });
    return () => controller.abort();
  }, []);

  const handleNameChange = (val: string) => {
    setName(val);
    if (!slug || slug === generateSlug(name)) {
      setSlug(generateSlug(val));
    }
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

    const trimmedName = name.trim();
    const trimmedSlug = slug.trim();
    const trimmedSku = sku.trim();
    const trimmedPrice = priceAmount.trim();

    if (!trimmedName) return setError("Tên sản phẩm không được để trống.");
    if (!trimmedSku) return setError("Mã SKU không được để trống.");
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
      const payload: ProductInput = {
        name: trimmedName,
        slug: trimmedSlug,
        sku: trimmedSku,
        categoryId,
        priceAmount: String(Number.parseInt(trimmedPrice, 10)),
        currency: "VND",
        description: description.trim(),
        status,
        specifications: specificationsObj,
      };

      const created = await createAdminProduct(payload, getSavedAdminToken());
      router.push(`/admin/products/${created.id}`);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(
          err.status === 409
            ? err.message || "Xung đột SKU hoặc Slug đã tồn tại trong hệ thống."
            : err.message
        );
      } else {
        setError("Lỗi không xác định khi tạo sản phẩm.");
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
            href="/admin/products"
            className="text-xs font-semibold text-neutral-600 hover:text-black underline"
          >
            ← Quay lại danh sách sản phẩm
          </Link>
          <h1 className="text-2xl font-bold tracking-tight mt-2">Tạo sản phẩm mới</h1>
          <p className="text-sm text-neutral-600 mt-0.5">
            Mỗi cấu hình bán tương ứng một SKU duy nhất. Sau khi tạo sản phẩm, bạn có thể tải lên tối đa 5 ảnh.
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="p-4 mb-6 bg-white border-2 border-black text-black rounded text-sm font-medium"
          >
            Lỗi: {error}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          className="bg-white p-6 rounded border border-neutral-300 space-y-6"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label htmlFor="prod-name" className="block text-xs font-semibold mb-1">
                Tên sản phẩm *
              </label>
              <input
                id="prod-name"
                type="text"
                maxLength={200}
                placeholder="Ví dụ: Bàn phím cơ không dây NuPhy Air75 V2"
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                required
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="prod-sku" className="block text-xs font-semibold mb-1">
                Mã SKU *
              </label>
              <input
                id="prod-sku"
                type="text"
                maxLength={64}
                placeholder="KB-NUPHY-A75-01"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                required
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none font-mono"
              />
            </div>

            <div>
              <label htmlFor="prod-slug" className="block text-xs font-semibold mb-1">
                Slug URL *
              </label>
              <input
                id="prod-slug"
                type="text"
                maxLength={180}
                placeholder="ban-phim-co-nuphy-air75-v2"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                required
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none font-mono"
              />
            </div>

            <div>
              <label htmlFor="prod-cat" className="block text-xs font-semibold mb-1">
                Danh mục *
              </label>
              {loadingCats ? (
                <div className="text-xs text-neutral-500 py-2">Đang tải danh mục...</div>
              ) : categories.length === 0 ? (
                <div className="text-xs text-black py-2">
                  Chưa có danh mục nào.{" "}
                  <Link href="/admin/categories" className="underline font-bold">
                    Tạo danh mục trước
                  </Link>
                </div>
              ) : (
                <select
                  id="prod-cat"
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
              )}
            </div>

            <div>
              <label htmlFor="prod-price" className="block text-xs font-semibold mb-1">
                Giá bán (VND - số nguyên) *
              </label>
              <input
                id="prod-price"
                type="number"
                min="0"
                step="1"
                placeholder="2450000"
                value={priceAmount}
                onChange={(e) => setPriceAmount(e.target.value)}
                required
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none font-mono"
              />
            </div>

            <div>
              <label htmlFor="prod-status" className="block text-xs font-semibold mb-1">
                Trạng thái phát hành
              </label>
              <select
                id="prod-status"
                value={status}
                onChange={(e) => setStatus(e.target.value as ProductStatus)}
                className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none bg-white"
              >
                <option value="DRAFT">DRAFT (Bản nháp - Mặc định)</option>
                <option value="ACTIVE">ACTIVE (Hiển thị công khai)</option>
                <option value="DISCONTINUED">DISCONTINUED (Ngừng kinh doanh)</option>
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="prod-desc" className="block text-xs font-semibold mb-1">
              Mô tả chi tiết sản phẩm
            </label>
            <textarea
              id="prod-desc"
              rows={4}
              placeholder="Giới thiệu tính năng, cấu tạo, bảo hành..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full border border-neutral-400 rounded px-3 py-2 text-sm focus:border-black focus:outline-none"
            />
          </div>

          <div className="pt-2 border-t border-neutral-200">
            <div className="flex justify-between items-center mb-2">
              <span className="block text-xs font-semibold">Thông số kỹ thuật (Key - Value)</span>
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
                    placeholder="Tên thông số (ví dụ: Switch)"
                    value={item.key}
                    onChange={(e) => handleSpecChange(idx, "key", e.target.value)}
                    className="w-1/3 border border-neutral-400 rounded px-3 py-1.5 text-xs focus:border-black focus:outline-none"
                  />
                  <input
                    type="text"
                    placeholder="Giá trị (ví dụ: Gateron Brown)"
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
              href="/admin/products"
              className="px-4 py-2 border border-neutral-400 rounded text-sm hover:bg-neutral-100"
            >
              Hủy
            </Link>
            <button
              type="submit"
              disabled={submitting}
              className="px-6 py-2 bg-black text-white rounded text-sm font-semibold hover:bg-neutral-800 disabled:opacity-50"
            >
              {submitting ? "Đang tạo..." : "Tạo sản phẩm & Tải ảnh →"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
