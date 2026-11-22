# Sáu ca demo Order

## Mở giao diện bấm thử ngay khi chưa có Identity

Chạy frontend ở terminal thứ nhất (`npm.cmd --prefix apps/web run dev`), rồi ở terminal khác:

```powershell
npm.cmd --prefix apps/web run demo:orders
```

Lệnh mở **hai cửa sổ Chromium đã đăng nhập sẵn**: khách và admin. Mỗi cửa sổ có dải vàng **DEMO · Dữ liệu giả, không ghi Supabase**. Khách bấm **Thêm giỏ mẫu** để thử đặt hàng; admin xử lý cùng danh sách đơn mẫu. Dữ liệu chỉ giữ trong RAM của script, mất khi đóng demo.

Nếu báo `fetch failed` hoặc chưa kết nối được frontend: bật frontend bằng `npm.cmd --prefix apps/web run dev` trong terminal riêng, đợi `Ready` và giữ terminal đó mở rồi chạy lại lệnh demo. Demo không cần bật Gateway, Order hay Docker.

Nếu cần đăng nhập lại **trong cửa sổ demo**:

| Vai trò | Email | Mật khẩu mẫu |
| --- | --- | --- |
| Khách | `khach@demo.local` | `demo123` |
| Admin | `admin@demo.local` | `demo123` |

Các tài khoản trên chỉ hoạt động trong trình duyệt do lệnh demo mở. Tab localhost thông thường tiếp tục dùng auth thật và chưa vào được khi Identity chưa có. Không thêm endpoint auth giả vào Gateway/Order; mọi request `/api/v1/*` trong hai cửa sổ demo đều bị chặn để trả dữ liệu mẫu, không chuyển về backend.

Lần đầu cần Chromium: cài theo [frontend-handoff](frontend-handoff.md#6-kiểm-tra-frontend-độc-lập). Script tự tìm bản Chromium local đã cài trong workspace máy Mạnh. Kiểm tra demo tự động không mở cửa sổ bằng `npm.cmd --prefix apps/web run demo:orders -- --verify`.

## Sáu ca kiểm thử nghiệp vụ

**Có thể chạy ngay bằng harness test** với PostgreSQL/RabbitMQ riêng. Test đóng vai Inventory/Payment và auth. **Demo qua UI với service đồng đội thật còn chờ ghép nhóm.**

Chạy từ root, Docker Desktop đang bật:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/order/test_lifecycle_broker.py tests/order/test_lifecycle_api.py tests/order/test_recovery_database.py --run-postgres --run-rabbitmq
```

Các ca này đã nằm trong lượt toàn suite 437 test đạt. Test tự dựng/dọn hạ tầng; không cần điền token hoặc thay DB dev. Nếu cần cấu hình Docker/cache trên máy Mạnh, xem [runbook](runbook.md#5-kiểm-tra-trước-bàn-giao).

| Ca | Diễn biến cần thấy | Bài test có sẵn |
| --- | --- | --- |
| 1. COD | Giữ hàng → tạo COD → chờ xác nhận → chuẩn bị → xuất kho → đang giao → thu tiền → hoàn thành | `test_full_order_workflows_over_real_broker[COD-complete]` |
| 2. Trả trước thành công | Giữ hàng → thanh toán thành công → xác nhận/giao → hoàn thành; không tạo thu COD | `test_full_order_workflows_over_real_broker[SIMULATED-complete]` |
| 3. Thiếu hàng | Đơn bị từ chối, có lý do; không có command tạo payment | `test_checkout_results_and_delays_never_invent_payment_outcome[stock-shortage]` |
| 4. Thanh toán lỗi/chậm | Lỗi rõ ràng thì giải phóng hàng rồi hủy; chậm thì còn PROCESSING, không thu lại/hủy mù | `test_checkout_results_and_delays_never_invent_payment_outcome` và `test_full_order_workflows_over_real_broker[SIMULATED-decline]` |
| 5. Hủy/hoàn tiền | Chờ cả kho và tiền; hoàn đủ cả ship; refund lỗi chưa được CANCELLED, kết quả mới tiếp tục đúng operation | `test_cancel_waits_for_both_branches_and_replays_after_completion` và `test_refund_error_keeps_cancelling_then_new_result_finishes` |
| 6. Worker lỗi rồi phục hồi | Mất event thì tra receipt gốc; claim cũ hết hạn được worker khác nhận; event đến đồng thời không bị snapshot cũ ghi đè | `test_missing_payment_event_advances_checkout_using_original_receipt`, `test_two_jobs_share_work_and_stale_claim_cannot_apply_snapshot`, `test_event_arriving_during_http_lookup_supersedes_snapshot` |

Ca 6 mô phỏng điểm lỗi bằng trạng thái/lease và kết quả lookup; kiểm tra restart process/container nằm trong `scripts/order_image_smoke.py`, commit/ACK/crash nằm trong test worker. Không coi việc tắt/mở container API với DB tắt là demo phục hồi nghiệp vụ.

## Khi service thật sẵn sàng

1. Hoàn tất các điểm chờ trong [bàn giao frontend](frontend-handoff.md#1-cần-đồng-đội-nối-những-gì), bật stack một laptop theo [runbook](runbook.md#4-một-laptop-chạy-bằng-compose).
2. Chuẩn bị CUSTOMER A/B, ADMIN và sản phẩm test do đúng service sở hữu; chọn kết quả thanh toán trong harness/admin test của Payment, không gửi simulationScenario từ checkout.
3. Với mỗi ca trên, thao tác ở `/checkout`, `/orders/{id}` và `/admin/orders/{id}`. So sánh trạng thái UI với GET; kiểm tra bản ghi kho/tiền bằng công cụ do chủ service cung cấp.
4. Thử bấm lặp, mất mạng rồi retry cùng key. Với ca phục hồi, dừng đúng worker, để producer commit, khởi động lại; kiểm tra không tạo giao dịch hoặc xuất hàng hai lần.
5. Ghi người chạy, môi trường, correlationId, trạng thái và số thao tác kho/tiền vào test-results; không ghi secret hay thông tin người thật. Các ô nghiệm thu tích hợp chỉ tick sau khi có kết quả này.
