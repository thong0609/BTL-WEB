# Step 3 — Domain và schema public của Order

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Đã triển khai phần độc lập của Step 3 theo hợp đồng hiện tại.** Có enum, tính tiền, quy tắc chuyển trạng thái/quyền thao tác, DTO Pydantic và test. Phần này không cần credential Supabase hoặc service khác chạy thật; các mục cần đối chiếu khi tích hợp được ghi ở mục 6.

## 1. Step 3 làm gì, dễ hiểu nhất?

Step 2 chuẩn bị chỗ chạy. Step 3 viết **các quy tắc và khuôn dữ liệu của Order**:

- Một đơn có những trạng thái nào, khi nào được hủy/giao/hoàn thành.
- Khách/ADMIN được làm những thao tác nào với đơn.
- Tính tiền thế nào và chặn dữ liệu vượt giới hạn.
- Dữ liệu gửi vào/trả ra API phải có những trường nào, đúng tên và kiểu gì.

Ví dụ thực tế đã được kiểm tra: 2 chuột × 200000 + phí ship 30000 = **430000**. Nội bộ dùng số nguyên, JSON gửi ra là **`"430000"`**. Giá trị ship trong ví dụ là fixture, không được viết cứng thành phí thật của cửa hàng.

Chưa có endpoint đặt/hủy đơn thật, ORM nghiệp vụ, migration mới hoặc consumer message trong bước này. Router/use case/transaction ở các bước sau sẽ gọi lại những quy tắc vừa viết; bộ khung API đang chạy không tự nhiên có thêm chức năng đặt hàng chỉ vì có schema.

## 2. Code đã thêm

| File | Công việc |
| --- | --- |
| [domain/enums.py](../../apps/order-service/src/commerce_order/domain/enums.py) | 8 trạng thái Order, phương thức/trạng thái tiền, workflow phase/state, bước kho/tiền, vai trò và action |
| [domain/money.py](../../apps/order-service/src/commerce_order/domain/money.py) | Parse tiền chuỗi, tính dòng/tổng/ship bằng số nguyên, kiểm tra quantity, số dòng và giới hạn bigint |
| [domain/transitions.py](../../apps/order-service/src/commerce_order/domain/transitions.py) | Bảng chuyển trạng thái, guard bằng chứng, allowed_actions và ensure_action_allowed dùng chung điều kiện |
| [api/schemas.py](../../apps/order-service/src/commerce_order/api/schemas.py) | DTO request/response theo OpenAPI, alias camelCase, validate dữ liệu và serialize JSON |
| [tests/order](../../tests/order) | Unit/contract test và kiểm tra HTTP validation bằng route chỉ tồn tại trong test |

Không đổi public OpenAPI/MESSAGES, shared MoneyAmount hoặc lockfile trong Step 3. Model nghiệp vụ của Order không được đưa vào backend-common. Các package mới có `__init__.py`; import những module này không tự mở DB/broker hoặc khởi động worker.

## 3. Quy tắc đã triển khai

### 3.1. Tiền và số lượng

- Mọi phép tính tiền dùng `int`; không dùng float.
- Tiền không âm và không vượt `9223372036854775807` — giới hạn bigint PostgreSQL, kể cả kết quả nhân/cộng trung gian.
- Money trên request bắt buộc là chuỗi chữ số ASCII: `"200000"` hợp lệ, JSON number `200000`, boolean, `"2.5"`, số âm, dấu `+`, khoảng trắng và chữ số Unicode bị từ chối.
- Tiền chuỗi có số 0 đầu được chuẩn hóa theo giá trị; output luôn là chuỗi số nguyên chuẩn. Response DTO nhận được số nguyên nội bộ để tiện dựng view.
- Số lượng phải là integer 1–999; không tự đổi `true`, `2.0` hoặc `"2"` thành số lượng.
- Một request quote/create có 1–50 dòng. ProductId trùng bị chặn sau khi chuẩn hóa UUID, không tự gộp dòng checkout.
- Schema snapshot còn kiểm tra SKU trùng, tiền từng dòng và tổng bằng tổng dòng + ship. SKU chưa có trong request checkout; chỉ kiểm tra được sau khi Catalog cung cấp dữ liệu để dựng snapshot.

### 3.2. Dữ liệu HTTP

Có QuoteInput, Quote, CreateOrder, Recipient, OrderAccepted, OrderSummary, Order, ActionResult, Reason, Complete và OrderPage; kèm các DTO dòng hàng/history/workflow cần thiết.

- Request dùng tên field camelCase đúng hợp đồng; snake_case từ HTTP không được chấp nhận thay thế.
- Field ngoài contract bị từ chối, kể cả `customerId`, `status`, `totalAmount`, `simulationScenario` do khách tự gửi.
- UUID được parse thành UUID; catalogVersion và thông tin phân trang phải là số nguyên đúng giới hạn, không nhận boolean.
- Tên/địa chỉ/điện thoại/lý do được trim trước kiểm tra. Lý do chỉ có khoảng trắng bị từ chối.
- `note` của CreateOrder có thể bỏ qua, nội bộ mặc định chuỗi rỗng; nếu có thì phải là string, không nhận null. Response Order vẫn cho phép note null theo OpenAPI.
- Thời gian response phải có timezone, khi serialize chuyển UTC ISO 8601 với `Z`.
- Complete bắt buộc `delivered: true` đúng boolean; COD còn cần `codCollected: true`. Phương thức thanh toán phải lấy từ đơn trong DB, không nhận khách tự khai ở payload complete.
- Field `history` và workflow view đúng tên contract; dữ liệu như operationId/retry payload không thể được thêm vào workflow view.
- Kiểm tra request sai đã đi qua handler validation chung và trả HTTP 400 với `{code, message, requestId, details}` trên route thử trong test.

### 3.3. Chuyển trạng thái và quyền thao tác

`OrderFacts` là trạng thái đáng tin cậy của đơn: chủ đơn, status, phương thức/trạng thái tiền, stock_step và workflow. `Actor` chứa user ID/vai trò đã được xác thực ở tầng gọi. Chúng là domain object, không phải cách cho client tự cấp danh tính.

- `allowed_actions` tạo danh sách cho frontend. `ensure_action_allowed` kiểm tra lại khi tiếp nhận action, dùng cùng logic; việc ẩn nút không thay kiểm tra backend.
- CUSTOMER chỉ hủy đơn của mình ở AWAITING_CONFIRMATION; ADMIN được hủy thêm PREPARING khi chưa bắt đầu dispatch. Sai chủ đơn dùng NOT_FOUND, gọi thao tác ADMIN bằng CUSTOMER dùng FORBIDDEN.
- Các action xác nhận/hủy/bàn giao/hoàn thành bị chặn khi workflow không ở IDLE/DONE, tiền chưa rõ hoặc điều kiện kho không phù hợp.
- Ghi ngoại lệ là ghi chú/cờ khi SHIPPING, chỉ dành cho ADMIN; vẫn cho ghi khi đang chờ thu COD. Nó không làm đơn COMPLETED hoặc tự tác động tới kho/tiền.
- Checkout chỉ tới AWAITING_CONFIRMATION khi kho RESERVED và COD AWAITING_COLLECTION hoặc SIMULATED SUCCEEDED.
- Không giữ được hàng mới REJECTED; payment thất bại xác định mới bắt đầu bù trừ. PENDING không được coi là FAILED.
- Chỉ SHIPPING khi có bằng chứng kho COMMITTED và đúng phase DISPATCH.
- Chỉ COMPLETED khi đã xác nhận giao và tiền SUCCEEDED; COD cần phase COMPLETION, nhánh mô phỏng có thể hoàn thành cục bộ từ workflow IDLE.
- Chỉ CANCELLED khi kho RELEASED và nhánh tiền đã xử lý xong. Refund còn REFUND_PENDING chưa đủ điều kiện.
- REJECTED/CANCELLED/COMPLETED không có transition hồi sinh về đơn đang chạy.

`transition_target` chỉ kiểm tra và trả trạng thái đích, không tự update DB. Consumer sau này phải xác minh message/order/operation/version trước khi xây facts; repository phải lock/recheck version và ghi lịch sử/outbox cùng transaction. Replay HTTP/message chưa thuộc Step 3, không được thay bằng việc cho phép mọi transition lặp.

## 4. Kết quả kiểm tra thực tế

| Kiểm tra | Kết quả |
| --- | --- |
| Test mới của Order | **125 ca mới**, đều pass trong suite cuối |
| Toàn backend không bật Docker integration | **204 passed, 5 skipped, 1 warning**, thời gian 9.26 giây |
| Lint/format toàn backend | PASS; 89 file đúng format |
| Typecheck toàn backend | PASS; 55 source file không có lỗi |
| Đối chiếu contract | Tên field, field bắt buộc, additionalProperties của 15 DTO khớp OpenAPI ở validation/serialization mode; enum public và kiểu money/delivered đúng contract |
| Fixture Step 1 | Quote, create COD/mô phỏng, hủy, complete và exception dùng được với schema đã viết |

Năm ca skip là PostgreSQL/RabbitMQ integration có opt-in. Không chạy lại chúng trong Step 3 vì không thay DB/messaging/migration; kết quả integration của môi trường được ghi tại [Step 2](step-2.md). Warning còn lại là TestClient/HTTPX deprecation kế thừa, không phải lỗi test mới.

Test mới bao phủ: giới hạn và tràn bigint từng phép tính, boolean/float/string quantity, tiền wire sai kiểu, trùng UUID/SKU, quá số dòng, snapshot sai tổng, trim/độ dài, field giả mạo, tên JSON, UTC, quyền CUSTOMER/ADMIN, workflow bận, kết thúc hủy thiếu một nhánh, nhầm trạng thái COD/mô phỏng, giao khi chưa xuất kho, hoàn thành chưa thu/đã giao và event cố hồi sinh đơn kết thúc.

Không có test nào kết nối hoặc ghi Supabase trong bước này.

## 5. Chạy lại và dùng code

Từ root repo, dùng môi trường đã chuẩn bị ở Step 2:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/order -q -o cache_dir=infra/.local/order-step3/pytest-cache
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend

# Chạy cả suite nền, giữ cache trong thư mục local của repo.
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step3/pytest-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend
```

Ví dụ dùng hàm tính tiền trong code use case sau này:

```python
from commerce_order.domain.money import calculate_totals

totals = calculate_totals([(200000, 2)], shipping_fee_amount=30000)
assert totals.subtotal_amount == 400000
assert totals.total_amount == 430000
```

Request DTO dùng `model_validate` với dữ liệu camelCase từ HTTP. View DTO có thể dựng từ số nguyên/tên Python nội bộ, rồi serialize bằng `model_dump(mode="json")`; tiền ra chuỗi. `Complete.validate_for_payment_method` phải được use case gọi với phương thức lấy từ đơn, trước khi ghi nhận yêu cầu complete. Việc xác thực nguồn giá/danh tính và áp dụng guard trong transaction thuộc các bước tiếp theo.

## 6. Những việc cần trao đổi với đồng đội

**Không còn đầu việc nào chặn phần code độc lập của Step 3.** Các mục sau là việc cần đối chiếu khi ghép dữ liệu/API thật, không phải yêu cầu duyệt lại toàn bộ enum hoặc MoneyAmount mới được tiếp tục.

| Trao đổi với ai? | Câu hỏi/nội dung dễ hiểu | Khi nào cần? |
| --- | --- | --- |
| Frontend/nhóm | “Mình đang dùng giới hạn trong tài liệu: tối đa 50 mặt hàng, mỗi mặt hàng 1–999; tên 150 ký tự, địa chỉ 10–1000, note/lý do 1000. Nhóm giữ các giới hạn này nhé; nếu đổi thì sửa contract và test cùng nhau.” | Trước hoàn thiện form và API thật; các ngưỡng là đề xuất đã có trong tài liệu, code hiện bám đúng chúng |
| Frontend | “Tiền gửi dạng chuỗi, field camelCase; COD complete phải có delivered/codCollected đúng true. Note có thể bỏ qua nhưng request không gửi null.” | Khi tích hợp checkout/đơn ADMIN; đây là định dạng đã có, cần hai bên code khớp |
| Catalog | “Kết quả batch cần productId, SKU duy nhất, tên, trạng thái, giá và catalogVersion đúng kiểu để Order kiểm tra/snapshot; gửi mẫu response và cách báo thiếu/ngừng bán.” | Step 7; ORD-OPEN-02 trong Step 1 |
| Payment | “Mình dùng COD AWAITING_COLLECTION và SIMULATED SUCCEEDED để tiếp nhận đơn. Các event/version và retry refund của bạn cần khớp contract để đưa vào guard.” | Step 9–14; version/error codes còn ORD-OPEN-05, chưa xử lý event thật ở đây |
| Nhóm/người phụ trách phí ship | “Phí ship thực tế sẽ cấu hình bao nhiêu?” | Step 7/8; hàm tính tiền nhận phí từ cấu hình, không mặc định 30000 cho production |
| Identity/Gateway | “Danh tính khách/ADMIN đã xác thực sẽ truyền và kiểm tra thế nào?” | Step 6; ORD-OPEN-01. Domain guard đã có nhưng chưa thay được xác thực token thật |

Những mục Supabase còn chờ từ Step 2 không ảnh hưởng unit test/domain/schema này. Cách chạy vẫn là một laptop/Compose; không có việc mới cần chốt IP hoặc máy chạy từng service.

## 7. Bước tiếp theo

Models và migration dùng enum/giới hạn vừa viết được triển khai ở [Step 4](step-4.md), kiểm chứng trên PostgreSQL riêng. Step 4 đã bổ sung reservationId nullable trong workflow và cập nhật thiết kế DB; không FK/join xuyên schema Inventory. Xem tài liệu Step 4 để biết tiến độ hiện tại thay vì suy ra cần chờ Inventory mới viết được model.
