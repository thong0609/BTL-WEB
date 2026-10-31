# Hướng dẫn chạy dự án

Tài liệu dành cho thành viên mới và việc chạy hằng ngày, dùng PowerShell trên Windows. Các lệnh chạy tại **thư mục gốc repo**, nơi có `pyproject.toml`, `uv.lock`, `apps/`, `scripts/`; không yêu cầu đặt repo ở ổ D hay cùng đường dẫn với người khác.

Hiện dự án có bộ khung API, database/migration, RabbitMQ và trang kiểm tra kết nối. Chưa có đăng nhập, sản phẩm, checkout, handler nghiệp vụ hoặc seed dữ liệu. Chạy thành công hiện nghĩa là bộ khung hoạt động, chưa phải một cửa hàng đã đủ chức năng.

## 1. Chọn cách chạy và hiểu việc migration

| Nhu cầu | Cách chạy |
| --- | --- |
| Code hằng ngày | API/frontend chạy trên máy; DB Supabase dùng chung; RabbitMQ local bằng Docker. Làm mục 2–6 |
| Chưa có credential Supabase, muốn xem bộ khung | Dùng container `--offline` tại mục 9 hoặc test DB riêng tại mục 10 |
| Thử migration, reset dữ liệu, chạy test | Dùng PostgreSQL/RabbitMQ test riêng tại mục 10 |
| Ghép service trên nhiều máy | Các phần liên quan dùng cùng broker/vhost và endpoint HTTP; xem mục 11 |

**Có phải chạy migration khi khởi động không?**

| Tình huống | Việc cần làm |
| --- | --- |
| Thành viên mới clone repo, Supabase đã có đủ schema/revision | Không bootstrap/migrate lại vì đổi máy. Nhận runtime credential, cấu hình env rồi chạy |
| Supabase mới hoàn toàn, chưa có role/schema | Người quản lý DB làm mục 8 một lần: bootstrap rồi baseline migration |
| Pull code có migration mới chưa áp dụng lên Supabase | Người phụ trách service chạy migration đã thống nhất một lần trên DB chung, rồi thông báo nhóm |
| Tắt/mở máy, khởi động lại API hoặc RabbitMQ | Không cần migration nếu schema/revision không đổi |
| Test DB mới tạo hoặc vừa reset | Chạy `infra test prepare`; script tự bootstrap/migrate đúng DB test |

API và lệnh start container **không tự chạy migration**. Gateway và frontend không có database riêng, không chạy Alembic. Hiện baseline `0001_base` chỉ tạo version table; chưa tạo bảng nghiệp vụ trong tài liệu thiết kế.

## 2. Máy mới: công cụ, clone và cài dependency

Chuẩn bị Git, Docker Desktop dùng Linux engine và bộ công cụ sau:

| Công cụ | Phiên bản dự án |
| --- | --- |
| Node.js | 22.19.0, xem `.node-version` / `.nvmrc` |
| npm | 10.9.3, xem `apps/web/package.json` |
| uv | 0.12.19, được kiểm tra trong `pyproject.toml` |
| Python của dự án | 3.12.8; uv có thể cài giúp, không cần đổi Python hệ thống |
| Docker Compose | 2.30 trở lên; dùng bản đi kèm Docker Desktop phù hợp |

Nếu chưa có uv và máy đã có Python/pip, có thể cài bản đã khóa bằng `py -m pip install --user uv==0.12.19`. Bảo đảm lệnh `uv` có trên PATH, mở lại terminal sau khi cài công cụ.

```powershell
git --version
uv --version
node --version
npm --version
docker compose version
```

Nếu chưa có repo:

```powershell
git clone https://github.com/thong0609/BTL-WEB.git
cd BTL-WEB
```

Nếu đã mở repo trong IDE thì mở terminal tại root hiện có, bỏ qua clone. Cài dependency:

```powershell
uv python install 3.12.8
uv sync --locked --all-packages
npm --prefix apps/web ci
```

`uv sync` mặc định tạo virtualenv `.venv` tại root. Các lệnh `uv run` và wrapper dưới đây tự dùng môi trường này, không cần activate thủ công. IDE Python chọn interpreter `.venv/Scripts/python.exe`. Dependency frontend nằm trong `apps/web/node_modules`; không copy `.venv` hoặc `node_modules` của người khác.

Các lệnh `.\scripts\dev.ps1` tự xác định root repo. Nếu PowerShell chặn script, thay tiền tố đó bằng `uv run --locked --all-packages python scripts/dev.py`, giữ nguyên phần tham số và chạy tại root. Ví dụ:

```powershell
uv run --locked --all-packages python scripts/dev.py run catalog-service
```

## 3. Máy mới: tạo và cấu hình env

### 3.1. Copy template, giữ nguyên file đã cấu hình

Chạy một lần; đoạn này chỉ tạo file chưa tồn tại:

```powershell
$commerceServices = @(
    "api-gateway", "identity-service", "catalog-service",
    "inventory-service", "order-service", "payment-service"
)
foreach ($commerceService in $commerceServices) {
    $commerceEnvPath = "apps/$commerceService/.env"
    if (-not (Test-Path -LiteralPath $commerceEnvPath)) {
        Copy-Item -LiteralPath "apps/$commerceService/.env.example" -Destination $commerceEnvPath
    }
}
if (-not (Test-Path -LiteralPath "apps/web/.env.local")) {
    Copy-Item -LiteralPath "apps/web/.env.example" -Destination "apps/web/.env.local"
}
```

Không cần tạo `.env` chung ở root. API đọc `.env` trong thư mục service mình; Next.js đọc `.env.local` trong `apps/web`. Các file thật bị Git ignore. Không gửi password/token trong chat, commit hoặc ảnh log.

### 3.2. Gateway và frontend

Giữ ở `apps/api-gateway/.env`:

```dotenv
APP_ENV=dev
DATABASE_ENABLED=false
BROKER_ENABLED=false
CATALOG_BASE_URL=http://127.0.0.1:3002
```

Các field còn lại như tên service và port giữ theo template. Ở `apps/web/.env.local`:

```dotenv
GATEWAY_URL=http://127.0.0.1:3000
```

Browser gọi `/api/v1` cùng origin; Next.js chuyển tiếp tới gateway. Frontend không cần DATABASE_URL, password DB, Supabase service-role key hoặc BROKER_URL. GATEWAY_URL là biến server-side; đổi nó cần restart dev hoặc rebuild image frontend.

### 3.3. DB cho từng service

Hỏi người quản lý DB của nhóm trước: **project đã bootstrap chưa, schema đã ở revision nào, ai chịu trách nhiệm migration?** Nhận project ref, session pooler host, runtime credential của service cần chạy và CA tin cậy nếu cần. Người chạy migration cần thêm migrator credential; thành viên chỉ chạy API không bắt buộc giữ credential đó.

Ví dụ cấu hình Catalog trong `apps/catalog-service/.env`:

```dotenv
APP_ENV=dev
DATABASE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://catalog_runtime.PROJECT_REF:RUNTIME_PASSWORD@POOLER_HOST:5432/postgres
MIGRATION_DATABASE_URL=postgresql+asyncpg://catalog_migrator.PROJECT_REF:MIGRATOR_PASSWORD@POOLER_HOST:5432/postgres
DB_SCHEMA=commerce_catalog
DB_SSL_MODE=verify-full
DB_SSL_CA_FILE=infra/supabase/certs/supabase-ca.crt
```

Đây là **mẫu session pooler**, phải thay placeholder trước khi dùng. `PROJECT_REF` và `POOLER_HOST` do project Supabase cung cấp; password là của đúng custom role, không tự dùng password quản trị cho mọi role. Nếu password có ký tự đặc biệt, URL-encode **phần password**, không encode cả connection string. Dự án hiện hỗ trợ direct/session connection; port 6543 transaction pooler không được chấp nhận trong base này.

Không copy nguyên username/schema Catalog sang các service khác:

| Service | Schema | Runtime user trước hậu tố `.PROJECT_REF` | Migrator user trước hậu tố `.PROJECT_REF` |
| --- | --- | --- | --- |
| identity-service | commerce_identity | identity_runtime | identity_migrator |
| catalog-service | commerce_catalog | catalog_runtime | catalog_migrator |
| inventory-service | commerce_inventory | inventory_runtime | inventory_migrator |
| order-service | commerce_orders | order_runtime | order_migrator |
| payment-service | commerce_payments | payment_runtime | payment_migrator |

`MIGRATION_DATABASE_URL` chỉ cần khi dùng Alembic; có thể để dòng này ở comment nếu không được phân công migration. Nếu chưa dùng DB cho một service, giữ `DATABASE_ENABLED=false` và để URL chưa cấu hình. Khi ấy health không xác nhận kết nối DB cho service đó.

Nếu có CA từ nguồn Supabase tin cậy, lưu đúng file `infra/supabase/certs/supabase-ca.crt` trên máy mình. Đường dẫn trong env là tương đối với root repo, không copy đường dẫn ổ D của người khác. Nếu hệ thống đã xác minh được chuỗi CA mà không cần file riêng, để `DB_SSL_CA_FILE` ở comment; vẫn giữ `verify-full`.

### 3.4. RabbitMQ: wrapper tự chọn local

Với `dev.ps1 run` cho Inventory/Order/Payment, wrapper mặc định lấy BROKER_URL của broker local tại mục 5, bật broker trong **tiến trình con**. Vì vậy có thể giữ BROKER_URL trong `.env` ở comment; wrapper không sửa file `.env`.

Nếu chạy thẳng `python -m commerce_order` thay vì wrapper thì phải tự đặt `BROKER_ENABLED=true` và URL phù hợp trong env. Credential host local được sinh trong `infra/.local/dev-broker.host.env`; không copy credential broker của máy người khác.

## 4. Kiểm tra DB đã sẵn sàng trước khi chạy

Nếu Supabase đã có role/schema và revision đầy đủ, **bỏ qua bootstrap/upgrade**, chuyển tới mục 5. Người có migrator credential có thể đọc revision hiện tại:

```powershell
# Đọc revision đã áp dụng lên DB được cấu hình của Catalog.
uv run --locked --all-packages python scripts/database.py current --service catalog-service

# Xem head trong source code, không kết nối DB.
uv run --locked --all-packages alembic -c apps/catalog-service/alembic.ini heads

# Kiểm tra quyền runtime trên DB đã có baseline.
uv run --locked --all-packages python scripts/database.py inspect --service catalog-service
```

Thay tên service/config path tương ứng nếu kiểm tra service khác. Nếu không có migrator credential, nhờ người phụ trách xác nhận revision; không cần xin tài khoản quản trị để chỉ chạy API.

`current` và `heads` dùng để đối chiếu revision. Lệnh `database.py check` là Alembic kiểm tra chênh lệch model/schema qua autogenerate, không phải lệnh áp dụng migration. Readiness `/health/ready` kiểm tra dependency/quyền cơ bản, không đảm bảo database đã ở revision head.

## 5. Máy mới: tạo RabbitMQ local

Mở Docker Desktop và chờ engine sẵn sàng:

```powershell
docker info --format '{{.ServerVersion}}'
.\scripts\dev.ps1 infra dev init
.\scripts\dev.ps1 infra dev up
.\scripts\dev.ps1 infra dev status
```

`init` tạo credential local trong `infra/.local/dev.env`, chạy lại giữ nguyên. `up` chỉ bật RabbitMQ; không bật PostgreSQL dev, API hoặc worker. Mặc định AMQP port 5672, UI `http://localhost:15672`, user/vhost `commerce_dev`; password xem trong file local. Không cần một máy thứ sáu để thực hiện cách chạy này.

Khai báo topology lần đầu trên broker local:

```powershell
.\scripts\dev.ps1 broker topology inventory-service --apply
.\scripts\dev.ps1 broker topology payment-service --apply
.\scripts\dev.ps1 broker topology order-service --apply
.\scripts\dev.ps1 broker smoke order-service --apply
```

Các lệnh tạo exchange/queue/binding, không khởi động consumer hay tạo đơn. Có thể declare lại cùng cấu hình; không cần chạy lại mỗi sáng nếu volume vẫn còn. Chạy lại khi broker mới/volume mới hoặc contract topology thay đổi theo nhóm. `smoke` dùng tài nguyên riêng rồi cleanup.

## 6. Chạy code trên máy và kiểm tra

Mỗi dòng start dưới đây chạy ở **một terminal riêng**, đều mở tại root repo. Chỉ chạy các phần cần thiết; muốn kiểm tra trang web hiện tại tối thiểu cần Catalog, gateway và web.

```powershell
# Terminal 1
.\scripts\dev.ps1 run catalog-service
```

```powershell
# Terminal 2
.\scripts\dev.ps1 run api-gateway
```

```powershell
# Terminal 3
.\scripts\dev.ps1 run web
```

Các API còn lại, mỗi lệnh ở terminal riêng nếu cần:

```powershell
.\scripts\dev.ps1 run identity-service
.\scripts\dev.ps1 run inventory-service
.\scripts\dev.ps1 run order-service
.\scripts\dev.ps1 run payment-service
```

| Ứng dụng | Port mặc định | Địa chỉ kiểm tra |
| --- | --- | --- |
| Gateway | 3000 | `http://localhost:3000/health/ready` |
| Identity | 3001 | `http://localhost:3001/health/ready` |
| Catalog | 3002 | `http://localhost:3002/health/ready` |
| Inventory | 3003 | `http://localhost:3003/health/ready` |
| Order | 3004 | `http://localhost:3004/health/ready` |
| Payment | 3005 | `http://localhost:3005/health/ready` |
| Frontend | 3100 | `http://localhost:3100` |

API có `/health/live` để xem process còn chạy và `/docs` để xem Swagger của phần đã triển khai. Ví dụ:

```powershell
Invoke-RestMethod http://localhost:3002/health/ready
Invoke-RestMethod http://localhost:3000/api/v1/health/catalog
```

Mở frontend và bấm **Kiểm tra kết nối**. Thành công chỉ xác nhận web → gateway → Catalog liveness; muốn biết DB/broker có dùng được phải xem `/health/ready` của service. Giá trị `disabled` nghĩa là dependency đang tắt, không phải đã kiểm tra thành công dependency đó.

Backend trong wrapper hiện không bật auto-reload: sau khi sửa code cần Ctrl+C và chạy lại service. Frontend chạy Next.js dev để cập nhật khi sửa UI.

**Worker có cần chạy không?** Hiện chưa có consumer nghiệp vụ. Không cần mở worker để dùng trang kiểm tra kết nối. Có thể kiểm tra broker bằng monitor:

```powershell
.\scripts\dev.ps1 worker order-service --once
```

Bỏ `--once` sẽ theo dõi liên tục; Ctrl+C để dừng. Monitor không giữ hàng, xử lý thanh toán hay chuyển trạng thái đơn. Khi có handler/outbox trong các đợt sau, nhóm sẽ bổ sung quy trình chạy worker tương ứng.

## 7. Những lần chạy tiếp theo

Nếu không đổi dependency/schema/env thì không cần clone, copy env, cài lại package, bootstrap hoặc migration. Làm như sau:

1. Mở Docker Desktop, terminal tại root repo.
2. Bật broker local bằng lệnh dưới.
3. Mở các terminal và chạy những service/web cần dùng như mục 6.
4. Kiểm tra readiness/trang web nếu cần.

```powershell
.\scripts\dev.ps1 infra dev up
```

Kết thúc công việc:

```powershell
# Ctrl+C trong từng terminal đang chạy API/web/worker, sau đó:
.\scripts\dev.ps1 infra dev down
```

`down` giữ volume RabbitMQ và credential local. Supabase là DB chung trên cloud, không bị tắt/reset bởi lệnh này. Giữ thư mục `infra/.local/` để lần sau dùng lại credential đúng với volume; không copy thư mục này giữa các máy.

Sau khi lấy code mới theo quy trình Git của nhóm, xem phần thay đổi:

| Thay đổi | Việc cần làm |
| --- | --- |
| `uv.lock` / dependency Python | `uv sync --locked --all-packages` |
| `apps/web/package-lock.json` / dependency frontend | `npm --prefix apps/web ci` |
| `.env.example` có field mới | Bổ sung vào `.env` cá nhân, không chép đè làm mất URL/password đã điền |
| Migration mới | Nhờ người phụ trách kiểm tra và áp dụng lên DB chung nếu còn thiếu; không cả nhóm cùng chạy |
| Code backend | Restart service đang chạy |
| Env hoặc GATEWAY_URL | Restart ứng dụng liên quan; image frontend cần rebuild nếu đổi rewrite |
| Topology message | Theo thay đổi contract và hướng dẫn cập nhật broker; không tự xóa queue đang dùng |

## 8. Phần dành cho người quản lý DB / người chạy migration

### 8.1. Supabase mới chưa chuẩn bị: bootstrap một lần

Bỏ qua nếu project đã được nhóm bootstrap. Nhóm chỉ định một người có quyền quản trị thực hiện; thành viên mới không chạy lại bước này để bắt đầu code.

Nếu chưa có file quản trị:

```powershell
if (-not (Test-Path -LiteralPath "infra/supabase/.env.bootstrap")) {
    Copy-Item -LiteralPath "infra/supabase/bootstrap.env.example" -Destination "infra/supabase/.env.bootstrap"
}
```

Điền trong file bị ignore này: `SUPABASE_PROJECT_REF`, `BOOTSTRAP_DATABASE_URL` của đúng project dev, TLS/CA nếu cần và các password runtime/migrator theo template. Dùng credential quản trị để bootstrap, sau đó API dùng runtime role riêng. Không đặt APP_ENV của terminal quản trị ở `test`.

Nạp file vào tiến trình bootstrap bằng uv:

```powershell
uv run --env-file infra/supabase/.env.bootstrap --locked --all-packages python scripts/database.py bootstrap --target dev --apply
```

`database.py` không tự đọc `.env.bootstrap`; `--env-file` ở lệnh trên thực hiện phần nạp đó. Bootstrap tạo schema/role/grants, **không thay migration bảng**. Chạy lại bootstrap có thể áp lại password trong file, nên chỉ làm khi đã phối hợp với nhóm. Xem [quy trình Supabase](../../infra/supabase/README.md) và [bước 3](SETUP-STEP-3.md) để biết giới hạn role/TLS.

### 8.2. Áp dụng baseline hoặc migration mới

Sau khi bootstrap và cấu hình `.env` service với đúng migrator URL, người phụ trách chạy từng service được phân công. Ví dụ Catalog:

```powershell
uv run --locked --all-packages python scripts/database.py upgrade --service catalog-service --apply
uv run --locked --all-packages python scripts/database.py current --service catalog-service
uv run --locked --all-packages python scripts/database.py inspect --service catalog-service
```

Khi DB mới, cần thực hiện cho cả `identity-service`, `catalog-service`, `inventory-service`, `order-service`, `payment-service`; Gateway/web không có migration. Khi chỉ một service có revision mới, chỉ người phụ trách phần đó cần áp dụng revision đã được review/đồng ý. Nếu lệnh lỗi thì dừng kiểm tra nguyên nhân, không tiếp tục và công bố migration thành công.

`upgrade` áp dụng các revision còn thiếu tới head, không tạo revision mới và không phải seed dữ liệu. `current`/`upgrade` dùng `MIGRATION_DATABASE_URL`; `inspect` dùng runtime `DATABASE_URL`. Đích các lệnh này lấy từ env của service; tùy chọn `--target` chỉ quyết định đích cho **bootstrap**.

Khi viết model nghiệp vụ mới, người phụ trách tạo/review migration theo [quy trình bước 3](SETUP-STEP-3.md#7-quy-trình-migration), test riêng rồi mới áp dụng lên Supabase. Không dùng reset DB chung để sửa lỗi local. Hiện chưa có lệnh seed tài khoản/sản phẩm.

## 9. Tùy chọn: chạy cả bộ bằng container

Sau khi cài công cụ/dependency và chạy `infra dev init`, có thể dùng:

```powershell
# Không đọc env DB dev, DB tắt; bật broker local và 7 ứng dụng container.
.\scripts\dev.ps1 infra dev apps-up --offline

# Dừng riêng các ứng dụng, giữ broker đang chạy.
.\scripts\dev.ps1 infra dev apps-down
```

Mở `http://localhost:3100` như khi chạy native. Bản offline không kiểm chứng Supabase. Không chạy song song với các API/web native cùng port.

Nếu muốn các API container dùng Supabase theo `.env` đã cấu hình:

```powershell
.\scripts\dev.ps1 infra dev apps-up
```

Script sinh env runtime container riêng, giữ `.env` gốc; chuyển hostname broker/gateway/Catalog sang mạng Docker và mount CA nếu có. API container vẫn không tự chạy migration. Cần chuẩn bị revision trước như mục 8. Container không bind source để hot reload; sửa code cần chạy lại `apps-up` để build. Đổi GATEWAY_URL image cần rebuild. Xem [bước 6](SETUP-STEP-6.md) để biết chi tiết container.

## 10. Test, migration thử và reset dữ liệu riêng

Kiểm tra code từ root:

```powershell
.\scripts\dev.ps1 lint all
.\scripts\dev.ps1 typecheck all
.\scripts\dev.ps1 test all
.\scripts\dev.ps1 test backend --integration
```

`--integration` dùng Docker fixture tạm, tự tạo DB/broker và cleanup, không cần `infra test up` trước. Không có cờ này thì các test cần DB/broker Docker được skip. Có thể dùng `web` hoặc tên backend service thay `all`; backend base tests hiện chạy suite chung giữa các service. Chi tiết CI/bàn giao nằm ở [bước 7](SETUP-STEP-7.md).

Muốn tự chạy API/worker trên PostgreSQL test riêng, không cần credential Supabase:

```powershell
.\scripts\dev.ps1 infra test init
.\scripts\dev.ps1 infra test up
.\scripts\dev.ps1 infra test prepare

# Terminal riêng cho từng service cần chạy.
.\scripts\dev.ps1 run catalog-service --test-stack
.\scripts\dev.ps1 run order-service --test-stack
```

`prepare` tự bootstrap 5 schema/role, migrate và chuẩn bị broker trên stack test. `--test-stack` gán URL test vào tiến trình con, không sửa `.env` dev, không cần đổi DATABASE_URL Supabase đang lưu. Không chạy đồng thời hai bản của một service trên cùng port HTTP.

```powershell
# Dừng và giữ dữ liệu test.
.\scripts\dev.ps1 infra test down

# Khi thực sự cần xóa dữ liệu test: reset xong phải prepare lại.
.\scripts\dev.ps1 infra test reset --apply
.\scripts\dev.ps1 infra test prepare
```

Reset chỉ cho project/volume test đã được kiểm tra; không tác động Supabase hoặc broker dev. Database/vhost test tên `commerce_test`, port khác dev. Đây là stack để thử thủ công, tách khỏi container tạm của pytest integration.

## 11. Khi các thành viên chạy service trên nhiều máy

DB chung không làm message của RabbitMQ local đi sang máy khác. Order gửi vào broker A thì Inventory/Payment cần kết nối broker A để nhận các message liên quan. Với luồng local, chạy đủ phần cần thiết trên máy đó; với luồng phân tán, nhóm cấp cùng broker/vhost và thống nhất địa chỉ HTTP.

Sau khi đã điền BROKER_URL chung/BROKER_ENABLED trong env, dùng:

```powershell
.\scripts\dev.ps1 run order-service --broker configured
.\scripts\dev.ps1 worker order-service --broker configured --once
```

Thay service cho Inventory/Payment tương ứng. `--broker configured` dùng URL đã cấu hình thay vì wrapper ghi đè sang local. Gateway `CATALOG_BASE_URL` phải trỏ đúng nơi chạy Catalog; frontend GATEWAY_URL trỏ gateway mà Next.js server truy cập được. Các máy cần thực sự truy cập được các endpoint này; bản Compose local hiện publish loopback nên chưa phải cấu hình chia sẻ LAN.

Dù broker riêng, dữ liệu ghi vào Supabase vẫn thay đổi chung. Dùng dữ liệu thử theo tài khoản/đơn riêng và phối hợp các worker/job đọc dữ liệu chung khi phần đó được viết.

## 12. Lỗi thường gặp

| Hiện tượng | Kiểm tra / xử lý |
| --- | --- |
| Không gọi được `uv`/Node/npm hoặc sai version | Kiểm tra PATH và version mục 2, mở terminal mới sau cài đặt |
| PowerShell chặn `dev.ps1` | Dùng tiền tố `uv run --locked --all-packages python scripts/dev.py` như mục 2 |
| Docker báo không kết nối engine | Mở Docker Desktop, chờ `docker info` chạy được, kiểm tra đang dùng Linux engine |
| Wrapper báo lỗi broker/config khi chạy Order/Inventory/Payment | Đã chạy `infra dev init` và `infra dev up` chưa? Wrapper mặc định dùng broker local |
| Port đã bị chiếm | Dừng bản native/container cũ; không chạy hai bản cùng port. Port broker host có thể chỉnh trong `infra/.local/dev.env` trước khi up |
| `/health/live` 200 nhưng `/health/ready` 503 | Xem `checks`: thiếu/sai URL, role/schema, DB chưa chuẩn bị hoặc broker chưa hoạt động; liveness không thay readiness |
| `SSLCertVerificationError` | Dùng CA tin cậy đúng project, đặt file/path DB_SSL_CA_FILE đúng từ root; giữ verify-full. Xem [TLS bước 3](SETUP-STEP-3.md#9-xử-lý-sslcertverificationerror) |
| `DatabaseConfigurationError` / migration lỗi | Kiểm tra runtime/migrator username đúng service, hậu tố project ref với session pooler, DB postgres, schema và URL không có query params. API không dùng migrator URL; migration không fallback sang runtime URL |
| Sửa `.env` nhưng vẫn dùng giá trị cũ | Restart ứng dụng; biến môi trường đã đặt trong terminal ưu tiên hơn `.env`. APP_ENV=test làm backend bỏ đọc env file dev |
| Frontend báo Catalog unavailable | Catalog và gateway đang chạy chưa? Gateway trỏ đúng CATALOG_BASE_URL chưa? Kiểm tra riêng `/health/live` và `/api/v1/health/catalog` |
| Không thấy bảng sản phẩm/tài khoản sau baseline | Hiện chưa có migration nghiệp vụ hoặc seed; baseline chỉ có version table |
| Máy khác thấy dữ liệu DB nhưng không nhận message | Các máy đang dùng broker riêng; làm theo mục 11 nếu muốn nối service giữa các máy |

Với lỗi chứa credential, chỉ chia sẻ loại lỗi/trạng thái/check đã làm sạch; các file `.env`, CA và `infra/.local/` giữ trên máy theo hướng dẫn nhóm. Bộ mô tả thiết kế và các bản ghi setup theo từng bước vẫn ở [mục lục tài liệu](../README.md).
