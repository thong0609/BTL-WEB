# Setup bước 4 — RabbitMQ transport và worker base

## 1. Phạm vi

Đã bổ sung client aio-pika, envelope kỹ thuật, topology tường minh, smoke test và entrypoint worker riêng cho Inventory, Order, Payment. API có thể kiểm tra broker qua readiness nhưng **không tự khai báo topology, không consume message và không khởi động worker**.

Chưa có handler ReserveStock/ProcessPayment hay nghiệp vụ khác, chưa có inbox/outbox/Saga hoặc retry nghiệp vụ. Worker hiện là connectivity monitor với consumers=0, không phải worker xử lý đơn đã hoàn thiện. Gateway, Identity và Catalog chưa dùng RabbitMQ trong MVP hiện tại.

Broker dev chung chưa được cấp trong đợt setup này. Chỉ tạo broker test riêng trên Docker Desktop để kiểm chứng, không provision dịch vụ cloud hoặc dùng queue dev của nhóm.

## 2. Code và cấu hình

- `commerce_backend_common.messaging`: URL/TLS, RobustConnection, channel có publisher confirms và on-return error; publish persistent + mandatory, giới hạn kích thước và deadline.
- `messaging_topology`: commands/events/dead-letter exchanges, binding và queue theo hợp đồng.
- `messaging_lifespan`: client API, đóng tài nguyên theo lifespan; đăng ký readiness khi bật.
- `messaging_smoke`: probe trên exchange/queue UUID riêng, queue exclusive, manual ACK và cleanup.
- `messaging_worker`: monitor kết nối tách API; chưa đăng ký consumer.
- `apps/{inventory,order,payment}-service/src/commerce_*/worker.py`: entrypoint mỗi service.
- `scripts/broker.py`: check, topology hoặc smoke tường minh.

Các service dùng shared package extra `[database,messaging]`. Phần messaging không import ORM model hoặc mở DB connection. Các dependency trực tiếp aio-pika/pamqp/yarl đã khóa trong uv.lock.

Trong `.env` của một trong ba service, cấu hình theo broker dev thực tế:

```dotenv
BROKER_ENABLED=true
BROKER_URL=amqps://SERVICE_USER:URL_ENCODED_PASSWORD@BROKER_HOST:5671/DEV_VHOST
BROKER_CONNECT_TIMEOUT_SECONDS=5
BROKER_PUBLISH_TIMEOUT_SECONDS=5
BROKER_RECONNECT_INTERVAL_SECONDS=2
BROKER_PREFETCH_COUNT=10
BROKER_HEARTBEAT_SECONDS=30
BROKER_MAX_MESSAGE_BYTES=262144
# Chỉ khi broker cần CA riêng; đường dẫn tính từ gốc repo.
# BROKER_SSL_CA_FILE=infra/rabbitmq/certs/dev-ca.crt
```

Đây là template, chưa phải credential hoạt động. AMQP local có dạng `amqp://USER:PASSWORD@127.0.0.1:5672/VHOST`. URL phải có user/password, không chứa query/fragment; password/vhost có ký tự đặc biệt cần encode phù hợp. AMQPS dùng certificate/hostname verification; thêm CA riêng nếu cần, không có tùy chọn tắt xác minh TLS.

Không copy DATABASE_URL của Supabase làm BROKER_URL. Đây là hai dịch vụ khác nhau. BROKER_ENABLED mặc định false; không sửa .env thật của nhóm trong bước này.

## 3. Kết nối, publish và giới hạn đảm bảo

API không mở broker ở import/startup: khi bật, readiness hoặc lần publish đầu mở client. Liveness không phụ thuộc broker. Readiness kiểm tra kết nối/channel, không chứng minh topology đã khai báo, consumer đang chạy hoặc message đã được xử lý. Mất broker trả unavailable; sai cấu hình trả invalid_configuration; tắt trả disabled. Pool/heartbeat/prefetch được kiểm soát qua settings.

RobustConnection phục hồi kết nối và những declaration được đăng ký robust khi broker trở lại. Nó **không tự phát lại publication bị lỗi**. Publish phải nhận Basic.Ack; mandatory + on_return_raises giúp nhận lỗi khi message không route được vào queue. Timeout/lost confirmation trả lỗi có kết quả chưa rõ, không được kết luận message chưa tới broker rồi tạo một thao tác mới.

Khi triển khai outbox sau này, retry giữ messageId và operationId, receiver có inbox/idempotency. Step 4 không bảo đảm exactly-once hoặc giao dịch DB + broker nguyên tử.

MessageEnvelope dùng messageId, type, version=1, correlationId, causationId nullable, occurredAt UTC và payload JSON object. Metadata bắt buộc khi parse; không tự tạo messageId cho input bị thiếu. Thêm field envelope tùy chọn được bỏ qua để tương thích; version sai/bool/string và timestamp không timezone bị từ chối. Payload nghiệp vụ từng loại vẫn phải được validate khi viết handler; envelope hợp lệ chưa có nghĩa đơn/payment hợp lệ.

Client library reconnect logs bị hạn chế để tránh lộ URL; boundary trả lỗi kỹ thuật đã làm sạch. Worker log JSON chỉ ghi service, trạng thái, mode=connectivity_only, consumers=0. Không log password, payload hoặc URL connection.

## 4. Topology được khai báo khi có lệnh --apply

| Exchange | Loại | Queue / binding |
| --- | --- | --- |
| commerce.commands | direct, durable | inventory.commands: inventory.reserve/release/commit |
| commerce.commands | direct, durable | payment.commands: payment.initialize-cod/process/collect-cod/cancel-cod/refund |
| commerce.events | topic, durable | order.events: các event key cụ thể trong MESSAGES.md |
| commerce.dead | direct, durable | inventory.commands.dead, payment.commands.dead, order.events.dead |

Ký hiệu `/` trong bảng rút gọn các key riêng. Mỗi queue chính có DLX/routing key tới dead queue tương ứng. Không có retry queue/TTL/requeue vô hạn trong step 4. Handler sau này phải ACK sau commit, reject/DLQ khi phù hợp; hiện chỉ smoke/test thao tác ACK/NACK trên dữ liệu test.

Declare topology gọi riêng từng service; rerun cùng cấu hình không phá dữ liệu. Nếu queue cũ có arguments khác, broker sẽ báo lỗi: không tự xóa queue để làm lệnh pass. Cần quyền configure/write/read phù hợp trên vhost dev; credentials dev được quản lý riêng. Xem [hợp đồng message](../contracts/MESSAGES.md).

## 5. Lệnh từ gốc repo

```powershell
# Chỉ kiểm tra kết nối, không khai báo queue hoặc consume.
uv run --locked --all-packages python scripts/broker.py check --service order-service

# Có thay đổi topology, chỉ chạy trên broker/vhost dev đã thống nhất.
uv run --locked --all-packages python scripts/broker.py topology --service order-service --apply
uv run --locked --all-packages python scripts/broker.py topology --service inventory-service --apply
uv run --locked --all-packages python scripts/broker.py topology --service payment-service --apply

# Tạo exchange/queue commerce.smoke.<uuid> riêng rồi cleanup.
uv run --locked --all-packages python scripts/broker.py smoke --service order-service --apply

# Worker base hiện chỉ monitor; --once kiểm tra một lần rồi thoát.
uv run --locked --all-packages python -m commerce_order.worker --run --once
uv run --locked --all-packages python -m commerce_inventory.worker --run
uv run --locked --all-packages python -m commerce_payment.worker --run
```

Chạy worker không có --run chỉ hiện help, không nạp connection. API `python -m commerce_order` không khởi động worker. Chưa cần cho mọi member chạy monitor/consumer cùng queue; giữ phân công worker khi có handler ở giai đoạn sau.

Các lệnh cần broker được cấu hình thật; đợt này kiểm chứng wrapper/topology/worker trên broker test, chưa kiểm tra credential dev. Smoke không tạo đơn, payment hoặc ghi Supabase. Không dùng smoke làm test dữ liệu nghiệp vụ.

## 6. Kiểm thử

```powershell
uv run --locked --all-packages pytest -q --run-rabbitmq tests/test_messaging.py -m integration
uv run --locked --all-packages pytest -q --run-postgres --run-rabbitmq
uv run --locked --all-packages ruff check apps packages scripts tests
uv run --locked --all-packages mypy
```

--run-rabbitmq tạo container RabbitMQ 4 alpine, vhost commerce_test, password ngẫu nhiên và port chỉ bind loopback. Host port được chọn một lần để ổn định khi test restart. Fixture stop/remove container của chính nó khi xong; không dừng broker khác của người dùng.

Các kiểm tra đã có: envelope/URL/size/version, thất bại kết nối không báo success giả, API không spawn worker, CLI --apply, routing mọi binding, persistent publication, mandatory unroutable, manual ACK và redelivery sau đóng channel, dead-letter, smoke resource cleanup, durable message và robust reconnect sau restart, lifespan đóng kết nối, worker monitor không consume.

Kết quả cuối: **72 test pass** với PostgreSQL và RabbitMQ Docker riêng; Ruff lint/format, mypy và uv.lock hợp lệ. Các container test đã được dọn. Deprecation warning TestClient/HTTPX kế thừa từ bước 2 vẫn còn, không che bằng filter. Test RabbitMQ riêng cũng có 3 ca integration pass.

## 7. Sửa cách ly test phát hiện trong bước này

Một test cũ kiểm tra migration không fallback runtime đã dùng subprocess mà chưa vô hiệu hóa service-local .env. Khi member đã điền .env dev, test đã chạy lại upgrade baseline Catalog trên Supabase. Baseline chỉ quản lý version table/quyền, không tạo bảng nghiệp vụ; đây vẫn là truy cập dev ngoài mục tiêu kiểm thử.

Đã bổ sung: test process/subprocess dùng APP_ENV=test; Settings bỏ đọc env file trong chế độ đó; URL database test chỉ được loopback + commerce_test; URL broker test chỉ được loopback; dev bootstrap bị từ chối trong test. Có regression tests cho việc bỏ qua env file và chặn host remote. Supabase credential và .env thật được giữ nguyên. Full suite sau sửa dùng DB/broker Docker riêng.

## 8. Phần để sau

Chưa cấp broker dev chung, dựng Compose của cả nhóm, viết inbox/outbox/retry/Saga, handler nghiệp vụ hoặc frontend. Worker hiện không xử lý message nên không được gọi là luồng đơn hàng hoàn chỉnh. Những phần này phải được triển khai và nghiệm thu riêng.

Tham khảo: [aio-pika API](https://docs.aio-pika.com/apidoc.html), [RabbitMQ confirms/acknowledgements](https://www.rabbitmq.com/docs/confirms), [reliability](https://www.rabbitmq.com/docs/reliability).
