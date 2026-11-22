# Step 2 — Môi trường Order trên máy Mạnh

Ngày thực hiện: **07/11/2026**. Mã nguồn nền: commit `e9cde62`, kèm các tài liệu Order đang chỉnh trong workspace.

**Cập nhật 15/11/2026:** Supabase dev đã cấu hình và kiểm chứng bằng `order_runtime`/`order_migrator` với TLS verify-full, CA `infra/supabase/certs/prod-ca-2021.crt`, DATABASE_ENABLED=true. Migration đã lên `0002_order_tables`; inspect xác nhận runtimeAccess=verified. App Order qua ASGI trả live/ready 200, database=ready, broker tắt riêng khi kiểm tra DB. Xem bằng chứng và checkbox mới trong [plan, Step 2/4](plan.md). Các kết quả/cấu hình ngày 07/11 bên dưới là lịch sử trước lần cập nhật này.

## 1. Kết quả và phạm vi

Đã tạo môi trường Python đúng lockfile, tạo `.env` Order không chứa credential thật, chạy kiểm tra nền và kiểm chứng HTTP Order với PostgreSQL/RabbitMQ test thật trên cùng laptop. Kết nối Supabase dev còn chờ thông tin từ người quản lý database của nhóm.

Phương án áp dụng: **một laptop chạy 5 service, Gateway, frontend và RabbitMQ bằng Docker Compose** khi tích hợp toàn hệ thống. Database dev dùng Supabase theo lựa chọn hiện tại. Không cần lập đầu việc tìm IP các laptop hoặc chia service theo máy. Mỗi người phụ trách code một phần vẫn có thể chạy toàn bộ stack trên một máy.

Lần kiểm chứng này chạy PostgreSQL/RabbitMQ bằng Compose test và chạy riêng API Order bằng Python để đo health thực tế. Chưa build/chạy đủ 5 service/frontend bằng container trong Step 2 của Order. Compose dev hiện đã có các ứng dụng nhưng chưa có container worker nghiệp vụ; bổ sung worker sau khi viết handler ở Step 9, không coi worker monitor là xử lý đơn.

## 2. Đã chuẩn bị trên máy

| Hạng mục | Trước khi làm | Kết quả |
| --- | --- | --- |
| Python | Mặc định máy 3.12.10; repo pin 3.12.8 | Đã tải 3.12.8 vào vùng local của repo, `.venv` dùng đúng 3.12.8 |
| uv | Mặc định máy 0.9.5; repo yêu cầu 0.12.19 | Đã cài uv 0.12.19 riêng tại `infra/.local/order-step2/uv-tool/bin/uv.exe` |
| Dependency | Chưa có `.venv` | `uv sync --locked --all-packages --link-mode copy` thành công; lock check pass, lockfile không đổi |
| Node | v22.19.0 | Khớp pin repo; không cần cài frontend dependency cho Step 2 backend Order |
| Docker | CLI 28.4.0, Compose v2.39.4; engine ban đầu chưa chạy | Đã khởi động Docker Desktop và kết nối Linux engine |
| Order `.env` | Chưa có | Đã copy từ `.env.example`, Git ignore có hiệu lực |
| Cấu hình test | Chưa có | Đã sinh `infra/.local/test.env`, dựng Compose test riêng và chạy prepare |

Không thay phiên bản Python/uv mặc định toàn máy. Các công cụ local, cache, `.venv`, test credentials và log nằm trong đường dẫn Git đã ignore. Docker CLI trong phiên tự động dùng config rỗng riêng vì không đọc được config Docker của user; không ghi đè `~/.docker/config.json`.

### Cấu hình Order tại lần kiểm tra 07/11/2026

- Service `order-service`, HTTP port **3004**, schema **commerce_orders**.
- `DATABASE_ENABLED=false`, `BROKER_ENABLED=false` trong `.env` dev, vì chưa cấu hình Supabase/broker dev cho phiên này.
- `DATABASE_URL` và `MIGRATION_DATABASE_URL` chưa được điền; không có connection string giả làm kết nối hoạt động.
- Khi có Supabase: runtime dùng `order_runtime`, migration dùng `order_migrator`; `DB_SSL_MODE=verify-full`.
- Test chạy bằng biến môi trường tách biệt với `.env` dev, dùng DB `commerce_test` và broker/vhost test. Không dùng hoặc bootstrap/reset Supabase.

## 3. Kiểm tra đã chạy

Các kết quả dưới đây là kết quả thực tế của Step 2, khác với expected nghiệp vụ ở Step 1.

| Kiểm tra | Kết quả |
| --- | --- |
| `uv lock --check` bằng uv local đúng phiên bản | PASS, resolved 56 packages, không sửa lockfile |
| Lint/format Order | PASS, 8 file đã đúng format |
| Typecheck Order | PASS, 6 source file không có lỗi |
| Backend baseline không Docker integration | **79 passed, 5 skipped, 1 warning** |
| Backend có PostgreSQL/RabbitMQ disposable integration | **84 passed, 2 warnings**, không skip, thời gian 77.76 giây |
| Prepare Compose test | PASS: bootstrap 5 schema/role, baseline migration, kiểm tra quyền runtime, topology và smoke broker |
| HTTP Order với DB/broker tắt | `/health/live` 200; `/health/ready` 200, dependency ghi `disabled` |
| HTTP Order với DB/broker test bật | `/health/live` 200; `/health/ready` 200, database và broker đều `ready` |
| Worker Order `--test-stack --once` | PASS: broker `ready`, mode `connectivity_only`, `consumers=0`, process thoát sau kiểm tra |

Warning đã thấy: Starlette TestClient/HTTPX deprecation từ dependency hiện có; suite integration còn báo không ghi được pytest cache trong sandbox. Không có test fail; không che warning hoặc sửa dependency để đổi kết quả kiểm tra.

Hai API được kiểm chứng bằng HTTP thật tại `127.0.0.1:3004`; process kiểm tra đã dừng sau khi lấy kết quả. Readiness ở chế độ disabled chỉ xác nhận bộ khung hoạt động; readiness ở chế độ test mới xác nhận DB/broker test kết nối được. Chưa có bảng/handler nghiệp vụ hoặc consumer đơn hàng.

Test dùng một project Compose riêng theo đường dẫn repo: `commerce-test-de9a754c73`, DB `commerce_test`, PostgreSQL host port 55432, RabbitMQ host port 5673 và management port 15673. Các schema/role của service khác được tạo **trong DB test** vì lệnh prepare kiểm tra ranh giới toàn hệ thống; không ghi vào DB dev của nhóm.

Log và snapshot health nằm trong `infra/.local/order-step2/`, không đưa credential/log runtime lên Git. Bộ helper kiểm chứng ở đó là file local của lần setup, không phải source nghiệp vụ hoặc yêu cầu cài đặt trên mọi máy.

Sau kiểm chứng đã dừng riêng Compose test và API tạm, giữ image, volume test và credential local để bật lại. Docker Desktop vẫn hoạt động. Không có API/worker Order được để chạy nền sau bàn giao này.

## 4. Chạy lại trên chính máy này

Chạy từ root `D:\BTL-WEB`. Các lệnh sau dùng `.venv` đã chuẩn bị; tránh wrapper `dev.ps1` gọi uv 0.9.5 mặc định đang không khớp repo. Có thể dùng wrapper gốc khi PATH đã trỏ uv đúng phiên bản trong một phiên làm việc phù hợp.

```powershell
# Kiểm tra Order.
.\.venv\Scripts\python.exe scripts/dev.py lint order-service
.\.venv\Scripts\python.exe scripts/dev.py typecheck order-service
.\.venv\Scripts\python.exe scripts/dev.py test backend
```

Nếu Docker CLI trong phiên hiện tại cũng không đọc được config user, dùng config local đã tạo; các biến sau chỉ có hiệu lực trong terminal đó:

```powershell
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue

# Bật test stack đã chuẩn bị. Không reset dữ liệu.
.\.venv\Scripts\python.exe scripts/dev.py infra test up
.\.venv\Scripts\python.exe scripts/dev.py infra test status

# Chạy API trên stack test; giữ terminal này mở, dừng bằng Ctrl+C.
.\.venv\Scripts\python.exe scripts/dev.py run order-service --test-stack
```

Mở terminal khác để xem health:

```powershell
Invoke-RestMethod http://127.0.0.1:3004/health/live
Invoke-RestMethod http://127.0.0.1:3004/health/ready
```

Kiểm tra worker monitor bằng terminal đã cấu hình Docker như trên, hoặc chạy suite tích hợp riêng:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py worker order-service --test-stack --once
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration

# Dừng Compose test, giữ dữ liệu/credential để bật lại.
.\.venv\Scripts\python.exe scripts/dev.py infra test down
```

`test backend --integration` tự tạo container disposable riêng và tự dọn khi xong; không dùng/reset stack Compose test thủ công. Không chạy API dev và API test cùng port 3004. Không bật `DATABASE_ENABLED` cho dev bằng URL test hoặc credential lấy từ ví dụ.

## 5. Việc cần đồng đội cung cấp hoặc xác nhận

Trong Step 2, phần còn cần phối hợp là **kết nối database dev thật**. Mạnh không cần hỏi lại UUID, message schema hoặc chọn máy chạy từng service để hoàn thành kiểm tra môi trường local.

| Cần hỏi ai? | Nội dung Mạnh gửi được ngay | Để hoàn tất việc gì? |
| --- | --- | --- |
| Người quản lý Supabase/DB của nhóm | “Cho mình cấu hình kết nối Order bằng role `order_runtime`, database `postgres`, schema `commerce_orders`, loại kết nối direct/session và CA certificate nếu cần. Cấp secret riêng ngoài Git.” | Bật DB dev và đo readiness thật với Supabase |
| Người quản lý Supabase/DB của nhóm | “Schema và quyền Order đã bootstrap chưa? Role runtime đã được cấp quyền đúng chưa?” | Tránh kết nối bằng tài khoản quản trị hoặc tự sửa quyền khi chưa biết hiện trạng |
| Người quản lý DB/người phụ trách migration | “Ai giữ và dùng credential `order_migrator` để áp dụng migration đã review lên dev chung? Mình được chạy hay bạn chạy?” | Có quy trình migration dev; chưa cần để viết/test migration cục bộ |

Không cần gửi mật khẩu/URL có secret vào chat hoặc tài liệu. Khi có thông tin, điền `.env` local/secret config, xác minh đúng project/role/schema/TLS rồi mới bật DB dev; nếu cần migration thì làm theo người phụ trách và quy trình đã thống nhất.

Những việc về auth/Gateway và chi tiết message Inventory/Payment vẫn nằm trong [Step 1](step-1.md). Chúng ảnh hưởng các bước triển khai nghiệp vụ sau, không chặn việc đã kiểm chứng API/DB/broker test ở đây.

## 6. Còn làm gì tiếp?

- Đã kết nối Supabase dev và áp dụng `0002_order_tables` ngày 15/11/2026; tiếp tục dùng cấu hình riêng đã được Git ignore, không dùng DB chung cho test reset/fault.
- Bổ sung consumer/outbox/recovery Order và container worker ở Step 9/14, sau khi có nghiệp vụ; monitor hiện tại chưa xử lý đơn.
- Có thể bắt đầu Step 3 domain/schema ngay, dùng fixture và môi trường test đã chuẩn bị.
