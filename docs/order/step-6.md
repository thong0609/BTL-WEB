# Step 6 — API đọc đơn, quyền truy cập và Gateway

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Đã triển khai repository/query, 4 API đọc đơn và routing Gateway; xác thực token Identity thật còn OPEN.** API runtime đóng mặc định khi chưa có bộ xác minh, không tin danh tính client tự khai. Các test quyền sử dụng principal qua dependency override, không tuyên bố login/token end-to-end đã hoàn tất.

## 1. Bốn endpoint đã có

| Method/route public | Ai được xem? | Nội dung |
| --- | --- | --- |
| GET `/api/v1/orders` | CUSTOMER | Chỉ đơn của mình, gồm PROCESSING/REJECTED |
| GET `/api/v1/orders/{id}` | CUSTOMER sở hữu đơn | Snapshot, history, payment mirror, workflow view và allowedActions |
| GET `/api/v1/admin/orders` | ADMIN | Danh sách toàn cửa hàng, filter status và q |
| GET `/api/v1/admin/orders/{id}` | ADMIN | Chi tiết đơn có cùng khuôn dữ liệu public |

CUSTOMER gọi admin route bị 403. Xem ID của khách khác bị 404, không tiết lộ đơn/địa chỉ. Vai trò ADMIN dùng admin route, không dùng customer route để bỏ qua scope. Các POST tạo/action vẫn thuộc bước sau, chưa được expose trong Step 6.

## 2. Phân trang, tìm kiếm và view

- page từ 1, pageSize 1–100, mặc định 20; UUID/status/query sai trả 400 theo envelope chung.
- Customer luôn thêm customer_id từ principal trong query; không dùng customerId/query/header tự khai.
- Sắp xếp created_at giảm dần rồi id giảm dần; có total và giới hạn số bản ghi.
- Count/page và các truy vấn dựng detail dùng transaction REPEATABLE READ để không ghép dữ liệu từ những snapshot khác nhau khi có writer đồng thời.
- q ADMIN hiện tìm chuỗi con trong orderNumber, không phân biệt hoa/thường; trim đầu/cuối, `%`/`_` được escape như ký tự thường. Chưa tìm theo tên hoặc điện thoại.
- Chỉ map các trường DTO public; không dump ORM/workflow, operation IDs, retry payload hoặc lỗi nội bộ.
- History sắp theo created_at/id; allowedActions lấy từ cùng bộ guard Step 3.
- Money JSON là string, timestamp UTC; snapshot lấy từ Order, không gọi Catalog để tính lại giá đơn cũ.
- Response đọc đơn có `Cache-Control: no-store`, cả trực tiếp Order lẫn qua Gateway.

Đã ghi hành vi tìm kiếm/sắp xếp và trạng thái auth thực tế vào [HTTP contract](../contracts/HTTP-API.md), giữ tên field và endpoint của OpenAPI hiện tại.

## 3. Auth đã làm tới đâu?

[api/dependencies.py](../../apps/order-service/src/commerce_order/api/dependencies.py) có `current_actor` và kiểu `TokenVerifier` bất đồng bộ, trả Actor chứa UUID/vai trò đã xác thực.

- Thiếu Bearer: 401 AUTH_INVALID.
- Có Bearer nhưng chưa cấu hình verifier: 503 AUTH_UNAVAILABLE, không cấp quyền từ nội dung token chưa kiểm chứng.
- Verifier phải trả Actor hợp lệ với UUID và CUSTOMER/ADMIN. Những lỗi xác thực cần được adapter thật chuyển sang ServiceError phù hợp.
- Không đọc X-User-Id/X-Role để cấp danh tính, không có DEV_TOKEN/mật khẩu mặc định hoặc nhánh mock auth bật bằng env.
- Factory Order nhận `token_verifier` qua cấu hình bootstrap bằng code. Entrypoint hiện chưa gắn adapter Identity vì repo chưa có contract xác minh token; đây là phần còn chưa hoàn thành.
- Test quyền dùng `app.dependency_overrides[current_actor]` trong test; không có đường nhận test principal trong API runtime.

Health ready chỉ phản ánh lifespan/DB/broker theo cấu hình; không được dùng để suy ra verifier Identity hoặc login thật đã hoạt động.

## 4. Gateway đã nối như thế nào?

- Thêm ORDER_BASE_URL, mặc định native `http://127.0.0.1:3004`; Compose dev đặt `http://order-service:3004`.
- Thêm đúng 4 GET route cố định. Path ID được validate UUID; query tùy chọn chỉ chuyển page/pageSize/status và q ở admin list; URL do client gửi không chọn được upstream.
- Forward Bearer nguyên bản để Order xác minh, X-Request-Id đã chuẩn hóa và Idempotency-Key nếu có. Không forward X-User-Id/X-Role hoặc cookie khách.
- HTTP client có timeout/pool/lifespan, không dùng proxy env hoặc follow redirect; client được đóng khi shutdown.
- Giữ mã HTTP và public error envelope hợp lệ của Order, chuẩn hóa requestId. Raw text, redirect hoặc response lỗi sai khuôn trả lỗi upstream đã lọc thay vì lộ nội dung.
- ORDER_BASE_URL được làm sạch khỏi env test kế thừa để không vô tình gọi service dev.

Gateway hiện kiểm tra có Bearer trước chuyển tiếp; **chưa tự xác minh JWT/claim của Identity**. Order vẫn phải xác minh ở tầng tài nguyên. Hai việc này không được thay bằng một header role do trình duyệt gửi.

## 5. File chính

- [services/queries.py](../../apps/order-service/src/commerce_order/services/queries.py), [repositories/orders.py](../../apps/order-service/src/commerce_order/repositories/orders.py): đọc dữ liệu và dựng view đúng scope.
- [api/customer.py](../../apps/order-service/src/commerce_order/api/customer.py), [api/admin.py](../../apps/order-service/src/commerce_order/api/admin.py), [api/dependencies.py](../../apps/order-service/src/commerce_order/api/dependencies.py): route và dependency.
- [Order main.py](../../apps/order-service/src/commerce_order/main.py): đăng ký router và verifier seam.
- [Gateway orders.py](../../apps/api-gateway/src/commerce_gateway/orders.py), [Gateway main.py](../../apps/api-gateway/src/commerce_gateway/main.py), [Gateway settings.py](../../apps/api-gateway/src/commerce_gateway/settings.py): fixed upstream và lifecycle/config.
- [Gateway env example](../../apps/api-gateway/.env.example), [Compose dev](../../infra/compose.dev.yaml): URL native/container.
- [tests mới](../../tests/order/test_persistence_and_queries.py): API thật qua ASGI + PostgreSQL, principal override chỉ trong test.

## 6. Kết quả kiểm tra

Lần chạy đầy đủ đầu tiên: 256 test pass, một test RabbitMQ nền đọc dead-letter quá sớm và QueueEmpty. Test đã được sửa để chờ message có giới hạn 5 giây, giữ nguyên assert dead-letter/redelivery và cleanup; không đổi transport nghiệp vụ hoặc bỏ test.

**Kết quả chạy lại cuối: 257 passed, 1 warning, không skip, trong 79.84 giây.** Có 25 ca mới của Step 5–6: 16 ca hash/auth/Gateway và 9 ca PostgreSQL/persistence/query. Warning còn lại là TestClient/HTTPX deprecation kế thừa. Container disposable đã được fixture dọn sau khi test kết thúc.

Lint/format toàn backend đã pass trên 111 file; typecheck pass trên 72 source file. Các test mới đã kiểm chứng: hash/replay, hai request cùng/khác payload cạnh tranh, action cạnh tranh, rollback, A/B/admin scope, PROCESSING/REJECTED, pagination tie-breaker, filter/tìm mã, tiền chuỗi, no-store, spoof header, query sai, requestId, error forwarding và client cleanup.

Test API dùng Order/Gateway app thật với ASGI transport và PostgreSQL test, **không phải token/login thật hoặc toàn bộ container frontend -> Identity -> Order đã được kiểm chứng**. Không chạy migration hoặc đọc dữ liệu Supabase trong Step 5–6.

## 7. Chạy lại

```powershell
# Không cần DB: hash, auth đóng mặc định và Gateway transport contract.
.\.venv\Scripts\python.exe -m pytest tests/order/test_idempotency_and_auth.py -q -o cache_dir=infra/.local/order-step56/unit-cache
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend

# PostgreSQL thật: Docker Desktop phải hoạt động.
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/order/test_persistence_and_queries.py -q --run-postgres -o cache_dir=infra/.local/order-step56/integration-cache

$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step56/full-integration-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
```

Không cần reset DB dev hoặc bật tất cả service để chạy các test này. Container disposable do fixture tự dọn. Không dùng token giả để mở API thủ công trên dev nhằm coi auth đã xong.

## 8. Riêng Step 6 cần chốt với đồng đội

| Trao đổi với ai? | Nội dung cần thống nhất | Có chặn gì? |
| --- | --- | --- |
| Identity + người làm Gateway | “Token đăng nhập được Order xác minh bằng JWT/JWKS hay endpoint kiểm tra? User ID/role nằm ở claim/response nào? Cấu hình issuer/audience/key hoặc URL và lỗi hết hạn cụ thể là gì?” | Chặn adapter xác thực thật và test login/token end-to-end; API đọc/runtime vẫn đóng khi chưa có verifier |
| Gateway | “Dùng 4 route cố định đã thêm, giữ Bearer/requestId và ORDER_BASE_URL đúng host native/Compose. Ai gắn phần kiểm tra token thật vào Gateway/Order theo contract Identity?” | Cần review/gắn adapter khi Identity sẵn sàng; routing/test độc lập đã có |
| Frontend/người phụ trách tìm kiếm ADMIN | “q hiện tìm theo mã đơn, không phân biệt hoa/thường. Nếu cần tìm cả tên/điện thoại thì chốt yêu cầu trước khi mở rộng.” | Không chặn hành vi tìm mã hiện có |

Đây là các điểm trong Step 6. Không cần chọn lại topology máy, chốt phí ship hoặc hỏi Payment/Catalog để triển khai API đọc snapshot của Order.
