# Hướng dẫn phát triển và phối hợp

## 1. Trạng thái hiện tại

Repository hiện chứa tài liệu phân tích/thiết kế. Chưa có package.json, Compose, migration hoặc bộ test ứng dụng để chạy. Các lệnh vận hành sẽ được bổ sung sau task INF-01 và phải do một thành viên khác thử lại trên máy sạch. Không coi tên công cụ trong tài liệu là đã cài đặt.

## 2. Trước khi bắt đầu code

Đọc [README](../README.md), use case và contract của phần mình. Điền tên chủ trì/reviewer trong kế hoạch, review quyết định còn mở và khóa phiên bản tương thích của Node/package/database/broker. Dựng khung repository theo file hệ thống; mỗi service có env example, schema, migration, healthcheck, Dockerfile và test.

Người dựng môi trường phải bổ sung: yêu cầu máy/OS; cài đặt đã kiểm chứng; lệnh cài dependency; build/start/stop; chạy một service; migration; seed; test; reset test; backup/restore; xem log và cách xử lý port trùng. Chỉ ghi lệnh sau khi chạy thành công, không sao chép lệnh giả định vào README.

## 3. Git và review

- Branch theo việc: `feat/ord-01-create-order`, `fix/payment-duplicate-refund`, `docs/checkout-contract`.
- Không push trực tiếp main; PR ghi mục tiêu, use case/task, thay đổi contract/DB, bằng chứng test và giới hạn.
- Ít nhất một reviewer; contract thay đổi cần cả producer/consumer review. Không merge migration phá consumer hiện tại.
- Không commit .env, private key, token, dữ liệu khách hoặc log chứa secret. Dữ liệu seed dùng tài khoản demo và mật khẩu từ cấu hình.
- Sửa docs và code trong cùng PR khi thay đổi hành vi. Thuật ngữ/status thống nhất theo contract, không tự dịch enum trong backend.

## 4. Quy ước backend và database

Controller validate và phân quyền; application service xử lý use case; repository chỉ truy cập DB của service mình. Không import Prisma model của service khác hoặc query xuyên DB. Transaction cục bộ phải gồm dữ liệu nghiệp vụ và inbox/outbox tương ứng.

Migration tạo mới có version, không sửa migration đã được dùng chung. Khi thay schema, ưu tiên thêm field tương thích → backfill → đổi reader/writer → loại field cũ trong đợt riêng. Migration test trên DB test; môi trường chung có backup trước thay đổi quan trọng. Không reset DB chung để sửa migration cá nhân.

Các API thay đổi có idempotency phải test trùng/khác payload. Khi ghi đồng thời dùng ràng buộc DB và transaction/khóa phù hợp; kiểm tra `if` trong code không thay thế ràng buộc. Tất cả file SQL/Prisma sẽ được viết khi triển khai service, tài liệu DB hiện tại là thiết kế đầu vào.

## 5. Tích hợp và quan sát

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
