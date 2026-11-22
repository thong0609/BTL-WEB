# Kết quả kiểm thử Order

Ngày chạy: **15/11/2026**. Môi trường: Windows, Python 3.12.8, Node 22.19.0/npm 10.9.3, Docker Desktop Linux. Kết quả gắn với workspace hiện tại; chưa tạo commit hoặc triển khai môi trường chung.

Cập nhật **16/11/2026**: thêm [demo tương tác trong trình duyệt cô lập](demo.md#mở-giao-diện-bấm-thử-ngay-khi-chưa-có-identity), tự đăng nhập khách/admin bằng dữ liệu mẫu. Frontend hiện **19 test đạt**; kiểm tra demo headless tạo COD → admin xác nhận/bàn giao/hoàn thành đạt. Đã mở hai cửa sổ demo để Mạnh thử; mọi API trong hai cửa sổ này trả mẫu tại trình duyệt, không gửi về backend/Supabase. Đã sửa lỗi thông báo auth 404 bị hiển thị nhầm thành không tìm thấy đơn hàng. Các số liệu ngày 15/11 bên dưới là lịch sử lần bàn giao trước.

## 1. Kết quả thực tế

| Kiểm tra | Kết quả |
| --- | --- |
| Toàn backend với PostgreSQL/RabbitMQ disposable | **437 passed**, 293,63 giây, không skip, 1 warning |
| Backend lint/format | PASS, 137 file |
| Backend typecheck | PASS, 86 source file |
| Frontend lint/typecheck | PASS |
| Frontend unit/contract | **16 passed** |
| Chromium với Next thật, API mẫu trong test | **9 passed**, 59,6 giây |
| Build Next webpack | PASS; có 5 trang Order gồm checkout, khách/admin list/detail |
| Build image `commerce-order-service:step16` | PASS |
| Build image `commerce-web:step16` | PASS |
| Khởi động/restart hai image bằng container riêng | PASS; chạy user không phải root; API chỉ chạy entrypoint API, không tự bật worker/migration |
| HTTP Next → Gateway → Order | PASS; trang đăng nhập, thiếu token 401, token chưa xác minh 503; kiểm tra thêm Catalog health và lỗi dependency |
| Tạo database từ migration | PASS trong PostgreSQL test; revision mới nhất `0003_action_audit` |
| Backup/restore Order rồi tiếp tục đơn pending | PASS bằng pg_dump/pg_restore trên PostgreSQL test; inbox/outbox giữ nguyên và event lặp không tạo bước mới |
| Đối chiếu contract public | PASS; field bắt buộc/request/response và 12 route, quyền, mã thành công khớp OpenAPI |
| Compose profile worker | Config-check PASS: rabbitmq + order-worker, đúng project/env của script |
| npm audit dependency production | 0 lỗ hổng được registry báo tại thời điểm chạy |

Warning backend là Starlette TestClient/HTTPX deprecation đã có. Build/npm ci báo cảnh báo eslint hết hỗ trợ và 8 moderate thuộc cây công cụ dev; `npm audit --omit=dev` trả 0. Chromium/Next dev có cảnh báo màu terminal; không có test fail ở lượt cuối. Các lỗi selector/TypeScript của test và cổng Docker thay đổi khi restart ở lượt đầu đã sửa, chạy lại kiểm tra liên quan đạt.

## 2. Đã chứng minh những gì?

| Nhóm | Bằng chứng |
| --- | --- |
| Giá và snapshot | Quote string-money, số lớn không mất độ chính xác, thay giá/phí/version, giữ nguyên tên/giá đơn cũ |
| Quyền | Backend A/B/admin, không tin header tự khai; UI chặn view khách khác và form không có phiên |
| Request lặp/cạnh tranh | Một đơn/command cho cùng key; rollback không giữ key; confirm/cancel/dispatch tranh nhau được khóa |
| COD/mô phỏng | Đủ hàng mới gọi Payment; chờ đúng kết quả; COD complete chờ ghi nhận thu tiền |
| Hủy/hoàn | Hai thứ tự kho/tiền, refund đủ ship, lỗi rồi nhận kết quả mới, không lặp phần đã xong |
| Inbox/outbox | Commit trước ACK, replay sau lỗi, lease takeover, giữ messageId, kiểm tra 14 event/8 command |
| Retry/DLQ | Retry có backoff/giới hạn, poison message vào DLQ, mất confirm không đánh gửi thành công |
| Recovery | Mất event, snapshot sai/cũ, pending/timeout/404, hai job, refund retry cùng operation, bằng chứng xác thực cho version gap |
| Giao diện | Retry đúng key/body sau reload, giá mới phải xác nhận lại, HTTP 202 tiếp tục chờ/poll, checkbox COD, lọc/trang và quyền |
| Backup/restore | Khôi phục dữ liệu Order trong schema đã migrate, redelivery an toàn, tiếp tục payment pending |

File test chính: [lifecycle API](../../tests/order/test_lifecycle_api.py), [broker](../../tests/order/test_lifecycle_broker.py), [worker DB](../../tests/order/test_worker_database.py), [worker RabbitMQ](../../tests/order/test_worker_rabbitmq.py), [recovery](../../tests/order/test_recovery_database.py), [release](../../tests/order/test_release_checks.py), [frontend](../../apps/web/tests/orders.test.ts), [Chromium](../../apps/web/tests/browser/orders.spec.ts).

## 3. Chưa kiểm chứng / cần ghép nhóm

- Identity thật, routing auth Gateway, xác minh/hết hạn/thu hồi token thực tế; form auth mới là consumer contract.
- Catalog thật, giỏ hàng do trang sản phẩm thêm vào, phí ship đã chốt. Giá 30000 trong fixture chỉ là ví dụ.
- COD/mô phỏng/hủy/hoàn chạy xuyên Inventory/Payment thật; số bản ghi giao dịch/reservation bên họ.
- Tranh tồn 20 đơn mua tồn 1 và atomic giữ hàng nhiều dòng bên Inventory.
- API recovery/auth/version/refund policy của producer đã review và chạy thật.
- Demo UI đủ 5 service chung broker trên Compose; restore đồng bộ cả hệ thống và đối chiếu dữ liệu sau restore.
- Một đồng đội đọc runbook và tự chạy lại; nhóm review nghiệm thu.

Các ca mô phỏng producer/snapshot/auth chỉ nằm trong test. Không có token giả, tự tạo event thành công hoặc truy cập chéo schema trong đường chạy app mặc định.

## 4. Chạy lại và môi trường còn lại

[Runbook](runbook.md#5-kiểm-tra-trước-bàn-giao) có lệnh chuẩn; [demo](demo.md) có sáu kịch bản. Test không dùng Supabase, không reset broker dev. Backup chỉ giữ trong RAM của ca test và bị bỏ sau khi chạy.

Supabase giữ revision `0003_action_audit` đã xác minh ở Step 14; Step 15–16 không có migration mới. Đã tạo file broker local bị Git ignore bằng `infra dev init`; chưa bật stack/worker dev chung. Container test được dọn sau mỗi kiểm tra, giữ lại hai image bàn giao và Docker Desktop.
