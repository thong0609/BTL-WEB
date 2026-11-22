import Link from "next/link";
import { Navbar } from "@/components/navbar";
import { ConnectionCheck } from "@/components/connection-check";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-neutral-50 text-black">
      <Navbar />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-12">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <p className="text-xs font-bold uppercase tracking-widest text-neutral-500 mb-2">
            BTL-WEB · Hệ thống Bán Hàng Trực Tuyến
          </p>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
            Phân hệ Quản lý Catalog
          </h1>
          <p className="mt-3 text-sm text-neutral-600 leading-relaxed">
            Module Catalog hoàn chỉnh bao gồm Backend (FastAPI, SQLAlchemy, Alembic, PostgreSQL)
            và Frontend (Next.js, TypeScript).
          </p>
        </div>

        {/* Feature Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          <div className="bg-white p-6 rounded-lg border border-neutral-200 flex flex-col justify-between hover:border-black transition">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-neutral-400 block mb-1">
                Khách hàng
              </span>
              <h2 className="text-lg font-bold mb-2">Cửa hàng Sản phẩm</h2>
              <p className="text-xs text-neutral-600 mb-4 leading-relaxed">
                Xem danh mục sản phẩm công khai (chỉ ACTIVE), tìm kiếm, lọc theo giá, lọc theo danh mục,
                phân trang và xem chi tiết sản phẩm.
              </p>
            </div>
            <Link
              href="/products"
              className="inline-block text-center py-2 px-4 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800"
            >
              Vào cửa hàng →
            </Link>
          </div>

          <div className="bg-white p-6 rounded-lg border border-neutral-200 flex flex-col justify-between hover:border-black transition">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-neutral-400 block mb-1">
                Quản trị viên
              </span>
              <h2 className="text-lg font-bold mb-2">Quản lý Sản phẩm</h2>
              <p className="text-xs text-neutral-600 mb-4 leading-relaxed">
                Tạo sản phẩm mới, cập nhật giá và thông số, quản lý phiên bản (expectedVersion),
                tải lên và sắp xếp tối đa 5 hình ảnh raster, đổi trạng thái DRAFT / ACTIVE / DISCONTINUED.
              </p>
            </div>
            <Link
              href="/admin/products"
              className="inline-block text-center py-2 px-4 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800"
            >
              Quản trị sản phẩm →
            </Link>
          </div>

          <div className="bg-white p-6 rounded-lg border border-neutral-200 flex flex-col justify-between hover:border-black transition">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-neutral-400 block mb-1">
                Quản trị viên
              </span>
              <h2 className="text-lg font-bold mb-2">Quản lý Danh mục</h2>
              <p className="text-xs text-neutral-600 mb-4 leading-relaxed">
                Thêm danh mục mới, chỉnh sửa thông tin, validate slug duy nhất, ẩn hoặc hiển thị
                danh mục trên điều hướng.
              </p>
            </div>
            <Link
              href="/admin/categories"
              className="inline-block text-center py-2 px-4 bg-black text-white rounded text-xs font-semibold hover:bg-neutral-800"
            >
              Quản trị danh mục →
            </Link>
          </div>
        </div>

        {/* Diagnostic Liveness Section */}
        <section className="bg-white p-6 rounded-lg border border-neutral-200 max-w-2xl mx-auto">
          <h2 className="text-sm font-bold uppercase tracking-wider text-neutral-500 mb-1">
            Kiểm tra kết nối hệ thống (Diagnostics)
          </h2>
          <p className="text-xs text-neutral-600 mb-4">
            Kiểm tra đường truyền: Frontend &rarr; API Gateway (Port 3000) &rarr; Catalog Service (Port 3002).
          </p>
          <ConnectionCheck />
        </section>
      </main>
    </div>
  );
}
