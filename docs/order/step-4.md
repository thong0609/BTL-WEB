# Step 4 — Models và migration cho database Order

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Cập nhật 15/11/2026:** đã áp dụng `0001_base -> 0002_order_tables` lên Supabase dev theo yêu cầu của Mạnh. Có đủ tám bảng Order, model không lệch; constraints/index/history trigger và quyền runtime đã kiểm tra, metadata bốn schema service khác trước/sau không đổi. Lệnh upgrade/check/inspect đều thành công; xem bằng chứng đầy đủ trong [plan, Step 4](plan.md). Các đoạn nói về phạm vi local bên dưới mô tả lần thực hiện ngày 07/11, không phải trạng thái cloud hiện tại.

**Đã triển khai đủ phần code và kiểm chứng local của Step 4.** Có 8 model, migration mới và kiểm thử PostgreSQL thật. Các thao tác DB trong lần này chỉ chạy trên container `commerce_test` tạm do công cụ/test tự tạo và dọn, không kết nối hoặc áp dụng migration lên Supabase dev chung.

## 1. Step 4 làm gì?

Step 3 định nghĩa quy tắc và kiểu dữ liệu. Step 4 tạo **cấu trúc để lưu dữ liệu Order vào PostgreSQL**, gồm đơn, các dòng hàng, lịch sử, tiến trình xử lý và các bảng kỹ thuật chống lặp/gửi message về sau.

Model SQLAlchemy là cách biểu diễn bảng trong Python. Migration Alembic là bản thay đổi có phiên bản, dùng để tạo/cập nhật bảng thực tế. Có model trong code chưa có nghĩa database chung đã được cập nhật; chỉ môi trường nào chạy migration mới có các bảng tương ứng.

Chưa có API tạo/hủy đơn, repository, xử lý idempotency HTTP hoặc worker nghiệp vụ hoàn chỉnh trong bước này. Chúng sẽ sử dụng các bảng này từ Step 5 trở đi.

## 2. Tám bảng đã triển khai

Tất cả nằm trong schema **`commerce_orders`**, dùng Base riêng của Order.

| Bảng | Lưu gì? | Ràng buộc quan trọng |
| --- | --- | --- |
| `orders` | Chủ đơn, người nhận snapshot, tiền, trạng thái, payment mirror/version và mốc thời gian | Mã đơn unique; tiền không âm, total = subtotal + ship, VND; enum và version hợp lệ |
| `order_items` | Sản phẩm/SKU/tên/giá/catalogVersion/số lượng tại lúc đặt | Không trùng productId hoặc SKU trong cùng đơn; quantity 1–999; tiền dòng = đơn giá × số lượng |
| `order_status_history` | Lịch sử chuyển trạng thái, người thao tác, lý do, correlation/message ID | Append-only; trigger PostgreSQL chặn UPDATE/DELETE lịch sử |
| `order_workflows` | Phase/state, bước kho/tiền, operation ID, retry/version và mã giữ hàng | Một workflow/đơn; enum hợp lệ, retry/version không âm; reservationId là UUID tham chiếu ngoài |
| `idempotency_requests` | Key tạo đơn, hash request và response tiếp nhận cũ | Unique `(customer_id, scope, idempotency_key)`; hash SHA-256 hex, response JSON object |
| `order_action_requests` | Key của từng thao tác confirm/cancel/dispatch/complete/exception | Unique `(actor_id, order_id, action, idempotency_key)`; hash và response JSON object |
| `processed_messages` | Dấu message đã xử lý — inbox của Order | PK `(consumer_name, message_id)`; phiên bản dương, payload hash SHA-256 |
| `outbox_messages` | Message sẽ gửi, payload/routing/correlation/causation, retry/lease/status | UUID message ổn định; version/count hợp lệ; payload JSON object, status/exchange/aggregate hợp lệ |

Foreign key chỉ nối các bảng Order với `orders.id`. CustomerId/productId/paymentId/reservationId là UUID tham chiếu logic, không tạo FK/join sang schema của service khác. Các tham chiếu bên ngoài có thể lưu được dù DB test không có bản ghi Identity/Catalog/Inventory/Payment tương ứng; việc xác minh nghiệp vụ do service/API/message phụ trách.

Tiền lưu bằng bigint, ID dùng UUID, thời gian bằng timestamptz. UUID được sinh ở phía ứng dụng khi chưa truyền ID cụ thể; không cần cài extension để tạo UUID trong migration. `created_at`/`updated_at` có default server; ORM/Core update hỗ trợ cập nhật `updated_at`, còn việc tăng/check version trong transaction sẽ được triển khai ở Step 5.

Index phục vụ danh sách dùng `(customer_id, created_at, id)`, `(status, created_at, id)`, `(created_at, id)`; lịch sử cũng có tie-breaker id. Workflow có index state/next_retry, outbox có index status/next_attempt/id, locked_until và aggregate để hỗ trợ claim/recovery sau này.

## 3. File thay đổi

| File | Nội dung |
| --- | --- |
| [models/orders.py](../../apps/order-service/src/commerce_order/models/orders.py) | OrderRecord, OrderItem, OrderStatusHistory và loại actor lịch sử SYSTEM/CUSTOMER/ADMIN |
| [models/workflow.py](../../apps/order-service/src/commerce_order/models/workflow.py) | OrderWorkflow, trong đó có reservation_id |
| [models/idempotency.py](../../apps/order-service/src/commerce_order/models/idempotency.py) | IdempotencyRequest và OrderActionRequest |
| [models/messaging.py](../../apps/order-service/src/commerce_order/models/messaging.py) | ProcessedMessage, OutboxMessage và OutboxStatus |
| [models/_common.py](../../apps/order-service/src/commerce_order/models/_common.py) | UUID/timestamps và enum VARCHAR + CHECK chỉ dùng trong Order |
| [models/__init__.py](../../apps/order-service/src/commerce_order/models/__init__.py) | Đăng ký đủ 8 bảng trên metadata và export model |
| [migrations/env.py](../../apps/order-service/migrations/env.py) | Import model trước khi Alembic đọc Base.metadata |
| [0002_order_tables.py](../../apps/order-service/migrations/versions/0002_order_tables.py) | Tạo 8 bảng/index/constraint và trigger lịch sử; downgrade chỉ gỡ phần Order mới |
| [test_models.py](../../tests/order/test_models.py) | Kiểm tra metadata, scope FK/index/type và SQL migration offline |
| [test_order_database.py](../../tests/order/test_order_database.py) | Kiểm thử schema/migration trên PostgreSQL disposable, dữ liệu thật và role runtime |
| [test_database.py](../../tests/test_database.py) | Điều chỉnh kỳ vọng nền: Order có thêm 8 bảng, các service chưa triển khai nghiệp vụ vẫn chỉ có version table |

Baseline `0001_base.py` được giữ nguyên. Revision `0002_order_tables` đã được sinh từ PostgreSQL test tại baseline và review lại; nội dung migration là DDL tường minh, không import model hiện tại để create_all/drop_all. Nhờ vậy việc đổi model sau này không làm revision cũ đổi ý nghĩa.

Migration không tạo/drop schema, role hoặc bảng của service khác. Enum được lưu bằng VARCHAR + CHECK, không tạo PostgreSQL enum type chia sẻ ngoài phạm vi bảng. Function/trigger append-only thuộc `commerce_orders`, được gỡ khi downgrade revision này.

## 4. Bổ sung reservation_id và thiết kế nguồn

`StockReserved` trong contract đã có `reservationId`, nhưng thiết kế workflow trước đó thiếu nơi lưu. Step 4 thêm **`order_workflows.reservation_id UUID NULL`**:

- NULL trước khi có kết quả giữ hàng.
- Lưu UUID đã xác minh từ Inventory để dùng cho ReleaseStock/CommitStock hoặc đối chiếu.
- Không tạo FK hoặc đổi schema Inventory.
- Không thay field public HTTP hoặc message hiện tại.

Đã cập nhật mục F.12–F.15 trong [thiết kế hệ thống/DB](../design/MO-TA-HE-THONG.md), gồm index phân trang, unique SKU trong đơn, append-only trigger và cột này. Register ORD-OPEN-03 ở [Step 1](step-1.md) ghi rõ phần lưu nội bộ Order đã triển khai; chưa tuyên bố implementation Inventory đã được tích hợp hoặc review.

## 5. Bằng chứng kiểm thử

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Metadata/SQL offline mới | **4 test pass** |
| Test PostgreSQL mới của Order chạy riêng | **19 test pass** |
| Toàn backend gồm PostgreSQL và RabbitMQ thật | **232 passed, 1 warning**, không skip, 75.07 giây |
| Lint/format toàn backend | PASS; 98 file đúng format |
| Typecheck toàn backend | PASS; 61 source file không có lỗi |

Các ca mới xác minh:

- Upgrade từ baseline, upgrade lại, `alembic check` không thấy lệch model/migration và inspect đúng runtime role.
- Lưu/đọc UUID, enum, timestamp có timezone, JSONB và tiền bigint qua SQLAlchemy; default/version/outbox status đúng.
- Mã reservation bên ngoài lưu được mà không có FK sang Inventory.
- PostgreSQL tự chặn dữ liệu sai bằng raw SQL, không chỉ dựa vào Pydantic: tiền âm/sai tổng, currency/status/method không hợp lệ, version âm, NULL ở field bắt buộc và vượt bigint.
- Quantity ngoài giới hạn, sai tiền dòng và catalogVersion âm bị DB từ chối.
- Unique request key có scope, inbox PK theo consumer/message và FK tới đơn được thực thi.
- Lỗi giữa transaction rollback các bản ghi mới của đơn/items/workflow/key/history/inbox/outbox, giữ nguyên dữ liệu đã commit trước đó.
- Runtime Order không được CREATE/TRUNCATE, sửa Alembic version hoặc đọc schema Inventory; không sửa/xóa được history có dữ liệu.
- Downgrade về baseline chỉ còn version table Order, trigger/function mới được gỡ; bảng/dữ liệu sentinel ở `public` và `commerce_inventory` còn nguyên. Upgrade lại và check tiếp vẫn pass.
- Test nền kiểm tra lại bootstrap/grants/migration cho cả 5 service sau khi Order có bảng nghiệp vụ.

Warning cuối là TestClient/HTTPX deprecation kế thừa. Lần chạy riêng ban đầu còn có warning ghi cache giữa sandbox và phiên Docker; lần full cuối dùng thư mục cache riêng cho phiên integration, không tắt test hoặc che warning ứng dụng.

Các container disposable dùng cho sinh migration và test đã được công cụ/fixture dọn sau khi xong. Không thay dữ liệu dev Supabase hoặc reset Compose dev/test đang giữ dữ liệu thủ công của nhóm.

## 6. Chạy lại

Từ root repo, dùng `.venv` đã dựng ở Step 2:

```powershell
# Chỉ kiểm tra cấu trúc và SQL offline, không cần Docker/Supabase.
.\.venv\Scripts\python.exe -m pytest tests/order/test_models.py -q -o cache_dir=infra/.local/order-step4/pytest-cache
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend
```

Để kiểm thử DB thật, bật Docker Desktop. Nếu phiên hiện tại không đọc được config Docker user, dùng config local như Step 2:

```powershell
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue

# Test Order, tự tạo và dọn PostgreSQL riêng.
.\.venv\Scripts\python.exe -m pytest tests/order/test_order_database.py -q --run-postgres -o cache_dir=infra/.local/order-step4/pytest-integration-cache

# Toàn backend, tự tạo DB/broker riêng; không cần reset stack Compose thủ công.
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step4/pytest-integration-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
```

Quy trình migration thật vẫn dùng `scripts/database.py upgrade/current/check/inspect` với đúng role migrator/runtime và target đã xác minh, như [setup DB](../development/SETUP-STEP-3.md). Chạy test ở trên không tự áp dụng revision mới vào Supabase hoặc volume DB khác.

## 7. Riêng Step 4 cần chốt/phối hợp với ai?

**Phần model/migration local đã đủ, không có câu hỏi nghiệp vụ mới bắt buộc trả lời để hoàn thành code Step 4.** Chỉ cần phân biệt việc lưu dữ liệu nội bộ với việc áp dụng lên DB chung:

| Trao đổi với ai? | Nội dung dễ hiểu | Có chặn Step 4 local không? |
| --- | --- | --- |
| Người quản lý DB/Supabase | “Order đã có migration `0002_order_tables`, sau `0001_base`. Ai sẽ review và chạy revision này trên schema `commerce_orders` bằng `order_migrator`, vào thời điểm nào?” | Không. Cần thống nhất trước khi cập nhật DB dev chung |
| Người quản lý DB/Supabase | “Schema/role/TLS và credential Order đã sẵn sàng chưa? Cấp cấu hình qua kênh riêng để xác minh quyền đúng trước khi chạy.” | Không. Tiếp nối cấu hình dev còn thiếu từ Step 2 |
| Inventory — đối chiếu khi tích hợp | “Order sẽ lưu nguyên UUID `reservationId` mà bạn trả trong StockReserved để dùng khi giải phóng/xuất hàng. Response/tra cứu của bạn giữ đúng mã đó nhé.” | Không cần Inventory duyệt cách lưu nội bộ; đây là kiểm tra khớp contract, chưa chạy giao tiếp thật |

Không cần hỏi lại frontend về giới hạn form, phí ship, auth hoặc chọn máy chạy service trong Step 4. Những nội dung đó thuộc bước khác. Không ghi nhận rằng đồng đội đã duyệt migration hay cấp secret khi chưa có thông tin thực tế.

## 8. Chuẩn bị cho Step 5

Step 5 dùng các model này để viết repository và transaction. Khi tạo đơn cần flush header để có ID trước khi thêm các bảng con; toàn bộ vẫn nằm trong cùng transaction. Các cột version/key/lease là hạ tầng lưu trữ, chưa thay thế code lock/version, canonical request hash, replay, claim hoặc ACK-after-commit ở các bước tiếp theo.
