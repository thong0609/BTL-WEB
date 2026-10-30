# Setup bước 5 — Base frontend

## 1. Phạm vi

Next.js + TypeScript đã khóa từ bước 1; bước này bổ sung App Router, Tailwind CSS, API client và trang kiểm tra kết nối. Không thêm màn hình mua hàng, auth, refresh token, consumer hay bảng database.

## 2. Cấu trúc

| File/thư mục trong `apps/web` | Vai trò |
| --- | --- |
| `src/app/layout.tsx` | Root Server Component, metadata, ngôn ngữ Việt và CSS |
| `src/app/page.tsx` | Trang kiểm tra luồng HTTP |
| `src/components/connection-check.tsx` | Client Component: nút gọi API, loading/success/error, hủy request khi unmount |
| `src/lib/api-client.ts` | Fetch cùng origin, timeout, abort, Error envelope, request ID |
| `src/lib/health.ts` | Gọi và validate kết quả health Catalog |
| `next.config.ts` | Rewrite `/api/v1/:path*` tới `GATEWAY_URL`, output standalone |
| `.env.example` | Mẫu origin gateway, không có secret |
| `postcss.config.mjs`, `src/app/globals.css` | Tailwind qua PostCSS, font hệ thống không cần tải mạng khi build |
| `tests/api-client.test.ts` | Kiểm tra hành vi HTTP client |
| `Dockerfile` | Image Node standalone, chạy bằng user `node` |

Không tạo Next.js Route Handler bắt `/api/v1`. Gateway vẫn xử lý backend. Chưa thêm TanStack Query vì trang chỉ có một thao tác gọi thủ công; chưa sinh toàn bộ TypeScript types từ OpenAPI, chưa tạo types nghiệp vụ thủ công trùng contract.

## 3. Cấu hình và chạy

Xem [README frontend](../../apps/web/README.md) cho lệnh cài/chạy đầy đủ. Web mặc định port 3100, gateway 3000, Catalog 3002. `GATEWAY_URL` là HTTP(S) origin không có path, credential, query hoặc fragment; chỉ dùng phía server. Frontend không đọc `.env` backend hay kết nối Supabase.

```text
Browser: /api/v1/health/catalog
  → Next.js rewrite
  → Gateway: /api/v1/health/catalog
  → Catalog: /health/live
```

`GATEWAY_URL` được chốt khi build rewrite. Cần restart dev hoặc rebuild image nếu đổi origin; truyền biến lúc container đã chạy không đổi rewrite đã build. Docker mặc định origin `http://api-gateway:3000`; chưa có Compose tạo hostname đó ở bước này.

API client dùng relative base `/api/v1`, timeout 8 giây gồm đọc body, `cache: no-store`, `credentials: same-origin`. Không tự refresh/retry mutation. Body lỗi đúng envelope giữ `code/message/requestId/details`; lỗi HTML của proxy hoặc network được chuyển thành thông báo an toàn. Request ID do gateway tạo hoặc caller truyền; UI hiện ID khi lỗi có cung cấp. UUID/tiền từ JSON không tự ép thành number.

Health dùng liveness. Kết nối thành công không xác nhận DB/broker hoặc các luồng nghiệp vụ. Người dùng bấm kiểm tra để gửi request; trang không polling nền. Có text trạng thái, vùng `aria-live`, nút khóa khi chờ và focus bàn phím.

## 4. Kiểm chứng

```powershell
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
uv run --locked --all-packages python scripts/smoke_web.py
```

Smoke khởi động Catalog, gateway thật và Next.js dev trên port loopback tạm. Backend `APP_ENV=test`, DB/broker disabled, không đọc `.env` dev và không chạy migration. Fixture gateway chỉ trong `tests/fixtures/web_gateway.py` thêm route echo để kiểm tra Cookie, Authorization, X-Request-Id, query và Set-Cookie qua rewrite. Route này không có trong ứng dụng gateway thường.

Smoke dừng Catalog để xác nhận Error envelope 503, dừng gateway để xác nhận lỗi proxy và dọn các process chính nó tạo. Không chiếm các port mặc định hoặc dừng process dev đang có. Đây là smoke HTTP, chưa phải browser E2E kiểm tra tương tác/hydration.

Đã pass: ESLint, TypeScript, 7 test API client, `next build --webpack`, smoke HTTP với gateway/Catalog thật. Typecheck chạy `next typegen` trước `tsc` để clone mới không phụ thuộc file route types của lần build/dev trước. Ruff lint/format và mypy cho smoke script/fixture cũng pass.

Đã build image `commerce-web:step5` từ Dockerfile và chạy container ở port loopback tạm: trang HTML/CSS trả 200, process dùng user `node`. Container kiểm tra đã được xóa. Đây là kiểm tra image standalone; chưa deploy hoặc ghép container với gateway qua Compose.

Đã kiểm tra bổ sung bằng Chromium headless với gateway HTTP fixture: hydration và click hoạt động; thấy trạng thái loading, success, error và request ID; màn hình 375px không tràn ngang, Tailwind có hiệu lực và không có lỗi JavaScript trên trang. Kiểm tra trình duyệt này chạy thủ công bằng Playwright tạm ngoài repo, chưa đưa thành bộ E2E tự động của nhóm.

`next dev` tự sinh `apps/web/AGENTS.md` để hướng dẫn coding agent đọc tài liệu đi kèm phiên bản Next.js đang cài. File này không phải module ứng dụng; đã giữ lại cùng bộ khung theo cơ chế của Next.js.

Máy setup từng dùng junction `apps/web/node_modules` sang ổ C vì thiếu dung lượng. Next.js build phát sinh đường dẫn dạng `./C:/...` và thất bại. Sau khi xác nhận ổ D đủ dung lượng, đã bỏ riêng junction và chạy `npm ci` trong `apps/web`. Dependency cũ ở ổ C vẫn giữ; `.venv` backend không thay đổi. Build sau đó pass. Không dùng junction qua ổ khác cho frontend.

## 5. Giới hạn và phần tiếp theo

Chưa deploy production, chưa có Compose/CI (bước 6–7), chưa có auth/UI nghiệp vụ. Shared RabbitMQ vẫn cần cấu hình riêng. Việc sinh types OpenAPI có thể bổ sung khi bắt đầu gọi API nghiệp vụ; generic TypeScript hiện tại không thay cho schema validation.

Tham khảo chính thức: [Next.js rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites), [standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output), [Tailwind với Next.js](https://tailwindcss.com/docs/installation/framework-guides/nextjs).
