# Plan setup base để duyệt trước khi triển khai

Trạng thái: **ĐÃ TRIỂN KHAI BASE BƯỚC 1–4** theo các yêu cầu riêng của bạn. Bước 4 có RabbitMQ client/topology/smoke và worker monitor tách API; chưa có handler nghiệp vụ. Shared broker dev chưa được cấp; kiểm thử bằng broker Docker riêng. Dockerfile ứng dụng chưa build. Bước 5–7 chưa triển khai. Xem [bước 1](../docs/development/SETUP-STEP-1.md), [bước 2](../docs/development/SETUP-STEP-2.md), [bước 3](../docs/development/SETUP-STEP-3.md), [bước 4](../docs/development/SETUP-STEP-4.md).

Tài liệu này dành cho bạn chốt phạm vi công việc mình sẽ thực hiện. Đây không phải kế hoạch phân công thành viên hoặc tài liệu onboarding. Sau khi bạn duyệt, mình triển khai các hạng mục được chọn và báo lại bằng kết quả chạy thực tế.

## 1. Kết quả cần đạt

Repository có bộ khung frontend/backend thống nhất, công cụ và cấu hình chung để bắt đầu viết nghiệp vụ. Chạy được từng ứng dụng, healthcheck, kiểm tra kết nối database và các kiểm tra CI cơ bản.

Bám các quyết định đã có:

- Next.js + TypeScript cho frontend; FastAPI/Python cho gateway và 5 service. Hiện đã thực hiện base bước 1–4; cấu hình dev DB/broker thực tế nằm ngoài Git và được kiểm chứng riêng.
- Dev dùng PostgreSQL trên Supabase chung, 5 schema/role riêng; backend có thể chạy trên máy thành viên.
- Database test riêng; production chưa thiết kế.
- PostgreSQL/SQLAlchemy/Alembic, RabbitMQ/aio-pika là hướng triển khai hiện tại.

## 2. Phạm vi đề nghị duyệt

| Hạng mục | Setup trong đợt này | Chưa làm trong đợt này |
| --- | --- | --- |
| Repository | Cấu trúc apps/packages/infra/scripts, gitignore, cấu hình công cụ | Đổi toàn bộ bộ tài liệu hoặc cơ cấu service |
| Backend | 6 ứng dụng FastAPI chạy độc lập, app factory, settings, healthcheck | API bán hàng, đăng nhập, đơn hàng và payment thật/mô phỏng |
| Database | Session factory, mapping schema, Alembic riêng từng service, kiểm tra quyền/kết nối | Toàn bộ bảng nghiệp vụ và seed sản phẩm/tài khoản |
| Gateway | Một route health đi qua gateway tới service, HTTP client/lifecycle cơ bản | Proxy toàn bộ API, auth, tổng hợp dữ liệu nghiệp vụ |
| RabbitMQ | Cấu hình client, topology khai báo tường minh, smoke test riêng | Consumer nghiệp vụ, workflow, inbox/outbox đầy đủ |
| Frontend | Next.js/TypeScript, App Router, API client, trang kiểm tra kết nối | Thiết kế và code các màn hình mua hàng/quản trị |
| Kiểm tra | Lint/typecheck/test/build cơ bản và CI | Bộ kiểm thử nghiệm thu MVP, load/fault test đầy đủ |
| Chạy dev | Env example và script chạy theo service | Đưa service lên production hoặc tự mua tài nguyên |

## 3. Các bước mình sẽ thực hiện sau khi duyệt

### Bước 1 — Tạo cấu trúc và khóa bộ công cụ

- Kiểm tra công cụ sẵn có trên máy, chọn phiên bản Python/Node tương thích và ghi lại cụ thể; không tự nâng/hạ phiên bản hệ thống đang dùng cho dự án khác.
- Đề xuất dùng **uv** quản lý dependency Python; **npm** cho frontend. Nếu công cụ chưa có, xử lý cài đặt trong phạm vi môi trường dev được duyệt, không giả định đã cài.
- Một uv workspace cho backend và các package Python chung, có lockfile; mỗi ứng dụng có pyproject.toml và dependency riêng. Frontend có package.json/package-lock.json riêng.
- Thống nhất Ruff, mypy, pytest/HTTPX cho Python; ESLint, TypeScript và build cho frontend.
- Tạo gitignore cho .env, virtualenv, node_modules, cache, log và file upload; giữ env example không có secret.

Đầu ra dự kiến:

```text
apps/
  web/
  api-gateway/
  identity-service/
  catalog-service/
  inventory-service/
  order-service/
  payment-service/
packages/
  backend-common/
  contracts/
infra/
  compose.dev.yaml
  compose.test.yaml
  supabase/
scripts/
pyproject.toml
uv.lock
.github/workflows/ci.yml
```

Tên module Python bên trong các ứng dụng phải khác nhau để chạy/test trong cùng workspace không xung đột import. Không dùng cùng module gốc `app` cho cả 6 ứng dụng nếu cùng được cài vào một môi trường.

### Bước 2 — Tạo phần dùng chung và skeleton backend

- Package chung chỉ chứa tiện ích kỹ thuật nhỏ: settings cơ sở, request ID/log JSON, Error envelope và cách đăng ký exception handler. Không chứa business service, ORM model hoặc repository dùng chung.
- Các ứng dụng có app factory, lifespan, API router, settings riêng, tests và Dockerfile. Tạo cấu trúc tối thiểu, không sinh nhiều lớp rỗng không có công dụng.
- Cấu hình CORS theo origin dev, timeout, tên service, port và endpoint upstream qua env.
- Chuẩn hóa lỗi validation 400 theo contract, lỗi không lộ stack/secret; serialize UUID/thời gian và tiền dạng chuỗi đúng quy ước.
- Health liveness không phụ thuộc database; readiness kiểm tra dependency bắt buộc trong chế độ đang bật. Không trả sẵn sàng giả khi DB cần dùng nhưng chưa có cấu hình.
- Gateway có HTTPX client được tạo/đóng theo lifespan và một route health chuyển tiếp cố định để chứng minh đường gọi hoạt động. Không nhận URL upstream tùy ý từ client.

**Xác nhận hoàn thành:** từng ứng dụng start/stop độc lập; health và Error envelope có kiểm tra tự động; không lỗi import/cấu hình lẫn service.

### Bước 3 — Chuẩn bị kết nối Supabase và migration nền

- Tạo session factory SQLAlchemy async/asyncpg cho 5 service, mỗi request/job dùng session riêng, không chia sẻ session giữa coroutine.
- Mapping cố định: commerce_identity, commerce_catalog, commerce_inventory, commerce_orders, commerce_payments. Gateway không có database.
- Alembic config và version table riêng trong schema từng service; autogenerate chỉ xét đối tượng service mình, không đụng schema hệ thống hoặc service khác.
- Chuẩn bị script bootstrap schema, owner/migration/runtime roles và grants/default privileges có phạm vi rõ. Secret truyền lúc chạy, không ghi trong script/repo/log.
- Tách DATABASE_URL và MIGRATION_DATABASE_URL; hướng kết nối dev là direct hoặc session pooler đã kiểm chứng với asyncpg, tùy mạng của máy.
- Migration nền chỉ phục vụ nền tảng/schema/version table. Chưa tạo toàn bộ bảng mô tả trong tài liệu và chưa seed dữ liệu nghiệp vụ.
- Tạo kiểm tra kết nối và quyền: service dùng đúng schema; runtime không có DDL/quyền chéo. Bảng kiểm chứng nếu cần chỉ tạo trong môi trường test hoặc probe schema đã thống nhất, có cleanup; không để bảng giả lẫn bảng sản phẩm.

**Phần có thể chuẩn bị ngay sau duyệt:** code, env example, SQL bootstrap, migration nền và kiểm thử trên PostgreSQL test.

**Phần cần thông tin thực tế:** kết nối Supabase và áp dụng bootstrap cần project dev, thông tin connection, tài khoản có quyền tạo role/schema và cơ chế cấp secret. Chưa có thông tin thì ghi rõ chưa kiểm chứng Supabase; không đánh dấu xong thay cho test local. Không tự tạo tài nguyên trả phí hoặc đổi cấu hình project khác.

### Bước 4 — Base RabbitMQ, tách worker khỏi API

- Tạo wrapper kết nối aio-pika, publish có confirm/routing check, declare exchange/queue theo cấu hình và đóng kết nối đúng cách.
- Cấu hình broker dev chung qua BROKER_URL; broker local dùng cho kiểm tra độc lập nếu cần.
- Chuẩn bị chế độ chạy worker riêng, mặc định **không tự chạy consumer/outbox khi mở API trên mọi máy**. Việc này tránh các bản code local cùng lấy công việc dev.
- Smoke test publish/consume dùng queue riêng có hậu tố ngẫu nhiên và cleanup; không consume queue nghiệp vụ hoặc tạo đơn/thanh toán giả trong DB dev.
- Chưa viết inbox/outbox, Saga hoặc handler command nghiệp vụ trong đợt base. Ghi rõ nền tảng broker chưa đồng nghĩa có giao dịch phân tán hoàn chỉnh.

**Xác nhận hoàn thành:** smoke test chạy trên broker test; mất kết nối không bị nuốt lỗi. Nếu chưa có broker dev thì base vẫn cấu hình được và trạng thái kiểm chứng dev được ghi là pending.

### Bước 5 — Base frontend

- Next.js + TypeScript, đề xuất App Router và Tailwind. Dùng routing/layout của Next.js, không cài React Router. TanStack Query chỉ thêm provider ở Client Components khi cần quản lý truy vấn/polling; không tạo thêm tầng fetch trùng lặp cho trang Server Component đơn giản.
- API client có base URL, timeout, Error envelope, request ID nếu có; chưa làm refresh token tự động khi auth chưa tồn tại.
- Next.js dev chạy cổng 3100 để tránh trùng gateway 3000. Cấu hình rewrite `/api/v1/:path*` tới gateway qua biến server-side GATEWAY_URL; browser dùng đường dẫn tương đối. Kiểm chứng chuyển tiếp cookie/header và không tạo route Next.js bắt trùng `/api/v1`. Chưa bổ sung Server Actions/Route Handlers cho nghiệp vụ backend.
- Một trang trạng thái đơn giản để kiểm tra frontend → gateway → health service, kèm loading/error. Chưa dựng trang mua hàng hoặc dashboard giả.
- Frontend không chứa DB URL/password/service-role key. Chưa tạo TypeScript types cho toàn bộ hợp đồng thủ công; có thể tạo script sinh type từ OpenAPI và kiểm tra output nếu công cụ tương thích.
- Phân biệt Server/Client Components; phần dùng state, browser storage và polling đặt ở Client Components. Dữ liệu đơn/tài khoản không cache chia sẻ giữa người dùng. Env NEXT_PUBLIC_* là dữ liệu có thể công khai; không dùng cho credential hoặc secret.
- Dockerfile frontend chạy Next.js Node server, không phục vụ như thư mục build tĩnh Vite. Kiểm tra next build với cấu hình mẫu không có Supabase secret; Node version khóa theo Next.js thực tế được chọn. Chưa triển khai production.

### Bước 6 — Dev scripts, container và môi trường test

- Script chạy/lint/test theo tên service, hỗ trợ PowerShell trên máy hiện tại; hướng dẫn workdir rõ ràng, không phụ thuộc cwd vô tình.
- Dockerfile cho backend/frontend; compose.dev có broker local tùy chọn và ứng dụng khi cần. **Không tự đưa PostgreSQL local thành database dev mặc định**: dev vẫn trỏ Supabase.
- compose.test có PostgreSQL và RabbitMQ test riêng. Reset test kiểm tra môi trường/đích kết nối đã allowlist; không chỉ tin APP_ENV trong khi URL vẫn trỏ dev.
- Không đưa tất cả worker lên cùng Supabase một cách tự động khi chạy lệnh start mặc định.
- Ghi các lệnh cài, chạy và smoke test đã thực thi vào hướng dẫn phát triển. Tài liệu chưa có endpoint/credential thì dùng placeholder rõ ràng.

### Bước 7 — CI và kiểm tra bàn giao base

- GitHub Actions cài dependency từ lockfile; lint/typecheck/test backend; lint/typecheck/build frontend.
- Test dùng dependency test tạm trong CI, không dùng secret hoặc dữ liệu Supabase dev.
- Test base cần thiết: health/lifecycle, chuẩn hóa lỗi, settings, session/migration scope, quyền schema, smoke RabbitMQ, gateway proxy health. Chưa viết bộ test nghiệp vụ khi code nghiệp vụ chưa có.
- Kiểm tra không commit secret, không in connection string có password, tài liệu và lệnh chạy khớp thực tế.
- Báo cáo phần pass, phần cần credential Supabase/broker dev và giới hạn. CI chỉ được nói đã pass trên GitHub sau khi workflow thực sự chạy; pass local chưa thay thế kết quả đó.

## 4. Những thông tin cần trước bước kết nối dev thật

Không cần gửi secret trong chat hoặc đưa vào repo. Khi triển khai sẽ dùng env/secret trên máy theo cách thống nhất.

| Thông tin | Cần khi nào |
| --- | --- |
| Supabase project dev đã có hay cần tạo | Trước bootstrap schema/role |
| Connection direct/session hoạt động từ máy dev | Trước test kết nối cloud |
| Credential bootstrap và quyền cần thiết | Trước áp dụng SQL schema/role |
| Credential runtime/migration từng service | Trước smoke test quyền thực tế |
| Broker dev đặt ở đâu và credential | Trước chạy message giữa máy thành viên |
| Endpoint HTTP các service khi chạy phân tán | Trước test liên thông nhiều máy; test local ban đầu có thể dùng localhost |

Thiếu thông tin của một hạng mục không ngăn viết skeleton hoặc kiểm thử nền tảng độc lập; hạng mục phụ thuộc được giữ trạng thái pending rõ ràng.

## 5. Điều kiện coi đợt setup base hoàn tất

- [ ] Clone repo và cài dependency bằng lockfile được.
- [ ] Chạy riêng gateway và 5 service; healthcheck đúng, không cần code nghiệp vụ.
- [ ] Frontend gọi qua gateway tới health service được.
- [ ] Bộ lỗi/log/settings có cách dùng chung, không phải mỗi service tự đặt format.
- [ ] 5 service có session/migration riêng, scope schema và quyền đã test trên DB test.
- [ ] RabbitMQ smoke test độc lập pass; worker không tự tranh công việc dev khi chạy API.
- [ ] CI config và kiểm tra local phù hợp pass; trạng thái GitHub CI được ghi theo thực tế.
- [ ] Hướng dẫn chạy/env example đã được thử, không chứa secret.
- [ ] Supabase/broker dev đã được kiểm chứng nếu thông tin truy cập đã có; nếu thiếu, bàn giao base ở mức local/test-ready và liệt kê chính xác phần cloud pending, chưa gọi là dev chung hoàn tất.

## 6. Phần sẽ làm sau base

Auth/JWT/refresh thật, quyền trên tài nguyên, toàn bộ migration nghiệp vụ, Catalog CRUD/ảnh, tồn kho/giữ hàng, checkout/Saga, payment/refund mô phỏng, inbox/outbox, các màn hình nghiệp vụ và test nghiệm thu sẽ được triển khai trong các đợt riêng.

Đợt base chỉ tạo điểm bắt đầu nhất quán. Việc duyệt plan này chưa có nghĩa duyệt production, chạy migration phá dữ liệu, triển khai đầy đủ MVP hoặc tự commit/push. Sau khi bạn duyệt phạm vi, mình mới bắt đầu setup.
