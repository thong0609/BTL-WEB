# Frontend — Next.js + TypeScript

App Router và Tailwind CSS. Trang `/` kiểm tra frontend → gateway → Catalog bằng nút bấm, có trạng thái chờ, thành công và lỗi. Chưa có giao diện mua hàng hoặc đăng nhập.

Từ thư mục gốc repository:

```powershell
npm --prefix apps/web ci
Copy-Item apps/web/.env.example apps/web/.env.local
```

Trong `.env.local`, `GATEWAY_URL` là origin gateway, mặc định `http://127.0.0.1:3000`. Biến này chỉ dùng phía server. Không thêm database URL hoặc Supabase key vào frontend.

Chạy backend ở hai terminal riêng (đã cấu hình env theo bước 2–3):

```powershell
uv run --locked --all-packages python -m commerce_catalog
uv run --locked --all-packages python -m commerce_gateway
```

Chạy frontend ở terminal thứ ba:

```powershell
npm --prefix apps/web run dev
```

Mở `http://localhost:3100`, bấm **Kiểm tra kết nối**. Browser gọi `/api/v1/health/catalog` cùng origin; Next.js rewrite sang gateway. Gateway gọi Catalog `/health/live`; thành công chưa có nghĩa DB/broker sẵn sàng.

```powershell
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web run start

# Smoke HTTP với backend test riêng, không đọc env dev hoặc dùng DB/broker.
uv run --locked --all-packages python scripts/smoke_web.py
```

`dev` và `build` dùng webpack. Cài `node_modules` trực tiếp trong `apps/web`; junction sang ổ khác khiến Next.js resolve đường dẫn build sai. Cách dùng junction tạm ở bước 1 đã được thay bằng cài đặt bình thường trong bước 5 sau khi ổ D có đủ dung lượng.

`src/lib/api-client.ts` dành cho Client Components: base `/api/v1`, timeout mặc định 8 giây, Error envelope/request ID, cookie cùng origin, không cache/retry tự động. Caller truyền header/body/signal qua options; với JSON body, tự đặt `Content-Type: application/json` và `JSON.stringify`. Generic TypeScript không thay thế validation runtime; `health.ts` kiểm tra response dùng bởi trang này.

Layout/page là Server Components; nút kiểm tra là Client Component. Chưa cần TanStack Query vì không có cache truy vấn hoặc polling. Không cache dùng chung dữ liệu tài khoản/đơn.

Dockerfile dùng Node server standalone, build context là root repository:

```powershell
docker build -f apps/web/Dockerfile --build-arg GATEWAY_URL=http://api-gateway:3000 -t commerce-web:step5 .
```

Rewrite được chốt lúc **build**. Đổi gateway khi chạy dev cần restart; đổi gateway cho image cần rebuild. Trong container `localhost` là chính container: gateway phải là hostname/port truy cập được từ container. Compose và production để bước sau.

Chi tiết kết quả và giới hạn: [setup bước 5](../../docs/development/SETUP-STEP-5.md).
