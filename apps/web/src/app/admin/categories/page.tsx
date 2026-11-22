"use client";

import { useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { ApiError } from "@/lib/api-client";
import {
  Category,
  CategoryInput,
  CategoryPatch,
  createAdminCategory,
  fetchAdminCategories,
  generateSlug,
  getSavedAdminToken,
  isValidSlug,
  patchAdminCategory,
} from "@/lib/catalog";

export default function AdminCategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [reloadTick, setReloadTick] = useState(0);
  const pageSize = 20;

  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [isVisible, setIsVisible] = useState(true);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editSlug, setEditSlug] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editVisible, setEditVisible] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    fetchAdminCategories(getSavedAdminToken(), page, pageSize, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setCategories(res.items);
          setTotal(res.total);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof ApiError ? err.message : "Không thể tải danh sách danh mục.");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [page, pageSize, reloadTick]);

  const triggerReload = () => {
    setLoading(true);
    setReloadTick((prev) => prev + 1);
  };

  const handleNameChange = (val: string) => {
    setName(val);
    if (!slug || slug === generateSlug(name)) {
      setSlug(generateSlug(val));
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedName = name.trim();
    const trimmedSlug = slug.trim();
    if (!trimmedName) {
      setError("Tên danh mục không được để trống.");
      return;
    }
    if (!isValidSlug(trimmedSlug)) {
      setError("Slug không hợp lệ (chỉ gồm chữ thường a-z, số 0-9 và dấu gạch ngang -).");
      return;
    }
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const payload: CategoryInput = {
        name: trimmedName,
        slug: trimmedSlug,
        isVisible,
      };
      if (description.trim()) {
        payload.description = description.trim();
      }
      await createAdminCategory(payload, getSavedAdminToken());
      setSuccessMsg("Tạo danh mục thành công.");
      setName("");
      setSlug("");
      setDescription("");
      setIsVisible(true);
      setIsCreating(false);
      triggerReload();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Lỗi khi tạo danh mục.");
    } finally {
      setActionLoading(false);
    }
  };

  const startEdit = (cat: Category) => {
    setEditingId(cat.id);
    setEditName(cat.name);
    setEditSlug(cat.slug);
    setEditDesc(cat.description || "");
    setEditVisible(cat.isVisible);
  };

  const handleUpdate = async (id: string) => {
    const trimmedName = editName.trim();
    const trimmedSlug = editSlug.trim();
    if (!trimmedName) {
      setError("Tên danh mục không được để trống.");
      return;
    }
    if (!isValidSlug(trimmedSlug)) {
      setError("Slug không hợp lệ (chỉ gồm chữ thường a-z, số 0-9 và dấu gạch ngang -).");
      return;
    }
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const patch: CategoryPatch = {
        name: trimmedName,
        slug: trimmedSlug,
        description: editDesc.trim(),
        isVisible: editVisible,
      };
      await patchAdminCategory(id, patch, getSavedAdminToken());
      setSuccessMsg("Cập nhật danh mục thành công.");
      setEditingId(null);
      triggerReload();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Lỗi khi cập nhật danh mục.");
    } finally {
      setActionLoading(false);
    }
  };

  const toggleVisibility = async (cat: Category) => {
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await patchAdminCategory(cat.id, { isVisible: !cat.isVisible }, getSavedAdminToken());
      setSuccessMsg(
        `Đã ${!cat.isVisible ? "hiển thị" : "ẩn"} danh mục "${cat.name}". Lưu ý: ẩn danh mục không tự ngừng kinh doanh sản phẩm thuộc danh mục này.`
      );
      triggerReload();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Lỗi khi cập nhật trạng thái hiển thị.");
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
            <h1 className="text-2xl font-bold tracking-tight">Quản trị danh mục</h1>
            <p className="text-sm text-neutral-600 mt-1">
              Tạo, sửa, ẩn/hiện danh mục. Danh mục đang được sản phẩm tham chiếu được bảo vệ toàn vẹn (không xóa).
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
            <button
              type="button"
              onClick={() => setIsCreating((prev) => !prev)}
              className="px-4 py-2 bg-black text-white rounded text-sm font-semibold hover:bg-neutral-800"
            >
              {isCreating ? "Đóng biểu mẫu" : "+ Tạo danh mục"}
            </button>
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

        {isCreating && (
          <form
            onSubmit={handleCreate}
            className="bg-white p-6 rounded border border-black mb-8 space-y-4"
          >
            <h2 className="text-base font-bold">Thêm danh mục mới</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label htmlFor="create-name" className="block text-xs font-semibold mb-1">
                  Tên danh mục *
                </label>
                <input
                  id="create-name"
                  type="text"
                  maxLength={100}
                  placeholder="Ví dụ: Bàn phím cơ"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  required
                  className="w-full border border-neutral-400 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="create-slug" className="block text-xs font-semibold mb-1">
                  Slug định danh URL *
                </label>
                <input
                  id="create-slug"
                  type="text"
                  maxLength={120}
                  placeholder="ban-phim-co"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  required
                  className="w-full border border-neutral-400 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none font-mono"
                />
              </div>
            </div>

            <div>
              <label htmlFor="create-desc" className="block text-xs font-semibold mb-1">
                Mô tả
              </label>
              <textarea
                id="create-desc"
                rows={2}
                placeholder="Mô tả danh mục..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full border border-neutral-400 rounded px-3 py-1.5 text-sm focus:border-black focus:outline-none"
              />
            </div>

            <div className="flex items-center space-x-2">
              <input
                id="create-visible"
                type="checkbox"
                checked={isVisible}
                onChange={(e) => setIsVisible(e.target.checked)}
                className="h-4 w-4 rounded border-neutral-400"
              />
              <label htmlFor="create-visible" className="text-sm font-medium">
                Hiển thị trên điều hướng công khai
              </label>
            </div>

            <div className="flex justify-end space-x-3 pt-2">
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="px-4 py-1.5 text-sm text-neutral-600 hover:text-black underline"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={actionLoading}
                className="px-5 py-1.5 text-sm font-semibold bg-black text-white rounded hover:bg-neutral-800 disabled:opacity-50"
              >
                {actionLoading ? "Đang lưu..." : "Tạo danh mục"}
              </button>
            </div>
          </form>
        )}

        {loading ? (
          <div className="py-16 text-center text-neutral-600 text-sm font-medium">
            Đang tải danh mục...
          </div>
        ) : categories.length === 0 ? (
          <div className="py-16 text-center bg-white rounded border border-neutral-300">
            <p className="text-neutral-600 text-sm font-medium">Chưa có danh mục nào.</p>
          </div>
        ) : (
          <div className="bg-white rounded border border-neutral-300 overflow-x-auto">
            <table className="min-w-full divide-y divide-neutral-200 text-sm">
              <thead className="bg-neutral-100 text-black font-semibold text-xs uppercase tracking-wider text-left">
                <tr>
                  <th className="px-6 py-3">Tên danh mục</th>
                  <th className="px-6 py-3">Slug</th>
                  <th className="px-6 py-3">Mô tả</th>
                  <th className="px-6 py-3">Hiển thị</th>
                  <th className="px-6 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 bg-white">
                {categories.map((cat) => {
                  const isEditing = editingId === cat.id;
                  if (isEditing) {
                    return (
                      <tr key={cat.id} className="bg-neutral-50">
                        <td className="px-6 py-3">
                          <input
                            type="text"
                            aria-label="Tên danh mục chỉnh sửa"
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            className="border border-black px-2 py-1 text-sm rounded w-full"
                          />
                        </td>
                        <td className="px-6 py-3">
                          <input
                            type="text"
                            aria-label="Slug danh mục chỉnh sửa"
                            value={editSlug}
                            onChange={(e) => setEditSlug(e.target.value)}
                            className="border border-black px-2 py-1 text-xs rounded w-full font-mono"
                          />
                        </td>
                        <td className="px-6 py-3">
                          <input
                            type="text"
                            aria-label="Mô tả danh mục chỉnh sửa"
                            value={editDesc}
                            onChange={(e) => setEditDesc(e.target.value)}
                            className="border border-black px-2 py-1 text-xs rounded w-full"
                          />
                        </td>
                        <td className="px-6 py-3">
                          <label className="flex items-center space-x-1.5 text-xs">
                            <input
                              type="checkbox"
                              checked={editVisible}
                              onChange={(e) => setEditVisible(e.target.checked)}
                            />
                            <span>Hiển thị</span>
                          </label>
                        </td>
                        <td className="px-6 py-3 text-right space-x-2 whitespace-nowrap">
                          <button
                            type="button"
                            disabled={actionLoading}
                            onClick={() => handleUpdate(cat.id)}
                            className="px-3 py-1 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800"
                          >
                            Lưu
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingId(null)}
                            className="px-3 py-1 border border-neutral-400 rounded text-xs hover:bg-neutral-100"
                          >
                            Hủy
                          </button>
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={cat.id} className="hover:bg-neutral-50">
                      <td className="px-6 py-4 font-semibold">{cat.name}</td>
                      <td className="px-6 py-4 font-mono text-xs text-neutral-700">{cat.slug}</td>
                      <td className="px-6 py-4 text-xs text-neutral-600 max-w-xs truncate">
                        {cat.description || "—"}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span
                          className={`inline-block px-2.5 py-0.5 rounded text-xs font-medium border ${
                            cat.isVisible
                              ? "bg-black text-white border-black"
                              : "bg-white text-neutral-700 border-neutral-400"
                          }`}
                        >
                          {cat.isVisible ? "Hiển thị (VISIBLE)" : "Đang ẩn (HIDDEN)"}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right space-x-3 whitespace-nowrap">
                        <button
                          type="button"
                          disabled={actionLoading}
                          onClick={() => toggleVisibility(cat)}
                          className="text-xs text-neutral-700 hover:text-black underline"
                        >
                          {cat.isVisible ? "Ẩn danh mục" : "Hiện danh mục"}
                        </button>
                        <button
                          type="button"
                          onClick={() => startEdit(cat)}
                          className="text-xs font-semibold text-black hover:underline"
                        >
                          Chỉnh sửa
                        </button>
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
              Trang {page} / {totalPages}
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
