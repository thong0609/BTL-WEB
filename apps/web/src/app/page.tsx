import { ConnectionCheck } from "@/components/connection-check";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <p className="mb-4 text-sm font-semibold uppercase tracking-widest text-teal-700">Commerce · Môi trường phát triển</p>
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Kiểm tra kết nối hệ thống</h1>
      <p className="mt-4 max-w-xl leading-7 text-slate-600">
        Gửi yêu cầu từ trình duyệt qua gateway đến Catalog để kiểm tra đường kết nối HTTP.
      </p>
      <div aria-label="Luồng kết nối" className="my-8 rounded-xl border border-slate-200 bg-white px-5 py-4 text-sm font-medium text-slate-700">
        Frontend <span aria-hidden="true">→</span> API Gateway <span aria-hidden="true">→</span> Catalog
      </div>
      <ConnectionCheck />
      <p className="mt-6 text-sm leading-6 text-slate-500">
        Kết quả kiểm tra liveness của Catalog. Database, RabbitMQ và các luồng bán hàng chưa được kiểm tra tại đây.
      </p>
    </main>
  );
}
