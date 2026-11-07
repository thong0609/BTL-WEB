# INV-01 — Quản trị tồn kho

Đã triển khai bốn API Inventory dưới `/api/v1/admin/inventory` và routing tương ứng
qua gateway. Phần giữ/giải phóng/xuất hàng, consumer và outbox thuộc INV-02.

## Cấu hình và chạy

Trong `apps/inventory-service/.env`, cấu hình runtime/migrator của Inventory và:

```dotenv
DATABASE_ENABLED=true
DB_SCHEMA=commerce_inventory
IDENTITY_BASE_URL=http://127.0.0.1:3001
CATALOG_BASE_URL=http://127.0.0.1:3002
# CATALOG_SERVICE_TOKEN=<credential riêng do chủ Catalog cấp>
```

Gateway dùng `INVENTORY_BASE_URL=http://127.0.0.1:3003`. Không thay secret có sẵn,
không commit `.env`. Kết nối Identity/Catalog ra ngoài host phải dùng HTTPS;
loopback và DNS `identity-service`/`catalog-service` trong mạng Compose cho phép
HTTP. Compose đã cấu hình URL nội bộ tương ứng. Các HTTP client không theo
redirect hoặc dùng proxy từ env.

Sau khi review migration mới, kiểm thử trên DB test rồi người phụ trách áp dụng:

```powershell
uv run --locked --all-packages python scripts/database.py upgrade --service inventory-service --apply
uv run --locked --all-packages python scripts/database.py check --service inventory-service
uv run --locked --all-packages python -m commerce_inventory
```

API không tự migrate. Revision `0003_inventory_initialize` mở rộng CHECK của
`inventory_operations.operation_type` để cho phép `INITIALIZE`, không sửa revision
đã dùng chung. Downgrade sẽ từ chối nếu còn dữ liệu INITIALIZE; không tự xóa lịch sử.

## Xác thực và phụ thuộc cần ghép

Inventory chuyển bearer token đến Identity `GET /api/v1/users/me`, kiểm tra
`id`, `role=ADMIN`, `status=ACTIVE` theo schema User của public OpenAPI. Không tin
`X-User-Id`/`X-User-Role` từ client, không decode JWT mà bỏ kiểm tra chữ ký, không
có chế độ bỏ qua auth. Token không được gửi sang Catalog.

Khởi tạo kho gọi Catalog `POST /internal/products/batch` theo
[contract nội bộ](../contracts/catalog-internal.openapi.yaml), dùng bearer service
credential `CATALOG_SERVICE_TOKEN` riêng cho Inventory. Catalog xác minh caller,
cho phép lookup cả sản phẩm DRAFT/ngừng bán, trả `{items:[{id: UUID}]}`; sản phẩm
không tồn tại bị bỏ khỏi danh sách. Inventory yêu cầu đúng ID đã hỏi, không lấy
trực tiếp bảng Catalog. Chủ Catalog cần review contract này trước khi tích hợp.
Rotation: cập nhật credential ở Catalog và Inventory theo cửa sổ chuyển đổi đã
thống nhất, restart Inventory để nạp cấu hình mới; không dùng chung token khách.

Identity/Catalog trong repo hiện chưa có các endpoint nghiệp vụ trên. Các test
dùng HTTP contract fixture cho hai dependency, DB PostgreSQL thật và runtime role
giới hạn quyền. Chưa có bằng chứng chạy INV-01 xuyên Identity/Catalog thật; API
sẽ trả 503 khi dependency chưa triển khai hoặc chưa có service credential.

## API và hành vi

| HTTP | Route sau `/api/v1` | Hành vi |
| --- | --- | --- |
| GET | `/admin/inventory?page=1&pageSize=20&lowStock=true` | Tồn kho phân trang, lọc sắp hết |
| POST | `/admin/inventory/items` | Khởi tạo tồn 0, trả 201 |
| POST | `/admin/inventory/adjustments` | Điều chỉnh và trả snapshot mới, 200 |
| GET | `/admin/inventory/{productId}/movements` | Lịch sử phân trang; chưa có mặt hàng trả 404 |

Hai POST đều bắt buộc `Idempotency-Key` 1–128 ký tự, không toàn khoảng trắng.
Response theo [public OpenAPI](../contracts/openapi.yaml): camelCase, Error envelope,
timestamp UTC; không trả actor, request hash hoặc payload nội bộ cho client.

Khởi tạo: `{productId, lowStockThreshold?}` (mặc định 5). Gửi lại cùng sản phẩm với
cấu hình khớp trả snapshot hiện tại, không reset tồn; cấu hình khác trả
`STOCK_CONFIGURATION_CONFLICT` (409). Replay cùng actor/scope/key trả snapshot
đã lưu từ lần đầu, kể cả tồn hiện tại đã thay đổi, và không cần gọi Catalog lại.

Điều chỉnh: `{productId, delta, reason, expectedVersion}`. Delta là integer khác 0,
lý do dài 1–1000 ký tự và không toàn khoảng trắng. Số lượng/threshold/version giới
hạn trong integer PostgreSQL. Không cho phép client sửa reserved trực tiếp.
Khóa hàng trước kiểm tra version và tồn, tăng version một lần khi thành công.
Tồn mới không được nhỏ hơn reserved; vi phạm trả `INSUFFICIENT_STOCK` (409).
Version cũ trả `STOCK_VERSION_CONFLICT` (409), vượt giới hạn số trả
`STOCK_LIMIT_EXCEEDED` (409). Delta dương ghi RECEIPT, delta âm ghi ADJUSTMENT.
Actor lấy từ Identity, cùng lý do và counters sau thao tác ghi vào movement.

Key được ánh xạ UUID ổn định từ actor + scope + key. Request hash gồm cả identity
key và nội dung chuẩn hóa để kiểm tra collision/đổi payload. Advisory transaction
lock bảo vệ cùng operation trước khi lookup; row lock bảo vệ cùng sản phẩm giữa
các key khác nhau. Cùng key khác payload trả `IDEMPOTENCY_CONFLICT` (409).
Kết quả từ chối nghiệp vụ được lưu; muốn xác nhận điều chỉnh lại sau conflict thì
đọc tồn mới và gửi key mới. Lỗi kỹ thuật rollback, có thể retry cùng key.

Stock, operation và movement commit/rollback cùng nhau. Không phát event kho mới
cho adjustment vì contract message hiện chưa quy định event đó. INIT không làm
biến động số lượng nên chỉ ghi operation, chưa có movement.

`lowStock=true` chọn available <= threshold, `false` chọn available > threshold,
bỏ tham số để xem tất cả. Tồn sắp xếp createdAt DESC + productId DESC; movement
createdAt DESC + id DESC. Count và items cùng snapshot đọc. Phân trang bắt đầu
từ 1, pageSize 1–100, mặc định 20; trang vượt cuối trả items rỗng.

## Kiểm thử

Mở Docker Desktop rồi chạy từ root repo:

```powershell
uv run --locked --all-packages python -m pytest tests/test_inventory_api.py tests/test_inventory_models.py tests/test_database.py tests/test_gateway.py --run-postgres -q
```

Test tự tạo PostgreSQL test riêng, bootstrap, migrate tới head và kiểm tra schema
so với metadata. Không sử dụng hoặc reset Supabase dev. Bao phủ auth, replay,
payload conflict, version, reserved, phân trang/lọc, lịch sử, lỗi Catalog,
khởi tạo/điều chỉnh cạnh tranh và rollback khi ghi movement lỗi.

Bằng chứng lần triển khai: bộ backend đầy đủ chạy với `--run-postgres
--run-rabbitmq` có 123 test pass; sau đó bổ sung 5 ca URL upstream/service
credential và chạy nhóm không cần DB của Inventory: 15 test pass (10 ca đã có +
5 ca mới). Ruff lint/format, mypy toàn backend, lockfile và kiểm tra file bàn giao
đều pass. Compose config hợp lệ khi cấp các biến cấu hình bắt buộc bằng giá trị
test. Có một deprecation warning Starlette/TestClient đã có từ base.
Chưa áp dụng revision mới hoặc kiểm thử INV-01 lên Supabase dev trong đợt này.
