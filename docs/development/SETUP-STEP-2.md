# Setup bước 2 — skeleton FastAPI và tiện ích chung

## 1. Kết quả

Gateway và 5 service đã có app factory, settings riêng, lifespan, router health, entrypoint Python, env example và Dockerfile. Package chung cung cấp settings nền, log JSON, request ID, xử lý lỗi và quy ước serialization. Không chứa entity, ORM model hoặc nghiệp vụ.

Chưa triển khai SQLAlchemy session/migration, kết nối Supabase, RabbitMQ worker, auth, đơn hàng hay payment. Frontend vẫn ở mức tooling bước 1.

## 2. Chạy từ gốc repo

```powershell
uv sync --locked --all-packages --link-mode copy

# Terminal 1: Catalog, cổng mặc định 3002
uv run --locked --all-packages python -m commerce_catalog

# Terminal 2: Gateway, cổng mặc định 3000
uv run --locked --all-packages python -m commerce_gateway
```

Mỗi lệnh start chạy trong terminal riêng. Ctrl+C để dừng và chạy teardown lifespan. Không có consumer/outbox worker nào tự khởi động.

| Module chạy bằng `python -m` | Cổng mặc định | App factory |
| --- | --- | --- |
| commerce_gateway | 3000 | commerce_gateway.main:create_app |
| commerce_identity | 3001 | commerce_identity.main:create_app |
| commerce_catalog | 3002 | commerce_catalog.main:create_app |
| commerce_inventory | 3003 | commerce_inventory.main:create_app |
| commerce_order | 3004 | commerce_order.main:create_app |
| commerce_payment | 3005 | commerce_payment.main:create_app |

Tiền tố cho mọi lệnh là `uv run --locked --all-packages`. Nếu chạy Uvicorn CLI trực tiếp với `--factory`, tự truyền host/port; CLI không tự đọc HTTP_PORT của Settings để chọn cổng. Entrypoint `python -m` ở trên có đọc settings và tắt Uvicorn access log để tránh ghi URL/query nhạy cảm.

## 3. Cấu hình

Không cần file .env để chạy skeleton. Khi cần đổi, copy `apps/<service>/.env.example` thành `.env` ở cùng thư mục. Service đọc đúng file của mình bất kể workdir; biến môi trường process có ưu tiên cao hơn file. Không commit .env.

| Biến | Mặc định / ý nghĩa |
| --- | --- |
| SERVICE_NAME | Tên cố định từng service; cấu hình nhầm tên service khác sẽ bị từ chối |
| HTTP_PORT | 3000–3005 theo bảng; validate trong khoảng 1024–65535 |
| HTTP_HOST | 127.0.0.1; dùng 0.0.0.0 nếu cần truy cập từ container/máy khác |
| APP_ENV | dev |
| CORS_ORIGINS | JSON array, mặc định `["http://localhost:3100"]`; không wildcard khi dùng credentials |
| HTTP_TIMEOUT_SECONDS | 5, lớn hơn 0 và tối đa 60 |
| HTTP_MAX_CONNECTIONS | 20, từ 1 đến 100; giới hạn client HTTP của gateway |
| CATALOG_BASE_URL | Chỉ gateway; mặc định http://127.0.0.1:3002, HTTP(S) origin, không userinfo/path/query |
| DATABASE_ENABLED / BROKER_ENABLED | false ở bước 2; true sẽ khiến readiness 503 vì chưa có checker |
| DATABASE_URL / BROKER_URL | SecretStr, chưa được dùng để kết nối ở bước 2 |

Nếu đổi port Catalog thì đổi CATALOG_BASE_URL của gateway tương ứng. Khi dev qua LAN, dùng IP/host truy cập được và thống nhất CORS origin; frontend không nhận credential DB. Đây là cấu hình dev, chưa xác định production.

## 4. Endpoint đã có

- `GET /health/live`: process có thể trả HTTP, không kiểm tra DB/broker.
- `GET /health/ready`: lifespan đã bắt đầu và dependency bắt buộc đã có checker thành công. Hiện DB/broker tắt sẽ ghi `disabled`, không tuyên bố đã kết nối thật. Nếu bật, trả 503 `missing_configuration` hoặc `check_not_implemented`, kể cả đã điền URL.
- `GET /api/v1/health/catalog` trên gateway: gọi cố định `/health/live` của Catalog bằng HTTPX client có lifecycle/timeout/pool. Không proxy URL từ query, không chuyển token/cookie khách sang route health.
- `/docs`, `/openapi.json`: schema tự sinh cho skeleton; không thay thế hợp đồng nghiệp vụ trong docs/contracts.

Ví dụ sau khi start gateway và Catalog:

```powershell
Invoke-RestMethod http://127.0.0.1:3002/health/live
Invoke-RestMethod http://127.0.0.1:3000/health/ready
Invoke-RestMethod http://127.0.0.1:3000/api/v1/health/catalog
```

Gateway readiness chỉ phản ánh skeleton/client lifespan và các dependency đang bật của chính gateway. Muốn kiểm tra Catalog dùng route diagnostic riêng; gateway ready không khẳng định Catalog sẵn sàng xử lý nghiệp vụ.

## 5. Lỗi, log và schema dùng chung

Lỗi có code/message/requestId, details nếu có. Validation trả 400 thay cho 422 mặc định; details.fields chỉ có vị trí/loại lỗi, không echo input, context hoặc thông báo exception có thể chứa secret. HTTPException giữ header cần thiết như WWW-Authenticate nhưng không công khai detail nội bộ. ServiceError dành cho code và thông báo đã được chủ service chọn an toàn. Lỗi bất ngờ trả INTERNAL_ERROR 500.

X-Request-Id hợp lệ dạng UUID được chuẩn hóa và truyền tiếp; thiếu/sai thì tạo UUID mới. Application log JSON có service, request_id, route template, method, status và thời gian xử lý. Không ghi query/body/Authorization hoặc chuỗi exception. Log khởi động Uvicorn có thể vẫn là thông báo text của server, khác log ứng dụng.

ApiModel sử dụng camelCase; UUID serialize chuẩn. MoneyAmount là giá trị int nội bộ không âm, serialize JSON thành chuỗi, không chấp nhận bool/float hoặc chuỗi tùy ý làm giá trị nội bộ. Khi viết request schema tiền dạng chuỗi theo OpenAPI ở bước nghiệp vụ, cần parse/validate riêng rõ ràng. UtcDatetime yêu cầu timezone và chuẩn hóa UTC/Z. Không có endpoint nghiệp vụ giả để minh họa các kiểu này; test dùng route riêng chỉ trong test.

CORS áp dụng cả response lỗi ứng dụng. Preflight dùng hành vi tiêu chuẩn CORSMiddleware; thông báo preflight không phải Error envelope nghiệp vụ.

## 6. Kiểm thử đã chạy

```powershell
uv run --locked --all-packages ruff check apps packages tests
uv run --locked --all-packages ruff format --check apps packages tests
uv run --locked --all-packages mypy
uv run --locked --all-packages pytest -q
uv lock --check
```

Kết quả: **29 test pass**, Ruff/format/mypy pass. Test kiểm tra lifecycle của 6 app, tách settings, readiness khi thiếu checker, chuẩn hóa lỗi, giữ auth header, chống lộ secret, CORS, money/UUID/UTC, request ID đồng thời, timeout/error/redirect/malformed upstream và gateway → Catalog ASGI.

Đã chạy thêm 6 tiến trình Uvicorn thật trên port tạm tránh trùng, kiểm tra HTTP readiness và gateway → Catalog qua TCP. Các tiến trình smoke đã dừng. Lifespan teardown/client close được kiểm chứng trong test; smoke process dùng terminate để thu dọn, không dùng làm bằng chứng graceful shutdown trên môi trường triển khai.

Có một deprecation warning từ Starlette TestClient về HTTPX hiện tại; test vẫn pass. Chưa đổi dependency sang httpx2 vì plan hiện tại dùng HTTPX; cần đánh giá migration riêng nếu bộ test/framework yêu cầu sau này.

## 7. Dockerfile và phần chưa xác minh

Dockerfile có trong từng backend, build context là gốc repo. Cài package bằng lockfile, runtime non-root, host 0.0.0.0 trong container; .dockerignore loại env, dependency/cache và file upload.

```powershell
docker build -f apps/catalog-service/Dockerfile -t commerce-catalog:dev .
docker run --rm -p 3002:3002 commerce-catalog:dev
```

Đây là cách dùng dự kiến; **chưa build/run image thực tế** vì Docker daemon chưa hoạt động trên máy, dù Docker CLI đã có. Không coi Dockerfile đã kiểm chứng. Compose và chạy cả bộ qua container thuộc bước 6.

Ổ D tiếp tục thiếu chỗ khi mypy ghi cache. Cache .mypy_cache đã được chuyển sang vùng dự án riêng trên C và junction về repo. Môi trường cài dở .venv-incomplete của bước 1 cũng được chuyển sang cùng vùng C, không xóa file người dùng. Những đường dẫn này không được commit và không phải yêu cầu của máy khác.

Tham khảo kỹ thuật: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Starlette middleware](https://www.starlette.io/middleware/). Chưa tạo tài nguyên cloud, chưa chạy migration và chưa kiểm thử Supabase/broker.
