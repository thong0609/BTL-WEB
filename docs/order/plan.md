# Kế hoạch triển khai Order Service — Mạnh

Ngày lập: 07/11/2026. Người phụ trách Order: **Mạnh**.

Cập nhật **15/11/2026**: đã triển khai phần độc lập của Order đến Step 16, gồm backend, giao diện khách/admin và tài liệu bàn giao. Kiểm tra: **437 test backend, 16 test frontend, 9 ca Chromium đạt**, build/restart image Order và web đạt. Auth/Catalog, ghép Inventory/Payment thật và nghiệm thu nhóm còn mở. Supabase ở `0003_action_audit`; xem [kết quả](test-results.md), [runbook](runbook.md), [Step 15](step-15.md) và [Step 16](step-16.md).

Đây là kế hoạch thực hiện; checkbox phản ánh những đầu việc đã chuẩn bị hoặc đã thực hiện và được cập nhật theo kết quả thực tế. Tên file mới là đề xuất tổ chức code; chỉ những file được ghi rõ là hiện có mới đã tồn tại. Không thay thế hợp đồng chung bằng các ví dụ trong plan.

## 1. Mạnh chịu trách nhiệm những gì?

Order là nơi quản lý đơn và điều phối Inventory/Payment. Một đơn chỉ được chuyển sang trạng thái tiếp theo khi có đủ bằng chứng nghiệp vụ, không chỉ vì đã gửi một message.

Mạnh phụ trách:

- Báo giá checkout; kiểm tra lại giá và phí khách đã xác nhận.
- Tạo đơn, mã đơn, snapshot sản phẩm/giá/địa chỉ, lịch sử trạng thái.
- API xem danh sách, chi tiết đơn cho CUSTOMER và ADMIN.
- Xác nhận, hủy, bàn giao, hoàn thành đơn và ghi ngoại lệ giao hàng.
- Workflow bền vững phối hợp giữ hàng, thanh toán, giải phóng, xuất kho, thu COD và hoàn tiền.
- Idempotency HTTP, inbox/outbox của Order, xử lý event lặp/cũ, retry và đối chiếu tiến trình treo.
- SQLAlchemy models, Alembic migration, test, cấu hình và hướng dẫn chạy phần Order.
- Phối hợp Gateway/Identity để xác thực và routing; bàn giao contract cho frontend, cùng nhóm kiểm thử xuyên service.

Inventory sở hữu số tồn/reservation; Payment sở hữu giao dịch tiền; Catalog sở hữu sản phẩm/giá; Identity sở hữu người dùng. Order chỉ truy cập schema `commerce_orders`, không import ORM hoặc join/update schema của các service khác.

Làm backend Order và phối hợp giao diện liên quan là phạm vi của plan. Việc Mạnh trực tiếp xây màn hình checkout/đơn hàng cần nhóm phân công thêm; hiện chưa suy ra Mạnh phải làm toàn bộ frontend từ việc nhận Order.

Ngoài phạm vi MVP: sửa đơn sau đặt, giao từng phần, thanh toán lại trên cùng đơn đã FAILED, hoàn tiền một phần, cổng thanh toán thật, tích hợp hãng vận chuyển, đổi trả sau giao, service Saga riêng.

## 2. Điểm xuất phát đã kiểm tra trong repository

| Hạng mục | Hiện trạng | Cần làm tiếp |
| --- | --- | --- |
| Backend | FastAPI/Python 3.12, SQLAlchemy async, Alembic, PostgreSQL, aio-pika | Dùng stack này; không dùng NestJS/Prisma từ các trao đổi cũ |
| `apps/order-service/src/commerce_order/main.py` | Factory và lifespan DB/broker | Gắn router, client và dependency nghiệp vụ |
| `db.py`, `settings.py` | Base/schema riêng, port 3004, dependency session | Thêm models và cấu hình nghiệp vụ |
| `migrations/versions/0001_base.py` | Migration nền rỗng | Tạo revision mới, không sửa baseline đã chia sẻ |
| `worker.py` | Gọi worker monitor chung, chỉ kiểm tra kết nối | Viết consumer, publisher outbox, recovery thật |
| `packages/backend-common` | Session/DB guard, HTTP/error/JSON, AMQP transport, envelope, topology | Tái sử dụng; chưa có xử lý inbox/outbox nghiệp vụ |
| Gateway | Có diagnostic `/api/v1/health/catalog` | Chưa có routing nghiệp vụ Order hoặc auth đầy đủ |
| Test | Có suite nền tảng chung | Chưa có test nghiệp vụ Order |
| Dev | 5 service + Gateway + frontend + RabbitMQ có cấu hình chạy cùng một laptop bằng Compose; DB dev Supabase | Cấp đúng env; worker nghiệp vụ bổ sung sau khi có handler, test dùng DB/broker riêng |

Không coi baseline/migration, monitor worker hoặc healthcheck chạy được là đã có chức năng đặt hàng. Không kết luận Supabase hoặc broker chung đã sẵn sàng chỉ từ file cấu hình mẫu.

## 3. Tài liệu đọc theo thứ tự

1. [Đặc tả nghiệp vụ](../product/DAC-TA-NGHIEP-VU.md): BR-01–12, UC-ORD-01–04, UC-ADM-02–04.
2. [Thiết kế luồng](../design/THIET-KE-LUONG-XU-LY.md): trạng thái, checkout, hủy, điều kiện phục hồi.
3. [HTTP](../contracts/HTTP-API.md), rồi [OpenAPI](../contracts/openapi.yaml): endpoint, input/output, quyền, mã lỗi.
4. [Messages](../contracts/MESSAGES.md): envelope, 8 command Order phát và 14 loại event Order nhận.
5. [Thiết kế hệ thống/DB](../design/MO-TA-HE-THONG.md): F.12–F.16, F.20–F.23; cấu hình FastAPI và ranh giới dữ liệu.
6. [Setup DB](../development/SETUP-STEP-3.md), [RabbitMQ](../development/SETUP-STEP-4.md), [chạy dev/test](../development/SETUP-STEP-6.md), [Supabase](../infrastructure/PHUONG-AN-SUPABASE.md).
7. [Kiểm thử](../testing/KE-HOACH-KIEM-THU.md), [quy ước phát triển](../development/HUONG-DAN-PHAT-TRIEN.md), [quyết định](../decisions/CAC-QUYET-DINH-THIET-KE.md).

Khi tài liệu khác nhau: nghiệp vụ theo đặc tả, trạng thái theo workflow, cấu trúc public theo OpenAPI, message theo MESSAGES, dữ liệu theo thiết kế DB. Ghi và sửa điểm lệch cùng các bên liên quan trước khi triển khai phần bị ảnh hưởng.

## 4. Những điểm phải thống nhất trước khi tích hợp

Đây là đầu việc cụ thể của bước 1, không phải yêu cầu dừng toàn bộ để chờ nhóm. Trong lúc chờ, Mạnh có thể viết domain, schema, migration và test bằng adapter giả trong môi trường test.

| Điểm cần thống nhất | Hiện còn thiếu/chưa rõ | Đầu ra cần có |
| --- | --- | --- |
| Auth với Identity/Gateway | Chưa có principal người dùng đã xác thực ở Order | Claim/user ID/role, cách xác minh token hoặc danh tính nội bộ đáng tin cậy; chặn header giả từ client |
| Catalog batch | Step 7 có OpenAPI internal dự thảo và caller/test phía Order; Catalog chưa có handler thật | Chủ Catalog review request/response/lỗi/auth và triển khai producer; URL native/Compose đã có |
| Lưu reservation | Step 4 đã thêm `order_workflows.reservation_id` UUID nullable và cập nhật thiết kế DB | Dùng field reservationId trong contract Inventory hiện có, không FK xuyên schema; xác minh payload thật khi tích hợp |
| Recovery | API tra cứu reservation/payment hiện mới được mô tả bằng lời | Response có trạng thái, version, operation liên quan và kết quả đủ để kiểm chứng, kể cả NOT_FOUND/chưa rõ |
| Payment version | `paymentVersion` và kết quả refund phải đủ để phân biệt event cũ với lần retry cùng operation | Chốt quy tắc tăng version và snapshot tra cứu; không bỏ kết quả refund hợp lệ chỉ vì cùng operationId |
| Payment pending | Trước event có thể chưa biết paymentId; public cho phép paymentStatus NULL | Phân biệt workflow đang chờ với trạng thái Payment đã xác nhận; không bịa paymentId/kết quả tiền |
| HTTP hoàn thành | OpenAPI hiện quy định `/complete` trả 202, kể cả nhánh mô phỏng có thể xong cục bộ | Giữ 202 theo contract; nếu nhóm muốn 200 cho nhánh đồng bộ phải đổi OpenAPI và frontend trước |
| Quote lỗi giá | Step 7–8 đã mở rộng ServiceError và trả PRICE_CHANGED trong `details.quote`, có test qua Gateway | Frontend/reviewer shared xác nhận shape và cách yêu cầu khách xác nhận lại; chưa coi đã được nhóm chốt |
| `history`/timeline | HTTP gọi là timeline, OpenAPI dùng field `history` | Public trả `history` đúng OpenAPI; frontend ánh xạ sang timeline hiển thị |
| Broker ngừng | Readiness kiểm tra broker, nhưng outbox cho phép lưu việc lúc broker lỗi | Chốt routing/readiness: request nào vẫn nhận khi DB/Catalog sẵn sàng; không để gateway âm thầm phá cơ chế outbox |
| Phí ship/mã đơn/tìm kiếm | Chưa chốt giá trị phí, định dạng orderNumber, ngữ nghĩa `q` ADMIN | Cấu hình server; mã đơn unique; ghi trường tìm kiếm được hỗ trợ vào HTTP contract |
| Worker trên Compose | Các ứng dụng chạy cùng một laptop; Compose hiện chưa có worker nghiệp vụ | Bổ sung worker vào cùng stack sau khi viết handler; cùng broker RabbitMQ của stack, test dùng DB riêng |

## 5. Cấu trúc code đề xuất

Giữ `main.py`, `db.py`, `settings.py`, `__main__.py`, Dockerfile và toolchain hiện có. Tạo dần các module theo bước; không tạo hàng loạt file rỗng.

```text
apps/order-service/
  src/commerce_order/
    main.py                    # hiện có: đăng ký router/lifespan
    db.py                      # hiện có: Base, SPEC, session_dependency
    settings.py                # hiện có: bổ sung cấu hình không chứa secret
    worker.py                  # hiện có: thay monitor bằng entrypoint nghiệp vụ rõ chế độ
    api/
      dependencies.py          # principal, quyền, Idempotency-Key
      schemas.py               # Pydantic public request/response
      customer.py              # quote/create/list/detail/cancel
      admin.py                 # list/detail/confirm/cancel/dispatch/complete/exceptions
    domain/
      enums.py                 # OrderStatus, workflow, bước kho/tiền
      money.py                 # tính tiền nguyên, giới hạn bigint
      transitions.py           # điều kiện chuyển, allowedActions
    models/
      __init__.py              # import đủ metadata cho migration
      orders.py                # orders, items, history
      workflow.py              # workflow và các ID bền vững
      idempotency.py           # tạo đơn và action requests
      messaging.py             # inbox/outbox riêng Order
    repositories/
      orders.py                # query, lock/update version, history
      idempotency.py            # unique/replay/conflict
      messaging.py             # inbox và claim/lease outbox
    services/
      quote.py                 # Catalog -> báo giá
      checkout.py              # tiếp nhận đơn trong transaction
      actions.py               # confirm/cancel/dispatch/complete/exception
      workflow.py              # áp dụng event và quyết định bước tiếp theo
      recovery.py              # đối chiếu HTTP, retry bước chưa hoàn tất
    clients/
      catalog.py
      inventory.py             # chỉ tra cứu recovery
      payment.py               # chỉ tra cứu recovery
    messaging/
      schemas.py               # payload command/event, dùng MessageEnvelope chung
      commands.py              # xây command/outbox từ dữ liệu tin cậy
      consumer.py              # dispatch event, ACK sau commit
      outbox.py                # publisher có confirms và lease
  migrations/versions/
    <revision_moi>_order_tables.py
tests/order/
  conftest.py
  unit/
  contract/
  integration/
  fixtures/                    # payload cố định, không dữ liệu người thật
docs/order/
  plan.md
  runbook.md                   # viết khi có lệnh/luồng đã chạy thật
  test-results.md              # kết quả thật, expected/actual, môi trường
```

Tên trên là phương án; có thể gộp module nhỏ nếu dễ đọc hơn. Model và workflow Order thuộc `commerce_order`; phần dùng chung chỉ chứa kỹ thuật hoặc contract đã thống nhất, không chứa ORM của Order. Nếu thêm thư viện runtime như HTTPX cho Order, khai báo dependency runtime đúng package và cập nhật lockfile, không chỉ dựa vào dependency dev ở root.

## 6. Danh sách API cần hoàn thành

Đây là route public sau base `/api/v1`. Thống nhất với Gateway việc giữ/bỏ prefix ở upstream, tránh `/api/v1/api/v1`. Khai báo `/orders/quote` trước route động nếu cơ chế routing cần để không hiểu `quote` là UUID.

| Method | Route | Quyền | Thành công theo OpenAPI hiện tại |
| --- | --- | --- | --- |
| POST | `/orders/quote` | CUSTOMER | 200 Quote |
| POST | `/orders` | CUSTOMER | 202 OrderAccepted |
| GET | `/orders` | CUSTOMER, chỉ đơn mình | 200 OrderPage |
| GET | `/orders/{id}` | Chủ đơn | 200 Order |
| POST | `/orders/{id}/cancel` | Chủ đơn, đủ điều kiện | 202 ActionResult |
| GET | `/admin/orders` | ADMIN | 200 OrderPage |
| GET | `/admin/orders/{id}` | ADMIN | 200 Order |
| POST | `/admin/orders/{id}/confirm` | ADMIN | 200 ActionResult |
| POST | `/admin/orders/{id}/cancel` | ADMIN | 202 ActionResult |
| POST | `/admin/orders/{id}/dispatch` | ADMIN | 202 ActionResult |
| POST | `/admin/orders/{id}/complete` | ADMIN | 202 ActionResult |
| POST | `/admin/orders/{id}/exceptions` | ADMIN | 200 ActionResult |

POST tạo đơn và mọi action thay đổi đơn phải có Idempotency-Key. Quote không lưu key và không giữ hàng. Response JSON camelCase, tiền chuỗi số nguyên VND, ID UUID, thời gian UTC ISO 8601; validation 400 theo handler chung. 401 thiếu/không hợp lệ phiên, 403 sai vai trò, 404 đơn không thuộc quyền xem, 409 key/giá/trạng thái xung đột, 503 dependency cần thiết lỗi trước tiếp nhận.

## 7. Các step thực hiện theo thứ tự

### Step 1 — Hiểu phạm vi và chốt điểm nối với các service

**Mục tiêu:** giải thích được một đơn COD/mô phỏng đi qua các service như thế nào và nhận diện việc đang phụ thuộc người khác.

- [x] Đối chiếu tài liệu theo mục 3; ghi lại 8 trạng thái Order và điều kiện chuyển trong [kết quả Step 1](step-1.md). Mạnh đọc mục 1–4 để nắm nghiệp vụ; việc chuẩn bị này không xác nhận thay cho mức độ hiểu của người đọc.
- [x] Chuẩn bị fixture: CUSTOMER_A/B, ADMIN_A, sản phẩm ACTIVE giá 200000, tồn 10 và phí ship 30000 chỉ dùng cho test/demo. Xem [data](fixtures/data.json), [HTTP](fixtures/http.json), [message](fixtures/messages.json); chưa seed/chạy nghiệp vụ.
- [ ] Cùng các chủ service xử lý từng mục trong bảng mục 4; ghi quyết định vào tài liệu nguồn liên quan khi được chốt.
- [x] Đối chiếu command/event mẫu: UUID, money string, correlationId, operationId, schema version=1 theo contract hiện tại; xem mục 6.1 của [Step 1](step-1.md). Có thể dùng ngay để triển khai phần Order độc lập.
- [ ] Cùng Inventory/Payment kiểm tra implementation khớp mẫu, chốt error codes còn thiếu và quy tắc paymentVersion qua refund retry (ORD-OPEN-05).
- [x] Chuẩn bị mapping URL mặc định native/Compose và vai trò hỗ trợ Gateway/auth, worker; xem mục 6.2 của [Step 1](step-1.md).
- [x] Xác định topology chạy: một laptop, các service/worker dùng tên service và broker trong mạng Docker Compose; không cần URL liên laptop. Worker nghiệp vụ được thêm ở Step 9 khi có handler.
- [ ] Xác định người hỗ trợ Gateway/auth và cơ chế danh tính được xác thực (ORD-OPEN-01); phần topology ORD-OPEN-11 đã có cách triển khai trên một laptop.

**Đầu ra:** checklist điểm nối có người phối hợp, fixture mẫu và quyết định cho những khoảng trống cần thiết. Chưa xác nhận điểm nào thì ghi OPEN, không tự coi là đã được nhóm duyệt.

**Hoàn thành khi:** Mạnh mô tả được cả trường hợp thành công, thiếu hàng, payment chậm, hủy sau trả tiền; các thiếu hụt không bị che bằng giả định trong code.

**Cập nhật 07/11/2026:** phần chuẩn bị đã có tại [step-1.md](step-1.md); register ORD-OPEN-01–11 ghi rõ người phối hợp theo vai trò và nội dung cần chốt. Đã đối chiếu quy ước message, mapping HTTP/worker và áp dụng topology một laptop/Compose. Các mục về nội dung API/message/auth còn mở; không cần chọn máy/URL liên laptop để phát triển Order.

### Step 2 — Dựng môi trường Order và chạy kiểm tra nền

**Phụ thuộc:** code base hiện tại; secret dev từ người quản lý môi trường nếu dùng Supabase.

- [x] Đọc setup bước 1–6, cài dependency đúng lockfile; đã chuẩn bị Python 3.12.8, uv 0.12.19 riêng và kiểm tra Docker/Node. Xem [kết quả Step 2](step-2.md).
- [x] Tạo `.env` Order từ template, schema `commerce_orders`, port 3004; đã bật DATABASE_ENABLED và cấu hình runtime/migrator cùng CA `infra/supabase/certs/prod-ca-2021.crt`. Secret và chứng chỉ nằm ngoài Git.
- [x] Nhận cấu hình Supabase cho `order_runtime`/`order_migrator`, xác nhận schema/quyền/CA; Mạnh yêu cầu áp dụng migration dev ngày 15/11/2026. Hai tài khoản kết nối TLS verify-full thành công; readiness với Supabase thật trả database=ready.
- [x] Ghi cách chạy cùng một laptop bằng Compose, cách kiểm tra riêng API Order và tách DB/broker test; không cần địa chỉ liên laptop.
- [x] Kiểm tra HTTP thật `/health/live` và `/health/ready` cả chế độ dependency tắt lẫn DB/broker test bật; test trả database/broker `ready`.
- [x] Chạy lint/typecheck và baseline tests; ghi kết quả thực tế tại [Step 2](step-2.md).
- [x] Khởi tạo/prepare Compose test riêng, schema/role/migration nền và broker smoke đã kiểm chứng; chưa có workflow nghiệp vụ và không dùng Supabase cho test.

**Đầu ra:** môi trường Order chạy được và ghi chú cấu hình không chứa secret.

**Hoàn thành khi:** API liveness hoạt động; môi trường cần DB/broker có readiness phù hợp; kết quả baseline được ghi thật. Worker monitor hiện tại chưa được tính là consumer.

**Cập nhật 07/11/2026:** phần local/test đã có bằng chứng ở [step-2.md](step-2.md). Supabase dev còn chờ cấu hình/quyền từ người quản lý DB; không coi kết quả PostgreSQL test là kết nối Supabase đã thành công.

**Cập nhật 15/11/2026:** phần Supabase dev của Step 2 đã hoàn tất. `scripts/database.py inspect --service order-service` xác nhận runtimeAccess=verified. App Order thật qua ASGI trả `/health/live` 200 và `/health/ready` 200 với `database=ready`, `broker=disabled` trong tiến trình kiểm tra riêng DB. Không suy ra auth, Catalog hoặc broker/workflow đã tích hợp từ kết quả này.

### Step 3 — Viết domain và schema public

- [x] Tạo enum chính xác cho OrderStatus, PaymentMethod, phase/state, stock_step/payment_step; dùng tên contract trong `domain/enums.py`.
- [x] Viết hàm tính tiền nguyên, kiểm tra từng phép nhân/cộng và giới hạn bigint trong `domain/money.py`.
- [x] Viết bảng chuyển trạng thái, `allowed_actions` và `ensure_action_allowed` dùng chung điều kiện trong `domain/transitions.py`; use case thật sẽ gọi khi triển khai bước sau.
- [x] Tạo Pydantic schemas public cùng DTO dòng hàng/history/workflow trong `api/schemas.py`; đối chiếu tên field và field bắt buộc với OpenAPI.
- [x] Validate 1–50 dòng, quantity strict 1–999, trùng productId, UUID, tiền chuỗi, trim/độ dài. SKU trùng kiểm tra trên snapshot sau khi có dữ liệu Catalog.
- [x] Bổ sung InputMoney/OutputMoney của Order, giữ MoneyAmount chung; tiền input là chuỗi, tính nội bộ bằng số nguyên và output JSON là chuỗi.
- [x] Từ chối các field khách tự cấp danh tính/trạng thái/tổng tiền/scenario. Principal thực tế còn triển khai ở Step 6, không thêm auth tạm trong Step 3.
- [x] Thêm 125 test Order về domain/schema/contract/HTTP validation; suite cuối 204 pass, 5 Docker integration skip, lint/typecheck backend pass.

**Đầu ra:** domain và schema độc lập DB, unit test chạy được khi các service khác chưa có nghiệp vụ.

**Hoàn thành khi:** ví dụ 2 chuột × 200000 + ship 30000 ra `"430000"`; các transition sai bị từ chối; JSON đúng tên và kiểu OpenAPI.

**Cập nhật 07/11/2026:** đã triển khai phần độc lập Step 3, xem [step-3.md](step-3.md) để đọc code, bằng chứng test và bảng việc cần đối chiếu với frontend/Catalog/Payment/Identity khi ghép API. Chưa thêm endpoint nghiệp vụ, ORM hoặc consumer và không cần kết nối Supabase để chạy các test này.

### Step 4 — Tạo 8 bảng Order và migration

- [x] Model `orders`: snapshot, tiền, payment mirror/version, mốc thời gian, version và cờ ngoại lệ trong `models/orders.py`.
- [x] Model `order_items`: snapshot SKU/tên/giá/version, quantity, UQ theo sản phẩm/SKU và CHECK tiền dòng.
- [x] Model `order_status_history`: actor/reason/correlation/message ID; PostgreSQL trigger bảo vệ append-only.
- [x] Model `order_workflows`: phase/state, bước kho/tiền, operation ID, retry/version và reservationId UUID nullable không FK xuyên schema.
- [x] Model `idempotency_requests`: unique theo actor/scope/key, hash và response tiếp nhận lưu JSONB.
- [x] Model `order_action_requests`: unique actor/order/action/key, hash và response action.
- [x] Model `processed_messages`: PK consumer/message ID, type/version/hash, processed_at.
- [x] Model `outbox_messages`: message ID, payload/correlation/causation, routing, retry/lease/status và thời điểm để phát lại.
- [x] FK chỉ trong `commerce_orders`, CHECK money/quantity/enum/version và index phân trang có created_at + id; không join/FK sang service khác.
- [x] Import models trong Alembic env, thêm revision `0002_order_tables` sau baseline, migration tường minh không import model sống.
- [x] Upgrade/re-run/autogenerate check/role isolation và downgrade-reupgrade đã pass trên PostgreSQL disposable ngày 07/11; các ca ghi/xóa/reset dữ liệu vẫn chỉ chạy trên DB test riêng.
- [x] Cập nhật test nền để kỳ vọng thêm đúng 8 bảng Order, vẫn giữ kiểm tra schema/version table và quyền service khác.
- [x] Áp dụng migration `0001_base -> 0002_order_tables` trên Supabase dev bằng `order_migrator` ngày 15/11/2026 theo yêu cầu của Mạnh; xác nhận đúng tám bảng mới, model không lệch, owner/constraint/index/trigger/quyền runtime đúng và metadata bốn schema service khác không đổi.

**Đầu ra:** migration mới và models tương ứng. Không cần migration cho schema Inventory/Payment.

**Hoàn thành khi:** upgrade/re-run đúng, constraint bắt được dữ liệu sai, rollback transaction không để dữ liệu dở; không đổi/xóa bảng service khác. Nếu thử downgrade chỉ làm trên DB test và chứng minh không ảnh hưởng schema ngoài Order.

**Cập nhật 07/11/2026:** phần model/migration Step 4 đã triển khai; xem [step-4.md](step-4.md) để đọc cấu trúc, bằng chứng PostgreSQL test và các việc cần phối hợp trong phạm vi Step 4. Chạy migration lên Supabase dev là bước riêng cần người phụ trách DB/cấu hình phù hợp.

**Cập nhật 15/11/2026 — đã chạy trên Supabase dev:**

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Trước khi chạy | Revision `0001_base`, schema Order chỉ có `alembic_version`; TLS verify-full và migrator/owner đúng |
| Áp dụng migration | `upgrade --service order-service --apply` thành công; head trong repo đã xác nhận đúng `0002_order_tables` trước khi chạy |
| Revision và bảng sau chạy | Revision `0002_order_tables`; đủ tám bảng Order và một bảng `alembic_version`, tất cả thuộc `order_owner` |
| Model và database | `check --service order-service`: No new upgrade operations detected |
| Constraint/index | 44 CHECK, 5 FK nội schema, 9 PK và 5 UNIQUE; 22 index; không có constraint chưa validate |
| History | Trigger `order_status_history_append_only` đã được tạo và bật |
| Runtime | Có SELECT/INSERT/UPDATE/DELETE trên tám bảng; không có TRUNCATE hoặc quyền bảng Alembic; inspect xác nhận cách ly schema |
| Các service khác | Snapshot tên/loại/OID relation ở bốn schema service khác trước/sau không đổi |
| Readiness | App Order qua ASGI: live/ready đều 200, database=ready; broker tắt riêng cho lần kiểm tra DB |

Lệnh đã dùng từ root repo với `.env` local, không truyền credential qua tham số:

```powershell
.\.venv\Scripts\python.exe scripts/database.py upgrade --service order-service --apply
.\.venv\Scripts\python.exe scripts/database.py check --service order-service
.\.venv\Scripts\python.exe scripts/database.py inspect --service order-service
```

Snapshot/báo cáo metadata và readiness không chứa credential được lưu local trong `infra/.local/order-supabase/` (Git ignore). Không chạy downgrade, reset hoặc seed đơn thử trên Supabase chung. Đây là bằng chứng migration/cấu hình DB, chưa phải test nghiệp vụ checkout xuyên service.

### Step 5 — Repository, transaction và chống request lặp

- [x] Repository đọc đơn/items/history/list và lock header trước workflow; hàm accept_order ghi snapshot nguyên tử.
- [x] Application service làm chủ session.begin; session mới mỗi thao tác, không gọi Catalog trong transaction/row lock.
- [x] Writer dùng row lock theo thứ tự cố định, recheck guard bên trong lock và tăng version khi action mới được nhận.
- [x] Hash SHA-256 từ DTO đã chuẩn hóa UUID/money/text/defaults, sắp items theo productId; quy tắc cụ thể tại Step 5.
- [x] Lookup/replay trước gọi load_quote; request đã nhận vẫn replay khi Catalog ngừng/giá đổi, cả nhánh concurrent winner khi đọc Catalog lỗi.
- [x] Order/items/workflow/history/key/outbox cùng transaction và savepoint; unique loser rollback toàn bộ rồi đọc winner, không nuốt lỗi DB khác.
- [x] Action key tách actor/order/action; callback cùng transaction, replay trước state guard, payload khác conflict, callback/state lỗi chưa chiếm key.
- [x] Không thêm TTL/job xóa key hoặc trạng thái idempotency chỉ giữ trong RAM.

**Đầu ra:** lớp persistence/idempotency dùng được cho checkout và mọi action.

**Hoàn thành khi:** hai request đồng thời cùng key chỉ có một orderId; payload khác nhận 409; crash trước commit không để order/key/outbox một phần; replay action không tạo thêm tác dụng.

**Cập nhật 07/11/2026:** xem [step-5.md](step-5.md). Persistence và test PostgreSQL đã có. Step 8 đã gắn POST tạo/error adapter vào lớp này; action/workflow cụ thể tiếp tục ở các bước sau.

### Step 6 — Auth dependency, API đọc đơn và điểm nối Gateway

- [x] Thêm principal/TokenVerifier seam và dependency đóng mặc định; mock chỉ qua override trong test, không có nhánh dev token/header tự cấp quyền.
- [ ] Gắn bộ xác minh token Identity thật và kiểm chứng login/token end-to-end; cần contract claim/issuer/audience/key/JWKS hoặc endpoint xác minh từ Identity/Gateway.
- [x] Kiểm tra scope CUSTOMER/ADMIN tại Order; không tin X-User-Id/X-Role từ trình duyệt; thiếu Bearer 401, chưa có verifier 503.
- [x] Có 4 GET customer/admin list/detail; customer query luôn lọc chủ đơn, đơn của người khác 404.
- [x] Pagination/filter/status/total, thứ tự created_at desc + id desc; q hiện tìm mã đơn theo chuỗi con, không phân biệt hoa/thường; có ghi HTTP contract và note nếu muốn mở rộng tìm kiếm.
- [x] Dựng explicit DTO snapshot/payment mirror/history/workflow/allowedActions; no-store, đọc cùng snapshot, không lộ payload/operation IDs nội bộ.
- [x] Routing Gateway 4 GET cố định, forward Bearer/requestId/key theo allowlist; ORDER_BASE_URL native/Compose, lỗi HTTP public được giữ và upstream bất thường được lọc.
- [x] Test PostgreSQL + ASGI Order/Gateway với A/B/admin, spoof/missing headers, query sai, PROCESSING/REJECTED; dùng principal override, chưa dùng token Identity thật.

**Đầu ra:** API tra cứu thật trên PostgreSQL; dùng seed/fixture test để có đơn trước khi checkout hoàn tất.

**Hoàn thành khi:** không lộ đơn người khác; route công khai đến đúng Order; phần auth chưa tích hợp thật phải được ghi rõ, không đánh dấu end-to-end xong.

**Cập nhật 07/11/2026:** xem [step-6.md](step-6.md). Phần query/route/Gateway đã triển khai và kiểm chứng độc lập. Step 6 còn mở ở adapter xác thực thật và test login end-to-end; API runtime không cho qua khi verifier chưa được cấu hình.

### Step 7 — Catalog client và API báo giá

- [x] Catalog client HTTPX async có lifespan, connection limit, timeout, requestId và credential service cấu hình; khai báo runtime dependency/lockfile. Scheme Bearer đang theo dự thảo.
- [x] Contract-test caller `/internal/products/batch` theo OpenAPI internal dự thảo: mapping ID, SKU/name/ACTIVE/price/version; từ chối thiếu/trùng/ngoài ID, sai money/version/currency. Chưa phải producer contract-test với Catalog thật.
- [x] `POST /orders/quote` tại Order/Gateway: kiểm tra items, lấy giá server, tính phí cấu hình và tổng; quotedAt UTC.
- [x] Quote không dùng DB/broker, không giữ hàng, không tạo Order/Payment/message. Không báo availability khi chưa có kết quả ReserveStock.
- [x] Theo dự thảo: missing/inactive trả 404 chung; dependency/config/response lỗi trả 503, không thay bằng giá 0; overflow trả 400.
- [x] PRICE_CHANGED mang quote mới ở `details.quote` qua error handler chung; có test không lộ lỗi/credential nội bộ.
- [ ] Chủ Catalog xác nhận/sửa dự thảo request/response/lỗi/auth và triển khai batch thật; sau đó kiểm thử hai service thật.
- [ ] Nhóm chốt phí ship và điền SHIPPING_FEE_AMOUNT; không lấy 30000 của fixture làm mặc định thật.

**Hoàn thành khi:** báo giá đúng fixture, thay giá Catalog phản ánh ở quote mới; dependency timeout có lỗi rõ; quote không thay đổi kho hoặc tạo message nghiệp vụ.

**Cập nhật 07/11/2026:** xem [step-7.md](step-7.md). Phần Order và kiểm thử độc lập đã có; producer Catalog/credential/phí thật còn OPEN, auth kế thừa điểm mở Step 6.

### Step 8 — API tiếp nhận tạo đơn và outbox đầu tiên

- [x] `POST /orders` tại Order/Gateway: CUSTOMER dependency, validation, Idempotency-Key; replay trước Catalog. Bộ xác minh Identity thật vẫn còn OPEN ở Step 6.
- [x] So sánh expectedUnitPriceAmount/expectedCatalogVersion và expectedShippingFeeAmount; khác trả 409 PRICE_CHANGED với details.quote mới, chưa tạo đơn/key/outbox.
- [x] Snapshot SKU/tên/giá/version/người nhận/note; UUID/orderNumber unique theo Step 5, tổng server tính.
- [x] Một transaction lưu PROCESSING, history, CHECKOUT/WAITING + RESERVE_PENDING, reserve_operation_id, key/response 202 và đúng một ReserveStock outbox.
- [x] 202 chỉ chứng minh đã tiếp nhận; GET đọc trạng thái hiện tại. Không gọi Inventory/Payment HTTP hoặc giả lập kết quả kho/tiền.
- [x] Không giữ transaction DB khi gọi Catalog/chờ broker; xử lý duplicate bằng constraint Step 5. RequestId đã chuẩn hóa thành correlationId lưu bền vững.
- [x] Test PostgreSQL/ASGI: COD/SIMULATED, gửi lặp/đồng thời, đổi giá/version/phí, missing/inactive, Catalog timeout/response sai và rollback sau khi flush các insert.
- [ ] Frontend/reviewer shared xác nhận `details.quote` và UX xác nhận giá mới/key mới; mất response chỉ retry key cũ. Phụ thuộc Catalog/phí thật dùng cùng danh sách Step 7.

**Hoàn thành khi:** với broker chưa phát, API đã tạo một đơn có đầy đủ snapshot/workflow/key/history và đúng một công việc ReserveStock bền vững. Request bị từ chối trước tiếp nhận không để rác DB.

**Cập nhật 07/11/2026:** xem [step-8.md](step-8.md). Tiếp nhận/transaction/replay đã triển khai và test; chưa phải luồng giữ hàng/thanh toán hoàn chỉnh. Publisher/consumer thuộc Step 9.

### Step 9 — Cho Order gửi và nhận việc qua RabbitMQ

**Mục tiêu:** Order gửi yêu cầu cho Inventory/Payment và nhận kết quả trả về.

- [x] **Gửi:** lấy lệnh trong database, gửi RabbitMQ; được xác nhận mới đánh dấu đã gửi.
- [x] **Nhận:** nhận kết quả đúng đơn, lưu database xong mới báo đã xử lý.
- [x] **Chống trùng:** gửi lại giữ nguyên mã; kết quả trùng không xử lý lần hai, kết quả cũ không ghi đè kết quả mới.
- [x] **Xử lý lỗi:** thử lại có giới hạn; thông điệp sai chuyển vào hàng đợi lỗi.
- [x] **Chạy nền:** chia việc giữa các worker; worker tắt thì worker khác tiếp tục. Có lệnh chạy riêng, không tự bật cùng API.
- [x] **Kiểm tra:** dùng RabbitMQ thật để thử gửi/nhận, gửi lặp và tắt/mở worker.

**Xong khi:** không mất lệnh, không xử lý trùng; khởi động lại vẫn tiếp tục được. Chi tiết message và ca test nằm ở mục 8–9 bên dưới.

**Đã triển khai 15/11/2026:** xem [Step 9](step-9.md). Toàn backend **384 test pass**, gồm 79 ca mới. Có worker gửi/nhận, retry/hàng đợi lỗi và handler đủ 14 event; các ca crash được kiểm tra bằng tạo lỗi/ngắt kết nối tại điểm gửi/commit/ACK. Worker có chế độ `outbox`, `consumer`, `all` và batch `--once`; Compose có profile riêng để bật tường minh. Chưa chạy worker trên Supabase/broker dev hoặc tích hợp service đồng đội thật; Step 10–16 vẫn giữ việc riêng cần hoàn thành.

### Step 10 — Xử lý đơn COD: trả tiền khi giao hàng

**Mục tiêu:** giữ được hàng và tạo khoản COD trước khi cho admin xác nhận đơn.

- [x] Inventory giữ hàng thành công → yêu cầu Payment tạo khoản COD đúng tổng tiền đơn.
- [x] Payment xác nhận đã tạo khoản COD → chuyển đơn sang **Chờ xác nhận**.
- [x] Không đủ hàng → từ chối đơn, ghi lý do; không tạo khoản COD.
- [x] Kết quả sai hoặc bị từ chối → ghi lỗi để kiểm tra, không tự báo thành công.
- [x] Test bằng dữ liệu mẫu, PostgreSQL/RabbitMQ thật và producer do test đóng vai.
- [ ] Ghép Inventory/Payment thật khi đồng đội làm xong.

**Xong khi:** đơn đủ hàng đến Chờ xác nhận với đúng tiền COD; đơn thiếu hàng bị từ chối.

**Đã làm phía Order:** [Step 10](step-10.md). Chưa kiểm chứng service đồng đội thật.

### Step 11 — Xử lý thanh toán mô phỏng

**Mục tiêu:** xử lý đúng khi thanh toán thành công, thất bại hoặc trả kết quả chậm.

- [x] Giữ hàng xong mới yêu cầu Payment thanh toán đúng tổng đơn; khách không tự chọn kết quả.
- [x] **Thành công:** chuyển đơn sang Chờ xác nhận.
- [x] **Thất bại rõ ràng:** yêu cầu giải phóng hàng đã giữ; xong mới đánh dấu Đã hủy.
- [x] **Chưa có kết quả:** tiếp tục chờ, không thu tiền lần nữa hoặc tự hủy đơn.
- [x] Test kết quả lặp/đến muộn; kết quả cũ không ghi đè kết quả mới hoặc mở lại đơn đã kết thúc.

**Xong khi:** không thu tiền hai lần; thanh toán thất bại trả lại hàng; thanh toán chậm vẫn chờ đúng.

**Đã làm phía Order:** [Step 11](step-11.md). Payment thật và quy tắc tăng version cần đối chiếu khi ghép.

### Step 12 — Cho phép hủy đơn và hoàn tiền

**Mục tiêu:** hủy xong thì hết giữ hàng và xử lý xong tiền.

- [x] Khách chỉ hủy đơn mình đang Chờ xác nhận; admin được hủy thêm lúc Chuẩn bị hàng. Bắt buộc có lý do.
- [x] Chặn hủy khi đang xử lý thanh toán, bàn giao hoặc hoàn thành đơn.
- [x] Khi nhận hủy: đánh dấu **Đang hủy**, yêu cầu Inventory giải phóng hàng.
- [x] Với COD: hủy khoản chờ thu. Với đơn đã thanh toán: hoàn toàn bộ tiền, gồm phí ship.
- [x] Chỉ đánh dấu **Đã hủy** khi cả hàng và tiền đều xử lý xong.
- [x] Test hủy lặp và lỗi hoàn tiền: chỉ thử lại phần chưa xong, không giải phóng/hoàn tiền hai lần.

**Xong khi:** đơn đã hủy không còn giữ hàng hoặc khoản tiền chưa giải quyết.

**Đã làm phía Order:** [Step 12](step-12.md); có API customer/admin và Gateway, replay/rollback/cạnh tranh đã kiểm tra. Migration `0003_action_audit` lưu input action để giữ lý do audit.

### Step 13 — Cho admin xác nhận, giao và hoàn thành đơn

**Mục tiêu:** admin xử lý đơn từ Chờ xác nhận đến Hoàn thành.

- [x] **Xác nhận:** Chờ xác nhận → Chuẩn bị hàng; không giữ hàng thêm lần nữa.
- [x] **Bàn giao:** yêu cầu Inventory xuất hàng; chỉ chuyển sang Đang giao khi Inventory xác nhận. Đang bàn giao thì chặn hủy.
- [x] **Hoàn thành đơn trả trước:** chỉ cho phép khi đã giao hàng và thanh toán thành công.
- [x] **Hoàn thành COD:** admin xác nhận đã giao/thu tiền; chờ Payment xác nhận ghi nhận thu tiền rồi mới hoàn thành.
- [x] **Giao thất bại:** lưu lý do và đánh dấu cần xử lý, giữ Đang giao; không tự hoàn tiền/nhập lại tồn.
- [x] Lưu lịch sử; test bấm lặp hoặc hai người cùng thao tác để tránh xuất hàng/thu tiền hai lần.

**Xong khi:** không có đơn Hoàn thành khi chưa giao hàng hoặc chưa xác nhận thu đủ tiền.

**Đã làm phía Order:** [Step 13](step-13.md). Có đủ 12 endpoint Order; Identity thật và UI tiếp tục ở Step 6/15.

### Step 14 — Tự xử lý đơn bị treo khi có lỗi

**Mục tiêu:** mất mạng, mất kết quả hoặc worker tắt không làm đơn bị bỏ quên.

- [x] Định kỳ tìm đơn chờ quá lâu hoặc việc chưa xử lý xong.
- [x] Có client tra cứu Inventory/Payment theo hợp đồng dự thảo; kiểm tra đơn, công việc, số tiền và message gốc bằng test phản hồi mẫu.
- [x] Tiếp tục phần còn thiếu bằng mã công việc cũ; không tạo đơn hoặc khoản thu/hoàn mới.
- [x] Kết quả chưa rõ thì tiếp tục chờ hoặc cảnh báo admin; không tự coi timeout là thất bại/hủy đơn.
- [x] Test mất mạng/message, phục hồi việc hết hạn và chặn snapshot cũ; log không chứa mật khẩu/token/địa chỉ đầy đủ.
- [ ] Inventory/Payment xác nhận và triển khai API recovery dự thảo, cấp token riêng và kiểm thử ghép thật; đối chiếu version/refund retry.

**Xong khi:** đơn tiếp tục được sau lỗi, hoặc hiển thị rõ cần admin xử lý; không thu/hoàn/xuất hàng lặp.

**Đã làm phía Order:** [Step 14](step-14.md). Có mode recovery/once, không giữ khóa DB khi gọi HTTP, kiểm tra phiên bản trước khi áp dụng; mặc định chưa tự bật khi producer chưa có. Hợp đồng response/auth vẫn là [dự thảo](../contracts/order-recovery.openapi.yaml).

### Step 15 — Nối giao diện với các service thật

**Mục tiêu:** khách và admin sử dụng được Order ngay trên website.

- [x] Soạn ví dụ API và hướng dẫn ghép frontend: báo giá, tạo/xem/hủy đơn, thao tác admin và lỗi giá thay đổi; có trong frontend-handoff/fixtures để đồng đội sử dụng.
- [x] Triển khai màn hình checkout, danh sách/chi tiết cho khách và admin; đã đọc `apps/web/AGENTS.md` và guide Next cục bộ.
- [x] Hiển thị trạng thái đang xử lý, polling và nút theo allowedActions; backend vẫn kiểm tra quyền.
- [x] Mất mạng/reload gửi lại cùng mã và nội dung; khách xác nhận giá mới dùng mã mới. HTTP 202 chỉ là đã tiếp nhận đơn.
- [x] Backend kiểm tra khách chỉ xem được đơn mình; frontend kiểm tra response, giữ nguyên giá/tên đã lưu; đã test độc lập.
- [ ] Ghép đăng nhập Identity/routing auth Gateway/verifier, trang sản phẩm/giỏ hàng Catalog và phí ship thật theo hướng dẫn bàn giao.
- [ ] Chạy toàn bộ luồng trên cùng laptop/Compose với Identity, Catalog, Inventory, Payment thật và cùng RabbitMQ.

**Xong khi:** đặt/xem/hủy và xử lý đơn qua giao diện được, không cần sửa database tay hoặc giả kết quả.

**Đã làm phía Order:** [Step 15](step-15.md), [bàn giao frontend](frontend-handoff.md). Giao diện đã có và test Chromium đạt; service của đồng đội chưa có nên chưa nghiệm thu mua hàng thật.

### Step 16 — Kiểm tra lần cuối và bàn giao

**Mục tiêu:** người khác lấy code về có thể chạy và kiểm tra Order theo tài liệu.

- [x] Chạy các ca thuộc phía Order trong mục 9 bằng PostgreSQL/RabbitMQ test riêng; kiểm tra state/inbox/outbox và số lệnh; backup/restore Order rồi tiếp tục đơn pending.
- [x] Lint/typecheck/backend test/frontend test/Chromium đã chạy; kết quả và cảnh báo ghi trong test-results.
- [x] Tạo database từ migration, build hai image Order/web và thử restart bằng container riêng. API không tự chạy migration/worker; image smoke tắt DB/broker, nghiệp vụ được kiểm tra riêng.
- [x] Đối chiếu 12 API public/request/response với OpenAPI; test contract 8 command/14 event và cấu trúc bảng tiếp tục đạt.
- [x] Viết `docs/order/runbook.md`: cấu hình, lệnh chạy, migration và cách xử lý lỗi.
- [x] Viết `docs/order/test-results.md`: pass/fail, cảnh báo và phần chưa kiểm tra; không ghi secret.
- [x] Có sáu kịch bản demo và harness test đạt: COD, trả trước thành công, thiếu hàng, thanh toán lỗi, hủy/hoàn tiền, worker lỗi/phục hồi.
- [ ] Chạy sáu demo qua UI/service thật; kiểm tra tranh tồn và số giao dịch trong Inventory/Payment, restore đồng bộ các service và nhóm review nghiệm thu.
- [ ] Một đồng đội tự chạy lại theo runbook và xác nhận kết quả.

**Xong khi:** đạt checklist mục 12 và một người khác chạy lại được theo tài liệu.

**Đã làm phía Order:** [Step 16](step-16.md), [test-results](test-results.md), [runbook](runbook.md), [demo](demo.md). Các ô chờ ghép nhóm được giữ mở.

## 8. Bảng điều phối event phải bao phủ

Mọi handler kiểm tra inbox, order/operation/phase và phiên bản trước khi áp dụng; dưới đây mô tả kết quả nghiệp vụ, không bỏ qua các kiểm tra đó.

| Event nhận | Việc Order làm |
| --- | --- |
| StockReserved | Lưu reservation, tạo InitializeCodPayment/ProcessPayment đúng phương thức |
| StockReservationFailed | REJECTED, giữ lý do, không khởi tạo payment |
| StockReleased | Hoàn tất nhánh kho của hủy; kiểm tra nhánh tiền trước CANCELLED |
| StockReleaseFailed | Đối chiếu/cảnh báo; không tuyên bố đã hủy xong |
| StockCommitted | SHIPPING sau khi khớp lệnh dispatch |
| StockCommitFailed | Chưa SHIPPING, giữ dấu vết và đối chiếu |
| PaymentInitialized | COD ready, AWAITING_CONFIRMATION khi đủ điều kiện kho |
| PaymentSucceeded | Lưu SUCCEEDED/version, tiếp nhận đơn mô phỏng khi khớp checkout |
| PaymentFailed | Thất bại xác định, giải phóng hàng rồi kết thúc hủy |
| CodCollected | Mirror SUCCEEDED, COMPLETED khi khớp completion và đã giao |
| CodPaymentCancelled | Hoàn tất nhánh tiền COD của hủy |
| PaymentRefunded | Hoàn tất nhánh hoàn tiền, chờ kho nếu chưa xong |
| PaymentRefundFailed | REFUND_PENDING, ghi retry/cờ; chưa CANCELLED |
| PaymentCommandRejected | Kiểm tra rejectedType/code, đối chiếu trạng thái; không suy ra thành công/thất bại thanh toán tùy ý |

8 command Order phát: ReserveStock, ReleaseStock, CommitStock, InitializeCodPayment, ProcessPayment, RecordCodCollection, CancelCodPayment, RefundPayment. Mapping exchange/routing key giữ theo MESSAGES và `messaging_topology.py`; không tạo queue/saga service mới vì tiện triển khai.

## 9. Ma trận kiểm thử trọng tâm của Mạnh

| Nhóm | Case phải chạy | Bằng chứng cần kiểm tra | AT liên quan |
| --- | --- | --- | --- |
| Tiền/snapshot | 2 × 200000 + 30000; Catalog đổi tên/giá sau đặt | Total 430000, JSON string, đơn cũ không thay đổi | 05, 11, 23 |
| Giá/validation | Giá/phí/version đổi, bool quantity, dòng trùng, extra field | 400/409 đúng, không order/key/outbox rác | 18, 23 |
| Quyền | A đọc/hủy đơn B, CUSTOMER gọi admin, header giả | 404/403/401, list đúng chủ và không lộ PII | 10 |
| Replay tạo đơn | Cùng key/payload tuần tự và song song; Catalog lỗi sau lần đầu | Một order/key, replay response tiếp nhận cũ, GET trạng thái mới | 18, 19 |
| Replay action | Mỗi action lặp/đổi payload/cạnh tranh | Không thêm release/refund/commit/collection; 409 phù hợp | 07–09, 13, 14, 21 |
| Kho | 20 đơn mua tồn 1; giỏ 2 dòng một hết | Inventory chỉ giữ một đơn; Order thiếu hàng không gọi Payment | 16, 17 |
| COD | Đặt -> confirm -> dispatch -> complete | Payment initialized trước tiếp nhận; commit trước SHIPPING; collect trước COMPLETED | 05, 13, 14 |
| Mô phỏng | Success/failure/delay | Fail release rồi CANCELLED; delay không tự release/thu lại | 06, 20 |
| Hủy | COD, đã trả, refund lỗi rồi retry | Hai nhánh độc lập, hoàn đủ ship, một refund/payment | 07–09 |
| Giao lỗi | Ghi exception khi SHIPPING | Cờ cần xử lý, không tự complete/refund/nhập tồn | 15 |
| Inbox | Cùng messageId; khác messageId cùng kết quả operation; payload xung đột | Không lặp transition/history/outbox, xung đột được phát hiện | 22, 24 |
| Event version | Cũ/muộn/gap; refund fail rồi success cùng operation | Không đảo trạng thái hoặc bỏ mất kết quả mới hợp lệ | 22 |
| Publish crash | DB commit trước publish; publish trước đánh PUBLISHED | Outbox còn việc hoặc phát trùng cùng messageId, nghiệp vụ không lặp | 19, 25 |
| Consume crash | Transaction commit trước ACK; DB lỗi trước commit | Redelivery an toàn; rollback inbox cùng nghiệp vụ | 19, 25 |
| Recovery | Payment đã commit nhưng event mất; worker chết sau claim | Đối chiếu đúng, lease takeover, chỉ retry bước còn thiếu | 20, 25 |
| Poison message | Sai schema/unknown version, lỗi dai dẳng | DLQ/backoff/cảnh báo, không vòng lặp requeue nóng | 24 |
| Restore | Phối hợp restore bản sao test rồi tiếp tục pending | Kiểm chứng Order/workflow/outbox/inbox và đối chiếu liên service | 26 |

Unit/contract có adapter giả để phát triển độc lập; integration cần PostgreSQL/RabbitMQ thật. Case tranh tồn, thu/hoàn/xuất cần chạy cùng chủ Inventory/Payment và kiểm tra dữ liệu do họ sở hữu bằng fixture/endpoint hoặc harness kiểm thử đã thống nhất, không cấp quyền runtime Order đọc chéo schema.

## 10. Lệnh nền tảng đã có để sử dụng khi thực hiện

Chạy các lệnh dưới từ root repo sau khi cấu hình môi trường. Bảng lệnh không phải bằng chứng pass; kết quả thực tế được ghi ở từng tài liệu step. Worker nghiệp vụ đã có ở [Step 9](step-9.md) và [Step 14](step-14.md); mặc định vẫn là monitor, muốn xử lý đơn phải chọn mode phù hợp.

Kết quả thực hiện sau khi lập plan nằm ở [Step 2](step-2.md). Trên máy Mạnh, dùng `.venv/Scripts/python.exe scripts/dev.py` theo hướng dẫn đó vì uv mặc định toàn máy vẫn là phiên bản cũ; toolchain đúng đã được cài riêng trong repo.

```powershell
# Kiểm tra code nền; test order-service hiện vẫn chạy toàn bộ backend suite.
.\scripts\dev.ps1 lint order-service
.\scripts\dev.ps1 typecheck order-service
.\scripts\dev.ps1 test order-service

# PostgreSQL/RabbitMQ disposable do pytest tạo, không dùng DB dev.
.\scripts\dev.ps1 test backend --integration

# Chạy broker local và API (điền env Order đúng trước nếu bật DB).
.\scripts\dev.ps1 infra dev init
.\scripts\dev.ps1 infra dev up
.\scripts\dev.ps1 run order-service

# Kiểm tra monitor hiện có; không xử lý đơn hàng.
.\scripts\dev.ps1 broker topology order-service --apply
.\scripts\dev.ps1 worker order-service --once

# Test stack riêng để chạy thử thủ công; không cần cho suite integration trên.
.\scripts\dev.ps1 infra test init
.\scripts\dev.ps1 infra test up
.\scripts\dev.ps1 infra test prepare
.\scripts\dev.ps1 run order-service --test-stack

# Kiểm tra toàn backend khi đổi shared/gateway và build image sau cùng.
.\scripts\dev.ps1 lint backend
.\scripts\dev.ps1 typecheck backend
.\scripts\dev.ps1 test backend
.\scripts\dev.ps1 build order-service
```

`run order-service` chiếm terminal; mở terminal riêng cho kiểm tra/worker. Chạy API dev và test cùng port 3004 sẽ xung đột. Với broker đã cấu hình chung dùng tùy chọn `--broker configured` theo setup bước 6, và phải thống nhất phạm vi dữ liệu/worker trước. `infra test prepare` áp dụng migration đã có tại thời điểm chạy; migration mới cần kiểm tra trên test trước khi người phụ trách áp dụng vào Supabase dev theo quy trình của nhóm. Không reset DB dev để thử plan.

## 11. Chia mốc công việc/PR để dễ theo dõi

Không gắn ngày hoàn thành vì chưa có số giờ làm/tuần và tiến độ service phụ thuộc. Làm theo đầu ra; mỗi PR có test của chính phần vừa thêm, không dồn test tới cuối.

| Mốc | Step | PR gợi ý | Kết quả demo được |
| --- | --- | --- | --- |
| A — Nền tảng | 1–5 | `docs/order-contract-gaps`, `feat/order-domain-schema`, `feat/order-persistence` | Tính tiền, transition, migration, atomic write/replay có test |
| B — API cơ bản | 6–8 | `feat/order-queries-auth`, `feat/order-quote`, `feat/order-create` | Quote, tạo PROCESSING và xem đơn đúng quyền |
| C — Luồng COD | 9–10 | `feat/order-outbox-consumer`, `feat/order-cod-workflow` | Giữ hàng + COD thật -> chờ xác nhận |
| D — Thanh toán/hủy | 11–12 | `feat/order-simulated-checkout`, `feat/order-cancel-refund` | Mô phỏng success/fail/delay, hủy/hoàn đúng |
| E — Vòng đời ADMIN | 13 | `feat/order-admin-lifecycle` | Confirm -> dispatch -> complete, exception |
| F — Ổn định/bàn giao | 14–16 | `feat/order-recovery`, `test/order-fault-integration`, `docs/order-runbook` | Restart/retry an toàn, UI tích hợp và báo cáo |

PR thay message cần producer/consumer review; migration cần người phụ trách DB phối hợp; shared/auth/gateway/worker script có test hồi quy liên quan. Có thể tách PR lớn hơn nữa, miễn mỗi PR mô tả rõ phần chưa hoạt động và không công bố luồng tích hợp đã xong khi mới dùng fixture.

Nếu các service khác chậm: hoàn thành A/B, viết contract fixture/adapter test cho C–E, giữ integration status NOT RUN và ghép service thật khi sẵn sàng. Không sửa Inventory/Payment DB hoặc làm mock thành đường chạy mặc định để vượt phụ thuộc.

## 12. Checklist hoàn thành Order Service

- [x] Đủ 12 endpoint public và test quyền/input/output/pagination/idempotency phía Order/Gateway; verifier test chỉ trong test, Identity thật vẫn mở ở Step 6.
- [x] Snapshot và tiền được kiểm tra; không tin tổng tiền/trạng thái/danh tính từ client.
- [x] 8 bảng nghiệp vụ/kỹ thuật Order có migration, constraints, index và isolation đúng; đã kiểm chứng trên PostgreSQL test và Supabase dev. Sau `0002_order_tables`, đã áp dụng/đối chiếu `0003_action_audit` ngày 15/11/2026 để lưu input action.
- [x] Phía Order có schema và contract test cho 8 command/14 event, queue/routing đã kiểm tra với RabbitMQ riêng ở Step 9; tích hợp producer thật vẫn nằm ở các bước sau.
- [ ] COD và mô phỏng chạy xuyên các service thật; thiếu hàng không tạo payment.
- [x] Phía Order: hủy chỉ xong sau đủ nhánh; dispatch/complete chờ bằng chứng kho/tiền, đã test với PostgreSQL/RabbitMQ riêng.
- [x] Request/message lặp hoặc cạnh tranh đã được kiểm tra không làm nghiệp vụ lần hai; cần tiếp tục đối chiếu producer thật khi tích hợp.
- [x] Các điểm crash phía Order của outbox/inbox, lease, retry/DLQ và recovery có test đạt; restore liên service thật vẫn chờ tích hợp.
- [x] API không tự chạy migration/consumer; worker có entrypoint riêng và đã chạy trên DB/broker test, image startup/restart đã kiểm tra riêng.
- [x] Lint/typecheck/test/build backend và frontend có kết quả thật; cảnh báo/giới hạn đã ghi.
- [x] Có runbook/test-results và lệnh đã kiểm tra; OpenAPI/message/DB Order được đối chiếu bằng test.
- [ ] Mạnh và các chủ service liên quan review bằng chứng, hoàn tất demo qua UI.

**Việc tiếp theo:** đồng đội ghép auth/Catalog/giỏ hàng, chốt API recovery với Inventory/Payment, rồi chạy demo UI đủ 5 service và review bàn giao. Phần code/test/tài liệu độc lập của Step 15–16 đã có; chỉ tick nghiệm thu tích hợp sau khi có kết quả thật.
