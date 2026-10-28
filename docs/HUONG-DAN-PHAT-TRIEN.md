# Hướng dẫn phát triển và phối hợp

## 1. Trạng thái hiện tại

Repository hiện chứa tài liệu phân tích/thiết kế. Chưa có package.json cho frontend, pyproject.toml cho backend, Compose, migration hoặc bộ test ứng dụng để chạy. Các lệnh vận hành sẽ được bổ sung sau task INF-01 và phải do một thành viên khác thử lại trên máy sạch. Không coi tên công cụ trong tài liệu là đã cài đặt.

## 2. Trước khi bắt đầu code

Supabase là **database dev dùng chung ngay khi cả nhóm phát triển**, theo làm rõ ngày 28/10/2026; đọc [thiết kế kết nối và phối hợp](PHUONG-AN-SUPABASE.md). FastAPI có thể chạy trên laptop, DATABASE_URL trỏ Supabase dev theo role service mình; không bắt buộc mỗi người có DB local. Một project/database có 5 schema và role riêng. Test cần reset dùng DB riêng cùng tên schema. Worker có thể chạy trên laptop theo phân công, nhưng dùng broker dev chung và tránh nhiều bản code khác nhau tranh cùng queue/outbox. Production chưa tính tới.

Đọc [README](../README.md), use case và contract của phần mình. Điền tên chủ trì/reviewer trong kế hoạch, review quyết định còn mở và khóa phiên bản Python/backend dependencies, Node/frontend packages, database và broker. Dựng khung repository theo file hệ thống; mỗi service có env example, schema, migration, healthcheck, Dockerfile và test.

Người dựng môi trường phải bổ sung: yêu cầu máy/OS; cài đặt đã kiểm chứng; lệnh cài dependency; build/start/stop; chạy một service; migration; seed; test; reset test; backup/restore; xem log và cách xử lý port trùng. Chỉ ghi lệnh sau khi chạy thành công, không sao chép lệnh giả định vào README.

## 3. Git và review

- Branch theo việc: `feat/ord-01-create-order`, `fix/payment-duplicate-refund`, `docs/checkout-contract`.
- Không push trực tiếp main; PR ghi mục tiêu, use case/task, thay đổi contract/DB, bằng chứng test và giới hạn.
- Ít nhất một reviewer; contract thay đổi cần cả producer/consumer review. Không merge migration phá consumer hiện tại.
- Không commit .env, private key, token, dữ liệu khách hoặc log chứa secret. Dữ liệu seed dùng tài khoản demo và mật khẩu từ cấu hình.
- Sửa docs và code trong cùng PR khi thay đổi hành vi. Thuật ngữ/status thống nhất theo contract, không tự dịch enum trong backend.

## 4. Quy ước backend và database

FastAPI router/dependency validate và phân quyền; application service xử lý use case; repository chỉ truy cập DB của service mình. Không import SQLAlchemy model của service khác hoặc query xuyên DB. Transaction cục bộ phải gồm dữ liệu nghiệp vụ và inbox/outbox tương ứng.

Migration tạo mới có version, không sửa migration đã được dùng chung. Khi thay schema, ưu tiên thêm field tương thích → backfill → đổi reader/writer → loại field cũ trong đợt riêng. Migration test trên DB test; môi trường chung có backup trước thay đổi quan trọng. Không reset DB chung để sửa migration cá nhân.

Các API thay đổi có idempotency phải test trùng/khác payload. Khi ghi đồng thời dùng ràng buộc DB và transaction/khóa phù hợp; kiểm tra `if` trong code không thay thế ràng buộc. Tất cả file SQL/SQLAlchemy/Alembic sẽ được viết khi triển khai service, tài liệu DB hiện tại là thiết kế đầu vào.

## 5. Tích hợp và quan sát

Frontend đã chọn Next.js + TypeScript, đề xuất App Router. Dev web dùng port 3100, gateway port 3000; `/api/v1` rewrite tới GATEWAY_URL server-side để browser gọi cùng origin. Client Components xử lý state/giỏ/polling; không cache chung dữ liệu tài khoản/đơn giữa người dùng. Không đặt secret trong NEXT_PUBLIC_*. Node cần cho cả build và chạy Next.js server; không cấu hình như Vite static build. Backend vẫn là nguồn xử lý nghiệp vụ. Tham khảo [Next.js App Router](https://nextjs.org/docs/app) và [environment variables](https://nextjs.org/docs/app/guides/environment-variables).

Backend dùng FastAPI/Python theo quyết định 28/10/2026. Quy ước async session, worker bền vững, migration riêng, camelCase/tiền dạng chuỗi và chuẩn hóa validation 400 được mô tả ở mục “Quy ước triển khai FastAPI/Python” trong [hệ thống](MO-TA-HE-THONG.md). Backend CI đề xuất Ruff, mypy, pytest/HTTPX; frontend tiếp tục dùng toolchain TypeScript và Playwright. Mỗi service có pyproject.toml và lock dependencies; không chia sẻ ORM model xuyên service.

Một request có requestId/correlationId xuyên gateway/service/message; log có mã đơn và thao tác, không chứa dữ liệu nhạy cảm. Healthcheck liveness phản ánh process; readiness phản ánh khả năng nhận việc với dependency cần thiết. Sau restart tự kết nối lại broker/database.

Khi thấy đơn treo: đọc workflow → đối chiếu reservation/payment → kiểm tra outbox/inbox/DLQ → sửa nguyên nhân → retry/replay cùng ID. Không dùng SQL sửa số tồn, status hoặc payment tùy tiện để demo qua bước.

## 6. Checklist PR thực dụng

| Mục | Bằng chứng cần có |
| --- | --- |
| Đúng nghiệp vụ | Link UC và AT liên quan |
| Đúng contract | OpenAPI/message cập nhật hoặc không có thay đổi |
| Đúng dữ liệu | Migration, unique/check/index cần thiết; test transaction/race nếu liên quan |
| Chạy được | Build/test phù hợp, không secret, cấu hình mẫu đúng |
| Tích hợp | Consumer thật hoặc fixture contract đã kiểm tra; điểm chưa ghép ghi rõ |

Chỉ chạy test phù hợp thay đổi; chỉnh Markdown không cần chạy E2E ứng dụng. Contract/schema cần validation, nghiệp vụ tiền/tồn cần test cạnh tranh và retry.
