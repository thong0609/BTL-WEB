# Step 5 — Repository, transaction và chống request lặp

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Đã triển khai phần độc lập Step 5**, gồm repository, hash chuẩn hóa, transaction nhận đơn và khung nhận action có replay/khóa dữ liệu. Đây là code nội bộ để các bước API/workflow sau sử dụng, chưa mở POST tạo/hủy/xác nhận đơn cho người dùng.

## 1. Kết quả dễ hiểu

Nếu khách gửi lại cùng yêu cầu do mạng mất phản hồi, Order nhận ra key đã dùng và trả lại **cùng mã đơn/kết quả tiếp nhận**. Nếu dùng key cũ cho nội dung khác thì báo IDEMPOTENCY_CONFLICT. Các bản ghi của một lần tạo đơn được lưu cùng transaction, tránh có đơn nhưng thiếu snapshot/workflow/key/outbox.

Hai request đồng thời có thể cùng chưa thấy key ở đầu luồng. Unique constraint trong PostgreSQL quyết định bản ghi thắng; lần thua rollback cả lần ghi thử rồi đọc kết quả đã commit. Không chỉ dựa vào `if key exists` hoặc bộ nhớ Python.

## 2. Code đã thêm

| File | Chức năng |
| --- | --- |
| [repositories/orders.py](../../apps/order-service/src/commerce_order/repositories/orders.py) | Lấy đơn, items/history, phân trang và lock header -> workflow |
| [repositories/idempotency.py](../../apps/order-service/src/commerce_order/repositories/idempotency.py) | Lookup key tạo đơn theo customer/scope và key action theo actor/order/action |
| [services/idempotency.py](../../apps/order-service/src/commerce_order/services/idempotency.py) | Validate key và hash SHA-256 chuẩn hóa request/action |
| [services/persistence.py](../../apps/order-service/src/commerce_order/services/persistence.py) | OrderPersistence.accept_order/accept_action, StoredResponse, replay và transaction |
| [test_idempotency_and_auth.py](../../tests/order/test_idempotency_and_auth.py) | Test chuẩn hóa hash và các guard auth/Gateway của Step 6 |
| [test_persistence_and_queries.py](../../tests/order/test_persistence_and_queries.py) | PostgreSQL thật cho concurrent replay, rollback, khóa action và API đọc ở Step 6 |

## 3. Quy tắc hash đã thống nhất trong code

- Chỉ hash request đã qua schema, không hash chuỗi raw JSON.
- JSON được sắp xếp key, biểu diễn Unicode ổn định, không có khoảng trắng phân cách dư.
- Items sắp theo productId khi tính hash: đổi thứ tự dòng không biến thành một lần mua khác.
- UUID/money được chuẩn hóa theo giá trị; money `"000200000"` và `"200000"` cùng nghĩa.
- Tên/địa chỉ/điện thoại/note/lý do được trim theo schema Step 3.
- Note bỏ qua và note chuỗi rỗng cùng nghĩa; Complete bỏ qua codCollected và codCollected=false cùng nghĩa. COD vẫn cần true khi chấp nhận complete.
- Thay quantity, giá/version đã xác nhận, phí ship, người nhận, phương thức hoặc nội dung note thực tế làm hash khác.
- Key giới hạn 1–128 ký tự theo contract. Actor/scope/order/action được tách ở unique key trong DB, không đọc actor từ payload khách.
- Chưa có TTL hoặc job tự xóa key. Replay response được copy khỏi ORM, không trả reference để caller vô tình sửa record đang giữ.

## 4. Transaction tạo đơn

`accept_order(actor, key, request, load_quote)` nhận CUSTOMER principal đã xác thực và callback trả Quote đáng tin cậy từ tầng đọc Catalog trong tương lai:

1. Validate key/hash và lookup replay. Đã nhận trước đó thì trả response cũ ngay, không gọi Catalog.
2. Request mới gọi load_quote khi không giữ transaction DB/row lock. Quote phải được xác minh sản phẩm ACTIVE tại adapter Catalog ở Step 7.
3. Mở transaction mới, lookup lại key để xử lý request khác vừa thắng; rồi đối chiếu giá/version/phí/quantity với khách đã xác nhận.
4. Trong savepoint: tạo header, flush để có parent; lưu items, workflow CHECKOUT/WAITING, history, key/response 202 và outbox ReserveStock.
5. Commit cả cụm hoặc rollback cả cụm. Nếu unique key tạo đơn xung đột, rollback savepoint, đọc winner và kiểm tra hash. Không nuốt lỗi unique khác hoặc lỗi DB không liên quan.

Nếu load_quote lỗi nhưng một request đồng thời vừa nhận thành công, có lookup lại để trả đúng replay. Nếu chưa có winner thì lỗi đọc giá được giữ nguyên và không giữ key. Quote khác nội dung đã xác nhận trả PRICE_CHANGED nội bộ, chưa tạo key/đơn; HTTP adapter và quote trong error details thuộc Step 7/8.

Mã đơn hiện dùng UUID của đơn viết hex hoa 32 ký tự, phù hợp varchar(32), không tạo bộ đếm dùng chung. Đây là định dạng thực thi ban đầu; nếu nhóm cần mã hiển thị dạng ngày/số thứ tự thì thống nhất trước khi đổi, không ảnh hưởng khóa UUID nội bộ.

## 5. Transaction action

`accept_action` là khung cho các thao tác ở Step 12/13, chưa phải workflow hủy/giao/thu tiền đã hoàn chỉnh:

- Mỗi lần gọi có session/transaction riêng. Mọi writer phải lock **orders trước, order_workflows sau**.
- Kiểm tra chủ đơn/quyền; lookup replay trước kiểm tra trạng thái hiện tại để key cũ vẫn trả kết quả cũ sau khi đơn đã tiến triển.
- Đánh giá guard bằng dữ liệu bên trong lock; chặn stale state, workflow bận và điều kiện kho/tiền không hợp lệ.
- Callback `apply` chỉ ghi bằng session đang có, không gọi HTTP/broker. Nó bổ sung history/outbox và thay đổi nghiệp vụ phù hợp ở bước triển khai action sau.
- Sau callback thành công, khung tự tăng version đơn/workflow, lưu action key/hash/response rồi commit. Callback không tự commit hoặc tự tăng version lần nữa.
- Callback lỗi: rollback mọi thay đổi, không chiếm key. Replay không gọi callback hoặc tăng version.
- Hai thao tác hủy/bàn giao cạnh tranh phải có một thao tác thắng; bên còn lại recheck dữ liệu sau lock và nhận ORDER_STATE_CONFLICT.

ReserveStock hiện mới lưu trong outbox, chưa publish và chưa giữ tồn thật. Inbox/publisher/recovery sẽ triển khai ở Step 9/14; không tự chạy khi import service hoặc start API.

## 6. Kiểm chứng

Tests PostgreSQL đã chạy thành công cho: replay khi Catalog ngừng; cùng key cùng/khác payload đồng thời; unique loser rollback sạch; lỗi trước commit; giá đổi không giữ key; action replay sau đổi state; callback lỗi rồi thử lại; reason khác trên key cũ; hủy cạnh tranh bàn giao. Những callback mô phỏng trong test kiểm tra transaction/guard, không được tính là Inventory/Payment/workflow thật đã chạy.

Kết quả tổng cuối Step 5–6 và lệnh chạy lại ghi trong [Step 6](step-6.md). Toàn bộ DB test là commerce_test disposable, không đọc `.env` dev/Supabase.

## 7. Riêng Step 5 cần trao đổi gì?

**Không có thông tin từ đồng đội bắt buộc phải chờ để hoàn thành lớp persistence này.** Các quy tắc key/hash/lock bám contract hiện tại và được ghi rõ để các bên sử dụng đúng.

- Với frontend/người gọi API: cùng thao tác bị timeout phải giữ nguyên key; nội dung mới dùng key mới. Replay trả response tiếp nhận ban đầu, trạng thái mới đọc qua GET.
- Nếu nhóm muốn định dạng orderNumber khác 32 ký tự hex, chốt yêu cầu hiển thị trước khi thay thuật toán sinh mã; hiện đã có định dạng dùng được.
- Các writer Order được viết tiếp phải dùng cùng thứ tự khóa và transaction; không tự gọi commit trong callback.

Token Identity, địa chỉ máy và dữ liệu thanh toán không phải điều kiện để unit/integration-test lớp Step 5 này. Chúng không được giả lập thành dữ liệu production chỉ để đánh dấu hoàn thành.
