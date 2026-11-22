# Chạy và xử lý lỗi Order

Chạy lệnh từ root repository. Máy Mạnh dùng `.venv\Scripts\python.exe` và `npm.cmd` (PowerShell chặn `npm.ps1`). Máy mới cần Python 3.12.8, uv 0.12.19, Node 22.19.x/npm 10.9.x và Docker Desktop Linux engine theo [setup](../development/SETUP-STEP-1.md).

**Hiện trạng:** backend/giao diện Order đã có; auth, Catalog và Inventory/Payment thật chưa ghép. API có thể health được nhưng chưa đặt hàng thật qua UI. Chạy test độc lập theo mục 5 để kiểm tra ngay mà không cần service của đồng đội.

## 1. Cấu hình

- Nếu đã có `.env`, giữ nguyên. Máy mới copy `apps/order-service/.env.example` thành `.env` trong cùng thư mục; copy `apps/api-gateway/.env.example` và `apps/web/.env.example` tương tự.
- `DATABASE_URL`: tài khoản `order_runtime`; `MIGRATION_DATABASE_URL`: `order_migrator`; schema `commerce_orders`. Không dùng tài khoản quản trị để chạy API/worker.
- Supabase dùng Session pooler theo cấu hình nhóm, `DB_SSL_MODE=verify-full` và CA đúng máy. Chỉ bật `DATABASE_ENABLED=true` sau khi cấu hình xong.
- Quote mới cần `CATALOG_BASE_URL`, `CATALOG_SERVICE_TOKEN` và `SHIPPING_FEE_AMOUNT` do nhóm chốt; **không có phí ship mặc định 30000**.
- Worker cần `BROKER_ENABLED=true` và broker/vhost đúng môi trường. Recovery mặc định tắt; chỉ bật sau khi có API/token Inventory/Payment thật.
- Frontend chỉ có `GATEWAY_URL`; không đưa URL database, secret nội bộ hoặc key Supabase vào frontend.

Không đưa `.env`, log chứa dữ liệu, certificate hoặc dump DB lên Git. Thay `GATEWAY_URL` cần restart frontend dev hoặc rebuild image.

## 2. Kiểm tra và migration

```powershell
.\.venv\Scripts\python.exe scripts/database.py current --service order-service
.\.venv\Scripts\python.exe scripts/database.py check --service order-service
.\.venv\Scripts\python.exe scripts/database.py inspect --service order-service
```

Revision mới nhất: `0003_action_audit`; thêm cột JSON nullable lưu input action. Supabase của Mạnh đã áp dụng ở Step 14, **không cần chạy lại**. Với môi trường mới đã được bootstrap đúng role/schema, sau khi kiểm tra thay đổi và chọn đúng DB:

```powershell
.\.venv\Scripts\python.exe scripts/database.py upgrade --service order-service --apply
```

Migration chạy riêng bằng migrator. API và worker không tự chạy migration. Không downgrade/reset Supabase để thử lỗi. Test suite tự tạo/migrate/restore database disposable của chính nó.

## 3. Chạy native để debug

Giữ mỗi tiến trình ở một terminal, dừng bằng Ctrl+C. Cấu hình `.env` trước; không chạy hai bản API cùng port.

```powershell
# Khởi tạo cấu hình broker local nếu chưa có; không ghi đè .env Order.
.\.venv\Scripts\python.exe scripts/dev.py infra dev init
.\.venv\Scripts\python.exe scripts/dev.py infra dev up

# Terminal API: đọc cấu hình DB/broker của Order.
.\.venv\Scripts\python.exe scripts/dev.py run order-service --broker configured
# Terminal Gateway: port 3000.
.\.venv\Scripts\python.exe scripts/dev.py run api-gateway
# Terminal frontend: port 3100.
npm.cmd --prefix apps/web run dev
```

Sau khi Inventory/Payment sẵn sàng, mở terminal worker riêng. `--broker local` lấy broker do script init tạo, không cần copy password bằng tay:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py worker order-service --mode all --broker local
```

Nếu dùng `BROKER_URL` đã cấu hình trong `.env`, chọn `--broker configured`. Không chạy đồng thời worker native và Compose chỉ để thử trên dữ liệu dev chung.

| Mode | Công việc | `--once` |
| --- | --- | --- |
| monitor (mặc định) | Kiểm tra kết nối; không xử lý đơn | Một lượt kiểm tra |
| outbox | Phát command đang chờ | Một batch hữu hạn |
| consumer | Nhận event | Một batch hữu hạn, tối đa ORDER_OUTBOX_BATCH_SIZE message sẵn có |
| recovery | Tra cứu đơn treo qua HTTP | Một batch hữu hạn; cần DB/token nhưng không cần broker |
| all | Outbox + consumer; thêm recovery nếu đã bật | Một lượt theo ý nghĩa từng loop |

Recovery có thể chạy riêng bằng `python -m commerce_order.worker --run --mode recovery --once`. Không bật job này khi API tra cứu của đồng đội còn chưa triển khai. Khi dùng `all`, mặc định recovery vẫn tắt.

## 4. Một laptop chạy bằng Compose

Sau khi cấu hình các service đã sẵn sàng:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py infra dev init
.\.venv\Scripts\python.exe scripts/dev.py infra dev apps-up
```

Script tạo env runtime trong `infra/.local/apps/`, copy CA sang chỗ mount trong container, đặt broker hostname nội bộ. Không copy credential migrator vào container. Profile apps bật 5 API + Gateway + web; worker có profile riêng, cần bật rõ khi bắt đầu tích hợp:

```powershell
# Dùng đúng Compose project/env của script; không tự tạo project thứ hai.
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'scripts'); from local_stack import LocalStack; LocalStack('dev').compose('--profile', 'order-workers', 'up', '--detach', '--build', 'order-worker')"
```

Trong container, các service gọi nhau bằng tên `catalog-service`, `inventory-service`, `payment-service`, không dùng localhost. Worker/API dùng chung image Order, chạy entrypoint khác nhau. Cổng trên máy: Gateway 3000, Identity 3001, Catalog 3002, Inventory 3003, Order 3004, Payment 3005, web 3100; RabbitMQ 5672/management 15672 chỉ bind loopback.

Dừng worker trước khi dừng stack; giữ dữ liệu broker:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'scripts'); from local_stack import LocalStack; LocalStack('dev').compose('--profile', 'order-workers', 'stop', 'order-worker')"
.\.venv\Scripts\python.exe scripts/dev.py infra dev down
```

Các lệnh khởi chạy dev ở mục này là hướng dẫn tích hợp, **chưa được chạy trong Step 15–16**. Lần này chỉ init/config-check; không bật worker trên dữ liệu Supabase chung.

## 5. Kiểm tra trước bàn giao

```powershell
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
npm.cmd --prefix apps/web run lint
npm.cmd --prefix apps/web run typecheck
npm.cmd --prefix apps/web test
npm.cmd --prefix apps/web run test:e2e
npm.cmd --prefix apps/web run build
.\.venv\Scripts\python.exe scripts/dev.py smoke-web
docker build -f apps/order-service/Dockerfile -t commerce-order-service:step16 .
docker build -f apps/web/Dockerfile --build-arg GATEWAY_URL=http://api-gateway:3000 -t commerce-web:step16 .
.\.venv\Scripts\python.exe scripts/order_image_smoke.py --web-image commerce-web:step16
```

Trước test:e2e, cài Chromium theo [frontend-handoff](frontend-handoff.md#6-kiểm-tra-frontend-độc-lập). Không chạy build/dev/e2e đồng thời trong cùng `apps/web`. Test dùng cổng tạm/3191; dừng frontend đang chạy nếu cần giải phóng lock Next.

Trên máy Mạnh, nếu terminal tự động không đọc được Docker config user, cấu hình riêng terminal:

```powershell
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step1516/full-cache'
```

Không cần cấu hình riêng này trên máy Docker chạy bình thường. Kết quả thực tế và các giới hạn nằm ở [test-results](test-results.md), hướng dẫn sáu ca ở [demo](demo.md).

## 6. Xử lý lỗi thường gặp

| Dấu hiệu | Kiểm tra / xử lý |
| --- | --- |
| UI login 404/503 hoặc AUTH_UNAVAILABLE | Identity/routing Gateway/verifier Order chưa ghép; không thay bằng token tự khai |
| Quote 503 | Kiểm tra phí ship, credential Catalog, API nội bộ và URL; chưa tạo đơn thì chưa giữ key |
| POST timeout/5xx | Bấm gửi lại yêu cầu đang lưu; giữ nguyên key/body, không tạo đơn khác để thử |
| PRICE_CHANGED | Xem giá/phí mới rồi xác nhận lại; không tự chấp nhận giá mới |
| Đơn PROCESSING/CANCELLING lâu | Kiểm tra outbox, worker consumer, broker và event đúng operation; giữ trạng thái nếu chưa rõ kết quả |
| Outbox NEEDS_ATTENTION | Kiểm tra routing, confirm, last_error và producer; không tự đánh PUBLISHED hoặc đổi messageId |
| Message vào `order.events.dead` | Xem request/correlation ID và mã lỗi, sửa nguyên nhân rồi phối hợp replay; không xóa queue hoặc tạo event thành công tay |
| PaymentVersion bị nhảy | Đợi đối chiếu snapshot có xác thực và message gốc; không tắt kiểm tra version |
| Refund lỗi | Chờ kết quả/recovery đúng operation; không tạo refund mới hoặc giải phóng lại nhánh kho đã xong |
| DB/certificate lỗi | Kiểm tra URL runtime/migrator, CA và quyền schema; không tắt verify-full cho Supabase |

Chỉ ghi ID và mã lỗi khi trao đổi lỗi; không gửi password, token, connection string hoặc địa chỉ khách vào log/chat. Sửa lỗi nghiệp vụ bằng use case/replay đã kiểm tra, không sửa trạng thái đơn trực tiếp trong database.
