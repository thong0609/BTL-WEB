# Setup bước 6 — Lệnh dev, container và môi trường test

## 1. Cách chạy đã chốt

- Mỗi thành viên chạy service trên máy mình và kết nối **Supabase dev chung**. Không tạo PostgreSQL dev mặc định.
- Khi code riêng, dùng **RabbitMQ local** trên máy đó, cùng code nền tảng và hợp đồng [message](../contracts/MESSAGES.md). Message không đi sang broker máy khác. Muốn chạy hết luồng phải có đủ service/worker liên quan và handler đã được viết.
- Khi ghép các service chạy trên nhiều máy, cấu hình cùng broker/vhost. Chưa cấp broker chung hoặc mở cổng máy này ra LAN/cloud.
- Dù broker riêng, dữ liệu ghi vào Supabase vẫn ảnh hưởng cả nhóm. Dùng tài khoản/đơn thử riêng, không reset DB dev; job quét dữ liệu/outbox cần nhóm phân công khi được triển khai.
- Test dùng database/broker riêng. API không tự chạy worker, migration hoặc outbox. Worker base hiện chỉ kiểm tra kết nối.

## 2. File và điều kiện

| File | Mục đích |
| --- | --- |
| `scripts/dev.ps1` | Điểm vào PowerShell, tự xác định root repo và trả exit code |
| `scripts/dev.py` | Chạy/lint/typecheck/test/build theo service và gọi quản lý hạ tầng |
| `scripts/local_stack.py` | Khởi tạo credential local, Compose và bảo vệ reset test |
| `infra/compose.dev.yaml` | RabbitMQ local; profile `apps` có 6 API và Next.js, không có worker/PostgreSQL |
| `infra/compose.test.yaml` | PostgreSQL `commerce_test` và RabbitMQ vhost `commerce_test`, volume riêng |
| `infra/.local/` | Cấu hình/credential runtime sinh trên từng máy, bị Git và Docker build context bỏ qua |

Cần uv/Python/Node theo lockfiles, Docker Desktop Linux engine đang chạy và Docker Compose **2.30+** (dùng env_file `format: raw`). Không cài hoặc nâng phiên bản toàn hệ thống trong bước này. Dockerfile backend từ bước 2 và frontend từ bước 5 được dùng lại.

Các lệnh dưới đây chạy từ root repo. Wrapper PowerShell có thể gọi bằng đường dẫn tuyệt đối từ thư mục khác; nó không phụ thuộc cwd. Nếu PowerShell chặn `.ps1`, dùng lệnh Python tương đương từ root, ví dụ `uv run --locked --all-packages python scripts/dev.py infra dev up`; không cần thay execution policy toàn máy.

## 3. Dev hằng ngày: broker Docker, code chạy trên máy

```powershell
.\scripts\dev.ps1 infra dev init
.\scripts\dev.ps1 infra dev up
.\scripts\dev.ps1 infra dev status
```

`init` sinh password ngẫu nhiên vào `infra/.local/dev.env`; chạy lại giữ nguyên. `up` chỉ bật RabbitMQ, **không khởi động các API hay worker**. Mặc định AMQP `127.0.0.1:5672`, trang quản lý `http://localhost:15672`, user/vhost `commerce_dev`; password xem trong file local, không đưa lên Git/chat. Nếu trùng port, sửa các biến port trong file trước khi khởi động; chạy `init` lại không tự đổi password/port.

Ở terminal riêng cho từng ứng dụng:

```powershell
.\scripts\dev.ps1 run catalog-service
.\scripts\dev.ps1 run api-gateway
.\scripts\dev.ps1 run order-service
.\scripts\dev.ps1 run web
```

Lệnh `run` cho Inventory/Order/Payment mặc định lấy broker local từ file đã sinh, ghi đè `BROKER_URL` **chỉ trong tiến trình con**. `.env` của service không bị sửa. DATABASE_URL vẫn do `.env` service cung cấp cho Supabase. Chạy các service khác tương tự; port theo bước 2, web port 3100. Dừng bằng Ctrl+C. Không có lệnh tự bật mọi worker.

Khi cần dùng broker đã cấu hình trong `.env` hoặc process env thay vì local:

```powershell
.\scripts\dev.ps1 run order-service --broker configured
.\scripts\dev.ps1 broker check order-service --broker configured
```

Topology/smoke local chạy tường minh:

```powershell
.\scripts\dev.ps1 broker topology inventory-service --apply
.\scripts\dev.ps1 broker topology payment-service --apply
.\scripts\dev.ps1 broker topology order-service --apply
.\scripts\dev.ps1 broker smoke order-service --apply
.\scripts\dev.ps1 worker order-service --once
```

Topology không consume. Smoke tạo tài nguyên riêng rồi cleanup, không tạo đơn hoặc payment. `worker` hiện là connectivity monitor, chưa có handler. Nếu muốn điền `.env` bằng tay, mẫu credential host nằm trong `infra/.local/dev-broker.host.env`; không dùng host `rabbitmq` cho ứng dụng chạy ngoài Docker.

```powershell
.\scripts\dev.ps1 infra dev down
```

`down` dừng project dev của clone hiện tại, giữ volume RabbitMQ và credential. Nếu đã bật profile apps, các container ứng dụng trong project cũng được dừng. Không có lệnh reset dev trong wrapper.

## 4. Các ứng dụng chạy bằng container khi cần

```powershell
# DB bị tắt, không đọc env backend dev; kiểm tra bộ khung HTTP/broker local.
.\scripts\dev.ps1 infra dev apps-up --offline
.\scripts\dev.ps1 infra dev status
.\scripts\dev.ps1 infra dev apps-down

# Chủ động chạy với cấu hình Supabase trong .env của từng service.
.\scripts\dev.ps1 infra dev apps-up
```

`apps-up` build trước khi chạy; `apps-build` chỉ build. Đây là chạy image để kiểm tra tích hợp, không có bind-mount source/hot reload; khi sửa code cần build lại hoặc dùng cách chạy native ở mục 3. Dừng các ứng dụng native chiếm port 3000–3005/3100 trước khi chạy container.

Runtime env container được sinh từ các field runtime cho phép của `apps/<service>/.env`, không sao chép migration/bootstrap URL. Broker trỏ `rabbitmq:5672` nội bộ Docker, gateway trỏ `catalog-service:3002`, web build rewrite tới `api-gateway:3000`. Không trỏ `localhost` sang container khác. API bind `0.0.0.0` trong container nhưng port host chỉ publish loopback.

Nếu service bật DB và có `DB_SSL_CA_FILE`, script resolve đường dẫn theo root repo, copy CA vào thư mục local bị ignore và mount read-only vào container; `.env` gốc không đổi. Không giảm kiểm tra TLS. Không chạy bootstrap/migration khi start container. Cấu hình thiếu/sai có thể khiến readiness chưa sẵn sàng dù process liveness hoạt động; kiểm tra `/health/ready` riêng. Compose healthcheck của API dùng liveness để không coi bộ khung là đã kiểm chứng Supabase.

`--offline` kiểm tra HTTP và broker local, chưa xác nhận credential/kết nối Supabase của container. Image chạy bằng user không phải root. Cấu hình Docker này chưa phải deployment production.

## 5. Test Compose riêng và reset có giới hạn

```powershell
.\scripts\dev.ps1 infra test init
.\scripts\dev.ps1 infra test up
.\scripts\dev.ps1 infra test prepare
.\scripts\dev.ps1 infra test status
```

Mặc định PostgreSQL ở `127.0.0.1:55432`, DB `commerce_test`; AMQP ở `127.0.0.1:5673`, user/vhost `commerce_test`; UI broker ở `localhost:15673`. Credential nằm trong `infra/.local/test.env`, khác dev. Project name có hậu tố hash theo đường dẫn repo để tránh nhầm các clone.

`prepare` kiểm tra project/container/port thật, bootstrap 5 schema/role, chạy baseline migration, inspect quyền runtime và khai báo/smoke broker test. Không seed nghiệp vụ, không dùng Supabase. Các subprocess dùng `APP_ENV=test`, bỏ đọc env file dev và xóa settings nhạy cảm kế thừa từ shell trước khi gán endpoint loopback được tạo từ cấu hình test.

Chạy API/worker/diagnostic trên stack test đã prepare:

```powershell
.\scripts\dev.ps1 run catalog-service --test-stack
.\scripts\dev.ps1 worker order-service --test-stack --once
.\scripts\dev.ps1 broker smoke order-service --test-stack --apply
```

Các lệnh này giữ port HTTP mặc định của service; không chạy đồng thời với bản dev trên cùng port.

```powershell
# Giữ dữ liệu test khi dừng.
.\scripts\dev.ps1 infra test down

# Xóa riêng hai volume TEST đã được kiểm tra rồi khởi động test stack rỗng.
.\scripts\dev.ps1 infra test reset --apply
.\scripts\dev.ps1 infra test prepare
```

Reset không chỉ tin `APP_ENV`: allowlist database/vhost, host loopback, port, image, volume local không external/bind-mount, project name và nhãn môi trường/workspace trên tài nguyên thật. Sai target hoặc thiếu `--apply` bị từ chối. Không có tùy chọn reset Supabase, dev broker, project tùy ý hoặc Docker prune. `reset` xóa toàn bộ dữ liệu của **test stack này**, sau đó cần prepare lại.

## 6. Lint/typecheck/test/build

```powershell
.\scripts\dev.ps1 lint all
.\scripts\dev.ps1 typecheck all
.\scripts\dev.ps1 test all
.\scripts\dev.ps1 test backend --integration
.\scripts\dev.ps1 build catalog-service
.\scripts\dev.ps1 build web
.\scripts\dev.ps1 smoke-web
```

Có thể thay `all` bằng `web`, `backend` hoặc tên backend service. Lint/typecheck theo service chỉ xét phần service đó; kiểm tra phần dùng chung bằng `all`/`backend`. Backend base tests hiện kiểm tra hợp đồng chung và nhiều service, nên `test <backend-service>` chạy toàn bộ backend suite, không lọc tùy tiện để bỏ sót kiểm tra.

`test backend --integration` dùng các fixture Docker tạm đã có của pytest, password/port ngẫu nhiên và cleanup khi xong; **không dùng hoặc reset stack Compose đang giữ cho việc test thủ công**. Không cần `infra test up` để chạy suite này. Compose test phục vụ chạy thử API/worker bằng `--test-stack`, kiểm chứng migration và reset local. `test all` mặc định bỏ qua các test cần Docker, frontend chạy 7 test API client. `build web` là Next.js build; `build <backend-service>` là Docker build. Build image frontend bằng `infra dev apps-build --offline` hoặc Dockerfile ở bước 5.

## 7. Kết quả thực thi và giới hạn

Đã kiểm chứng:

- Wrapper PowerShell chạy từ thư mục ngoài repo và giữ đúng root/exit code; init chạy lại giữ nguyên credential.
- Ruff lint/format, mypy 49 file backend, frontend ESLint/TypeScript pass.
- **84 test backend** gồm PostgreSQL/RabbitMQ integration pass; trong đó 12 ca mới kiểm tra target/reset/env. **7 test frontend** pass. Các ca guard liên quan được chạy lại sau khi bổ sung xử lý tên biến không phân biệt hoa/thường.
- Compose test up/prepare: 5 schema/role, baseline migration, quyền runtime và topology/smoke broker pass; API Catalog/Order chạy thật với `--test-stack` và báo DB/broker ready.
- Reset test đã chạy thật: bảng probe trong DB test bị xóa, queue probe trên broker dev còn nguyên; sau đó prepare lại pass. Probe dev được dọn sau kiểm tra. Không reset tài nguyên khác.
- Broker dev local, lệnh topology/smoke, worker monitor `--once` và smoke web qua gateway/Catalog thật pass.
- Build thành công cả **6 image backend và image frontend**. `infra dev apps-up --offline` khởi động đủ 8 container (7 ứng dụng + broker): các API ready, 3 messaging API kết nối broker, web → gateway → Catalog trả đúng kết quả. Kiểm tra runtime xác nhận ứng dụng dùng user không phải root, không chạy worker và không nhận DATABASE_URL/MIGRATION_DATABASE_URL ở chế độ offline.
- `apps-down` dừng riêng 7 ứng dụng, broker vẫn chạy. Các container kiểm chứng được dừng khi bàn giao; giữ image, volume và cấu hình local bị ignore để dùng lại. Chạy `infra dev up` khi cần bật broker.
- Đã thử dev `down` rồi `up`: queue durable probe và credential vẫn dùng được nhờ volume/hostname broker cố định; probe được xóa sau kiểm tra.

Deprecation warning Starlette TestClient/HTTPX kế thừa từ bước trước vẫn còn; không che bằng filter. Không chạy thao tác DB dev/Supabase trong bước này. Chưa làm CI bước 7, handler nghiệp vụ, inbox/outbox, production hoặc broker chung giữa các máy.

Tham khảo: [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/), [startup/healthcheck](https://docs.docker.com/compose/how-tos/startup-order/), [env_file](https://docs.docker.com/reference/compose-file/services/#env_file).
