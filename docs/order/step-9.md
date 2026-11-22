# Step 9 — Gửi và nhận việc qua RabbitMQ

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

Order đã có worker gửi lệnh đã lưu trong database và nhận kết quả từ Inventory/Payment. API không tự bật worker. Kiểm thử dùng PostgreSQL/RabbitMQ riêng; chưa chạy worker nghiệp vụ trên Supabase hoặc broker dev chung.

## 1. Đã làm gì?

| Phần | Hành vi |
| --- | --- |
| Gửi outbox | Nhiều worker chia việc bằng khóa; worker bị tắt thì việc hết hạn được nhận lại. Chỉ đánh dấu đã gửi sau xác nhận RabbitMQ và khi còn quyền xử lý việc đó |
| Gửi lại | Giữ nguyên mã, thời điểm, nội dung và liên kết message. Lỗi nhiều lần thì đánh dấu cần kiểm tra; không tạo lệnh mới |
| Nhận kết quả | Kiểm tra đủ 14 loại event, đúng đơn/công việc/message gây ra kết quả, sản phẩm/số tiền/phương thức và phiên bản |
| Lưu nguyên khối | Khóa đơn rồi workflow; cập nhật dữ liệu, lịch sử, lệnh tiếp theo và dấu đã xử lý trong cùng transaction. Lưu xong mới xác nhận message |
| Chống trùng | Cùng message/nội dung không làm lại; cùng mã khác nội dung vào hàng đợi lỗi. Kết quả cũ không ghi đè mới; vẫn nhận kết quả tiến triển mới của cùng công việc |
| Retry/DLQ | Lỗi kỹ thuật được gửi lại có khoảng chờ và giới hạn. Message sai hoặc hết lượt thử được lưu vào hàng đợi lỗi; xác nhận lưu bản gửi lại/lỗi trước khi bỏ bản gốc |

Consumer có handler cho cả kết quả thành công và thất bại. Ví dụ StockReserved lưu mã giữ hàng và tạo lệnh khởi tạo thanh toán; lỗi giải phóng/xuất kho hoặc hoàn tiền đánh dấu cần kiểm tra. Đây là nền xử lý event cho Step 10–14, chưa thay thế API hủy/admin và kiểm thử các luồng đầy đủ ở những bước đó.

## 2. Chạy worker

Chạy từ root repo. Các lệnh dưới đây là hướng dẫn bật dev khi bạn muốn, không phải worker đang được để chạy nền.

```powershell
# Bật RabbitMQ local nếu chưa có.
.\.venv\Scripts\python.exe scripts/dev.py infra dev init
.\.venv\Scripts\python.exe scripts/dev.py infra dev up

# Cần DATABASE_ENABLED=true và URL/CA trong .env Order.
# Wrapper lấy BROKER_URL của RabbitMQ local cho tiến trình worker.
.\.venv\Scripts\python.exe scripts/dev.py worker order-service --mode all
```

Các chế độ:

| Lựa chọn | Làm gì? |
| --- | --- |
| `--mode outbox` | Chỉ gửi lệnh đã lưu |
| `--mode consumer` | Chỉ nhận và xử lý kết quả |
| `--mode all` | Chạy cả hai |
| `--mode recovery` | Từ Step 14: chỉ chạy job đối chiếu đơn treo; all chỉ kèm job nếu ORDER_RECOVERY_ENABLED=true |
| `--mode monitor` | Chỉ kiểm tra kết nối, là mặc định để giữ hành vi lệnh cũ |
| Thêm `--once` | Xử lý tối đa một batch rồi thoát; all gửi trước, nhận sau. Lệnh mới sinh khi nhận sẽ gửi ở lần chạy tiếp |

Dùng `--broker configured` nếu cần lấy broker từ cấu hình riêng thay vì broker local. Inventory/Payment khi tích hợp phải dùng cùng RabbitMQ/vhost và khai báo queue của mình. Chưa có queue nhận thì lệnh giữ nguyên trong outbox để thử lại; hết lượt thử sẽ cần xử lý, không bị đánh dấu đã gửi.

Compose có service `order-worker`, profile riêng `order-workers`, dùng env đã chuẩn bị của Order và tự khởi động lại khi lỗi. Profile `apps` không tự bật worker này. Đã kiểm tra Compose resolve profile chỉ gồm RabbitMQ và order-worker; chưa build/chạy container worker dev trong lần triển khai này.

## 3. Cấu hình và lỗi

Các biến mới có sẵn trong [env example](../../apps/order-service/.env.example):

- Batch gửi: 20; quyền nhận việc hết hạn sau 60 giây; tối đa 10 lần thử outbox.
- Khi nhận lỗi kỹ thuật: mặc định 4 lần xử lý, chờ lần lượt 1/5/30 giây.
- Retry queue riêng: `order.events.retry.<milliseconds>`, qua exchange `commerce.order.retry`, quay lại `order.events` sau thời gian chờ.
- Retry queue dùng quorum và cơ chế chuyển tiếp có xác nhận để giữ message khi queue đích chưa nhận được. [Cơ chế của RabbitMQ](https://www.rabbitmq.com/docs/quorum-queues#dead-lettering).
- Hàng đợi lỗi vẫn là `order.events.dead` qua `commerce.dead`; có header `x-order-dead-reason`. Publisher xác nhận bản lỗi đã lưu rồi mới ACK bản gốc.

Không đổi envelope/message route public hay schema DB. Chưa cần migration mới sau `0002_order_tables`.

Phiên bản Payment bị nhảy được giữ lại để thử/đối chiếu thay vì ghi đè mù. Quy tắc version thực tế vẫn cần đối chiếu với chủ Payment khi tích hợp; chưa coi policy minh họa trong fixture là quyết định nhóm. Job tự tra cứu/sửa tiến trình treo thuộc Step 14.

## 4. Kiểm chứng

**Toàn backend: 384 passed, 1 warning, không skip, trong 280.57 giây.** Có 79 ca mới: 41 contract/CLI/config, 29 PostgreSQL và 9 RabbitMQ + PostgreSQL. Lint/format pass trên 126 file; typecheck pass trên 82 source file. Warning là TestClient/HTTPX deprecation đã có từ trước. Container test được fixture dọn sau khi chạy.

Các ca kiểm tra chính: chia việc/đổi worker, mất xác nhận gửi, crash sau gửi hoặc sau commit nhưng chưa ACK, trùng message, sai mã/nội dung/tiền, rollback, đủ 14 handler, hoàn tiền lỗi rồi thành công cùng công việc, retry lặp qua cùng queue, DLQ và lỗi lúc lưu retry/DLQ.

```powershell
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend
.\.venv\Scripts\python.exe -m pytest tests/order/test_worker_contracts.py -q -o cache_dir=infra/.local/order-step9/unit-cache

# Docker Desktop đang chạy; dùng các container test tự tạo và tự dọn.
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step9/full-integration-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
```

Các bài test dùng message mẫu do test tạo; chưa tích hợp Inventory/Payment/Catalog/Identity thật. Không dùng DB/broker dev cho fault test; không thêm đơn hoặc message demo vào Supabase.

## 5. File chính

- [worker.py](../../apps/order-service/src/commerce_order/worker.py): entrypoint và vòng đời worker.
- [repositories/messaging.py](../../apps/order-service/src/commerce_order/repositories/messaging.py), [outbox.py](../../apps/order-service/src/commerce_order/messaging/outbox.py): nhận việc, gửi và xác nhận hoàn tất.
- [schemas.py](../../apps/order-service/src/commerce_order/messaging/schemas.py), [inbox.py](../../apps/order-service/src/commerce_order/messaging/inbox.py), [handlers.py](../../apps/order-service/src/commerce_order/messaging/handlers.py): validate và xử lý event trong transaction.
- [consumer.py](../../apps/order-service/src/commerce_order/messaging/consumer.py): subscribe, ACK, retry và DLQ.
- Test mới: [contract](../../tests/order/test_worker_contracts.py), [PostgreSQL](../../tests/order/test_worker_database.py), [RabbitMQ + PostgreSQL](../../tests/order/test_worker_rabbitmq.py).
