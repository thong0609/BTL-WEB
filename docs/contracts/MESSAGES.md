# Hợp đồng command và event

Version 1 — bản thiết kế MVP. Command là yêu cầu; event là kết quả đã commit. Order điều phối, Inventory/Payment không tự quyết định kết thúc đơn. Liên quan [workflow](../THIET-KE-LUONG-XU-LY.md).

## 1. Envelope bắt buộc

```json
{
  "messageId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "type":"ReserveStock",
  "version":1,
  "correlationId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "causationId":null,
  "occurredAt":"2026-10-24T12:00:00Z",
  "payload":{
    "orderId":"cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "operationId":"dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "items":[{"productId":"11111111-1111-4111-8111-111111111111","quantity":2}]
  }
}
```

Tất cả ID UUID; occurredAt UTC; version là phiên bản schema, khác paymentVersion. causationId là message gây ra phản hồi; NULL nếu bắt đầu từ HTTP. Retry publish giữ messageId; retry nghiệp vụ giữ operationId. Không đưa địa chỉ/mật khẩu/token vào message khi consumer không cần.

## 2. Định tuyến

| Exchange durable | Loại | Routing key | Queue durable | Consumer |
| --- | --- | --- | --- | --- |
| commerce.commands | direct | inventory.reserve/release/commit | inventory.commands | Inventory |
| commerce.commands | direct | payment.initialize-cod/process/collect-cod/cancel-cod/refund | payment.commands | Payment |
| commerce.events | topic | inventory.stock-reserved/stock-reservation-failed/stock-released/stock-release-failed/stock-committed/stock-commit-failed | order.events | Order |
| commerce.events | topic | payment.initialized/succeeded/failed/cod-collected/cod-cancelled/refunded/refund-failed/command-rejected | order.events | Order |

Mỗi key trong ô có binding riêng; ký hiệu `/` rút gọn các lựa chọn, không phải một routing key chứa tất cả. Bổ sung exchange dead-letter và retry queues theo cấu hình triển khai. Consumer nhận các event riêng vào cùng order.events vẫn phải dispatch handler theo type.

## 3. Payload command

Mọi command có orderId và operationId. Các số tiền là chuỗi nguyên VND, quantity integer > 0. Bảng dưới là field bổ sung; không tùy ý thêm field từ client.

| type | Bên gửi → nhận | Field bổ sung | Điều kiện |
| --- | --- | --- | --- |
| ReserveStock | Order → Inventory | items[{productId,quantity}] | 1–50 dòng không trùng SKU; giữ toàn bộ hoặc không |
| ReleaseStock | Order → Inventory | reservationId, reason | RESERVED; RELEASED trả kết quả đã hoàn tất; COMMITTED từ chối |
| CommitStock | Order → Inventory | reservationId | RESERVED; COMMITTED trả kết quả cũ; RELEASED từ chối |
| InitializeCodPayment | Order → Payment | customerId, amount, currency | Một payment/order, chờ thu |
| ProcessPayment | Order → Payment | customerId, amount, currency | Kịch bản do Payment đọc config demo, không nằm trong command khách |
| RecordCodCollection | Order → Payment | paymentId, collectedBy | COD AWAITING_COLLECTION; actor ADMIN đã được Order kiểm tra |
| CancelCodPayment | Order → Payment | paymentId, reason | COD chưa thu |
| RefundPayment | Order → Payment | paymentId, amount, currency, reason | SIMULATED đã trả, hoàn toàn bộ gồm phí ship |

Lặp operationId cùng payload trả kết quả đã lưu; khác payload là OPERATION_CONFLICT. Reserve bị thiếu hàng vẫn lưu kết quả để lần gửi lại không bỗng giữ thành công sau nhập kho.

## 4. Payload event

Mọi event có orderId và operationId của command tương ứng. Event về tiền còn có paymentId, paymentVersion, paymentStatus; Order dùng version để chặn event cũ. Event không tự chứa lệnh đổi trạng thái đơn.

| type | Field bổ sung ngoài phần chung | Ý nghĩa |
| --- | --- | --- |
| StockReserved | reservationId, items[{productId,quantity}] | Đã giữ đủ, transaction commit |
| StockReservationFailed | code, shortages[{productId,requested,available}] | Không giữ mặt hàng nào; code có thể PRODUCT_NOT_STOCKED/INSUFFICIENT_STOCK |
| StockReleased | reservationId | Đã giải phóng hoặc đã giải phóng trước đó |
| StockReleaseFailed | reservationId, code | Trạng thái không hợp lệ, cần đối chiếu |
| StockCommitted | reservationId | Đã xuất hàng đúng một lần |
| StockCommitFailed | reservationId, code | Không xuất được, Order chưa chuyển SHIPPING |
| PaymentInitialized | method=COD, amount, currency | Đã tạo nghĩa vụ AWAITING_COLLECTION |
| PaymentSucceeded | method=SIMULATED, amount, currency | SUCCEEDED |
| PaymentFailed | amount, currency, code | FAILED xác định; không dùng cho timeout |
| CodCollected | amount, currency, collectedBy | SUCCEEDED, thu COD được ghi nhận |
| CodPaymentCancelled | amount, currency | CANCELLED, không còn nghĩa vụ thu |
| PaymentRefunded | refundId, amount, currency | REFUNDED toàn bộ |
| PaymentRefundFailed | refundId, code, retryable | Vẫn REFUND_PENDING, Order chưa kết thúc hủy |
| PaymentCommandRejected | rejectedType, code | Lệnh không hợp lệ; có paymentId/version/status nếu đã tồn tại |

Đối với PaymentCommandRejected khi payment chưa tồn tại, paymentId/version/status có thể NULL và phải giữ orderId/operationId để tra cứu. Lỗi kỹ thuật tạm thời không được đổi thành PaymentFailed nghiệp vụ. Message sai schema/unknown version đi DLQ sau ghi thông tin cần thiết, không tạo event có dữ liệu bịa.

## 5. Thứ tự, trùng và độ bền

Outbox + persistent + confirms/routing giúp gửi đáng tin cậy; inbox + unique operationId giúp xử lý lặp. Không bảo đảm exactly-once, không dựa vào thứ tự toàn cục của broker. Khi publish confirm bị mất, dùng lại messageId; consumer có thể ACK message đã xử lý sau khi xác minh record.

Version schema thay đổi tương thích: chỉ thêm field tùy chọn, consumer bỏ qua field chưa biết. Đổi tên/ý nghĩa/kiểu field cần version mới và kế hoạch chạy song song; thêm test contract trước merge. Mỗi hợp đồng có chủ sở hữu: command do cả sender/receiver review; event do producer sở hữu, Order review consumer.

## 6. Test contract tối thiểu

Producer tạo fixture cho mỗi type; consumer validate envelope, required fields, số tiền, enum, quantity và unknown version. Test message trùng, cùng operationId khác messageId, payload khác trên cùng operationId, event version cũ, event đến muộn và replay từ DLQ. Fixtures phải dùng ID cố định dễ đối chiếu, không dùng dữ liệu người thật.
