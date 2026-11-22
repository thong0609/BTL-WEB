# Step 14 — Phục hồi đơn bị treo

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

**Đã có job phía Order:** tìm đơn chờ lâu, hỏi Inventory/Payment, tiếp tục phần thiếu hoặc cảnh báo admin. Timeout/404 không tự làm đơn thất bại hoặc bị hủy.

## 1. Cách phục hồi

- Nhận việc bằng khóa và thời hạn lưu trong database; worker khác tiếp tục được khi worker cũ dừng.
- Gọi HTTP ngoài transaction. Trước khi lưu phải kiểm tra phiên bản workflow; kết quả từ lượt xử lý cũ không ghi đè event vừa đến.
- Khôi phục kết quả bằng message gốc của producer, đi qua cùng inbox/handler như RabbitMQ; không tự tạo event thành công.
- Nếu Payment tăng nhiều phiên bản một lần, event từ RabbitMQ phải chờ đối chiếu. Chỉ snapshot xác thực khớp đúng message, phiên bản và số tiền mới cho phép tiếp tục; vẫn kiểm tra workflow chưa bị thay đổi.
- PENDING chỉ là đang chờ; không thu lại tiền. Bản trả lời sai đơn/mã/số tiền/phiên bản được chặn.
- Lỗi gửi message thì gửi lại cùng mã/nội dung. Refund được producer xác nhận lỗi có thể retry thì thử lại cùng operationId/paymentId/số tiền; không giải phóng hàng đã xong.
- Hết lượt thử thì đánh dấu cần xử lý, vẫn giữ trạng thái tiền/kho chưa rõ. Log chỉ có mã lỗi/ID, không chứa secret hoặc địa chỉ.

Đã test mất event giữ hàng/thanh toán, pending, timeout/404, sai snapshot, hai job tranh việc, worker hết thời hạn, event đến trong lúc tra cứu và refund lỗi rồi phục hồi.

## 2. Phần phải chốt với Inventory/Payment

[Hợp đồng recovery](../contracts/order-recovery.openapi.yaml) là **DRAFT**. Đã có caller/test phía Order; producer chưa triển khai hoặc xác nhận.

- Inventory: GET `/internal/reservations/by-order/{orderId}`.
- Payment: GET `/internal/payments/by-order/{orderId}`.
- Cần thống nhất response, credential riêng cho Order, version và quy tắc retry refund cùng operation.
- Response cần message kết quả gốc theo đúng thứ tự công việc/phiên bản. Chỉ trả status mà không có bằng chứng thì Order không tự đánh dấu hoàn thành.

Việc này không chặn code độc lập. Tích hợp các service thật vẫn chưa hoàn thành. Chưa bật recovery trên Supabase/broker dev chung trong lần triển khai này.

## 3. Chạy job

Sau khi cấu hình URL/token nội bộ và producer hỗ trợ hợp đồng:

```powershell
# Chạy riêng recovery; cần DB, không bắt buộc broker đang bật.
.\.venv\Scripts\python.exe -m commerce_order.worker --run --mode recovery --once
.\.venv\Scripts\python.exe -m commerce_order.worker --run --mode recovery
```

Hoặc đặt `ORDER_RECOVERY_ENABLED=true` để chạy cùng `--mode all`. Mặc định false khi chưa cấu hình producer. Các biến có trong [env example](../../apps/order-service/.env.example): URL native 3003/3005, INVENTORY_SERVICE_TOKEN, PAYMENT_SERVICE_TOKEN; chờ đơn treo 300 giây, batch 10, thời hạn 60 giây, tối đa 5 lượt retry nghiệp vụ. Quá giới hạn vẫn tra cứu theo lịch chậm để nhận kết quả đến muộn, không tự tạo thêm thao tác tiền.

Trong Compose, worker đã có hostname Inventory/Payment nội bộ. Secret runtime/migrator và token dịch vụ không được đưa vào tài liệu hoặc Git.

## 4. Migration và kiểm tra

`0003_action_audit` chỉ thêm cột JSON nullable `request_body` vào bảng action của Order. Đã áp dụng và đọc lại metadata trên Supabase ngày **15/11/2026**: revision đúng `0003_action_audit`, quyền runtime hợp lệ, không có schema drift và các relation của service khác giữ nguyên. API kiểm tra database trả `/health/live` và `/health/ready` đều **200**; broker được tắt riêng trong lần kiểm tra DB này.

Kết quả chạy lại sau khi tiếp tục công việc ngày **15/11/2026**:

- Toàn bộ backend: **435 passed**, 278,13 giây; có 1 cảnh báo deprecation sẵn có từ Starlette TestClient/HTTPX.
- Lint/format: **đạt**, 135 file. Typecheck: **đạt**, 86 file nguồn.
- Thêm **51 ca test** cho Step 10–14 so với mốc 384 test của Step 9: vòng đời API, luồng RabbitMQ và phục hồi database/client; gồm xác minh snapshot khi paymentVersion bị nhảy bước.
- Compose profile `order-workers` hợp lệ; link tài liệu và schema/ref của OpenAPI recovery đã kiểm tra khớp code.

```powershell
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step1014/full-integration-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
```

Test dùng PostgreSQL/RabbitMQ disposable, HTTP snapshot/producer mẫu và verifier chỉ trong test; không reset hoặc thêm dữ liệu thử vào Supabase. Lệnh worker mặc định vẫn là monitor; API không tự chạy job/migration.

## 5. Code

- [recovery.py](../../apps/order-service/src/commerce_order/services/recovery.py): nhận việc, đối chiếu, kiểm tra phiên bản và tiếp tục đúng nhánh.
- [client recovery](../../apps/order-service/src/commerce_order/clients/recovery.py): HTTP có timeout/giới hạn kích thước/xác thực riêng, kiểm tra snapshot và receipt.
- [worker.py](../../apps/order-service/src/commerce_order/worker.py): lifecycle và mode recovery.
- Test: [API vòng đời](../../tests/order/test_lifecycle_api.py), [luồng RabbitMQ](../../tests/order/test_lifecycle_broker.py), [client](../../tests/order/test_recovery_client.py), [recovery DB](../../tests/order/test_recovery_database.py).
