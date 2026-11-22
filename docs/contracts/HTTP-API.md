# Hợp đồng HTTP và quy ước tích hợp

Phiên bản thiết kế 0.1. [openapi.yaml](openapi.yaml) là cấu trúc máy đọc cho request/response. File này giải thích ngữ nghĩa, quyền và những endpoint còn cần mở rộng khi triển khai. Order/Gateway đã có 12 endpoint Order và test riêng; các service nghiệp vụ khác, auth và tích hợp toàn hệ thống còn chờ triển khai/ghép nhóm.

## 1. Quy ước chung

Triển khai backend bằng FastAPI/Python theo quyết định 28/10/2026. Pydantic alias/serializer phải giữ đúng contract camelCase, tiền dạng chuỗi và Error envelope bên dưới. Validation mặc định 422 của FastAPI cần handler chuẩn hóa sang 400 theo hợp đồng; schema tự sinh của service không tự động thay thế OpenAPI public đã thống nhất.

- Public base path: `/api/v1`. Frontend không gọi thẳng database, broker hoặc endpoint internal.
- JSON camelCase, ID UUID, timestamp ISO 8601 UTC, tiền VND là **chuỗi số nguyên** như `"430000"`; số lượng là integer.
- Bearer access token; refresh token trong cookie HttpOnly. ADMIN được kiểm tra tại service, không chỉ ẩn menu.
- Danh sách: `page` từ 1, `pageSize` 1–100 (mặc định 20); phản hồi `{items, page, pageSize, total}`.
- Lỗi: `{code, message, requestId, details?}`. details không chứa stack trace, secret hoặc dữ liệu khách khác.
- 400 đầu vào sai; 401 thiếu/hết phiên; 403 thiếu quyền; 404 không tồn tại/không được thấy tài nguyên; 409 xung đột trạng thái/key/giá; 429 giới hạn yêu cầu; 503 dependency chưa sẵn sàng.
- Header `X-Request-Id` do gateway tạo/chuẩn hóa và truyền nội bộ. Không tin header nhận dạng người dùng từ client.
- `Idempotency-Key` bắt buộc khi tạo đơn, điều chỉnh kho và thao tác đổi trạng thái đơn. Cùng key cùng actor/scope/payload trả cùng tài nguyên/kết quả tiếp nhận; khác payload trả IDEMPOTENCY_CONFLICT. Key lưu cùng command/workflow/history hoặc bảng kỹ thuật tương ứng, không chỉ lưu trong RAM.

Order Step 5 chuẩn hóa hash từ DTO đã validate: items sắp theo productId, UUID/money theo giá trị, text trim theo schema và các optional field có default được đưa về cùng biểu diễn; thứ tự key raw JSON không ảnh hưởng. Thay dữ liệu nghiệp vụ thực tế làm hash khác. Replay tạo đơn trả response tiếp nhận ban đầu, còn trạng thái hiện tại đọc GET; không tự hết hạn/xóa key trong MVP. Xem [chi tiết persistence](../order/step-5.md).

Schema OpenAPI tập trung các API MVP. Security trong OpenAPI thể hiện cần token; vai trò và chủ sở hữu vẫn phải triển khai bằng kiểm tra nghiệp vụ.

## 2. Checkout quote và tạo đơn

`POST /orders/quote`: CUSTOMER gửi `{items:[{productId,quantity}]}`. Order đọc Catalog, tính giá và phí cấu hình. Phản hồi gồm dòng hàng có sku/name/unitPriceAmount/lineTotalAmount/catalogVersion, subtotalAmount, shippingFeeAmount, totalAmount, currency và quotedAt.

Quote không giữ giá hoặc tồn. `POST /orders` gửi snapshot giá khách đã xác nhận:

```json
{
  "items": [{"productId":"11111111-1111-4111-8111-111111111111","quantity":2,"expectedUnitPriceAmount":"200000","expectedCatalogVersion":3}],
  "expectedShippingFeeAmount":"30000",
  "recipient":{"name":"Nguyễn An","phone":"0901234567","address":"12 đường A, phường B, TP Hồ Chí Minh"},
  "paymentMethod":"SIMULATED",
  "note":"Gọi trước khi giao"
}
```

Không có customerId, status, amount phải thu hoặc simulationScenario do khách tự chỉ định. Lấy customerId từ phiên. Order kiểm tra giá/phiên bản trước tạo; PRICE_CHANGED trả quote mới để khách xác nhận với key mới. Khi chấp nhận trả 202 `{orderId, orderNumber, status:"PROCESSING"}`. Thiếu tồn được biết sau đó qua workflow và GET chi tiết, không phải 202 bảo đảm mua thành công.

Validation thất bại trước khi tiếp nhận chưa giữ key. Đã tạo order thì replay cùng key trả phản hồi tiếp nhận cũ, GET chi tiết trả trạng thái hiện tại. Key cũ khác payload trả 409. Cùng actor nhưng hai key khác được coi hai yêu cầu mua khác, UI phải tránh tự sinh lại khi timeout.

Triển khai Order Step 7–8 đã có hai POST ở Order/Gateway. PRICE_CHANGED dùng HTTP 409 và quote mới ở `details.quote`, có đủ field Quote như response báo giá; vị trí này đã có code/test và đang chờ frontend/reviewer xác nhận (ORD-OPEN-08). Xem [ví dụ lỗi](../order/step-8.md#3-price_changed-trả-ở-đâu). Không tự tạo đơn theo giá mới khi khách chưa xác nhận.

Caller Catalog đang theo [OpenAPI internal dự thảo](catalog-internal.openapi.yaml), chưa phải API Catalog producer đã triển khai/đồng ý. Theo dự thảo, thiếu sản phẩm hoặc status khác ACTIVE trả 404 NOT_FOUND chung, không trả tên/giá inactive; timeout/lỗi/response sai trả 503 DEPENDENCY_UNAVAILABLE. Phí ship lấy từ SHIPPING_FEE_AMOUNT của server, chưa có giá mặc định; thiếu phí hoặc credential service cũng trả 503 cho quote/yêu cầu mới. Replay đơn đã tiếp nhận không cần gọi lại Catalog hoặc đọc phí hiện tại. Phép tính vượt bigint trả 400 VALIDATION_ERROR.

202 chỉ được trả sau commit nguyên khối order/items/workflow/history/key và một ReserveStock outbox. Không chờ broker hoặc gọi Inventory/Payment HTTP trong transaction. Worker đã có ở Step 9, các luồng/action ở Step 10–14; auth Identity thật vẫn là điểm mở Step 6.

## 3. Endpoint và quyền

| HTTP | Route sau base path | Chủ sở hữu / quyền | Kết quả |
| --- | --- | --- | --- |
| POST | `/auth/register` | Identity, public | 201 user CUSTOMER |
| POST | `/auth/login` | Identity, public | Access token + Set-Cookie refresh |
| POST | `/auth/refresh` | Identity, cookie + Origin/CSRF | Access token mới, rotate cookie |
| POST | `/auth/logout` | Identity, cookie + Origin/CSRF | 204, thu hồi phiên |
| GET | `/users/me` | Identity, đã login | Hồ sơ |
| GET | `/products`, `/products/{id}`, `/categories` | Catalog public | Chỉ dữ liệu bán công khai |
| POST | `/orders/quote` | Order CUSTOMER | Quote không giữ hàng |
| POST | `/orders` | Order CUSTOMER | 202 + orderId |
| GET | `/orders`, `/orders/{id}` | Order chủ đơn | Kể cả PROCESSING/REJECTED |
| POST | `/orders/{id}/cancel` | Order chủ đơn | 202, hoặc trạng thái hiện có nếu đã hủy |
| GET | `/payments/{id}` | Payment chủ sở hữu | Payment và refund tóm tắt, không secret |
| GET/POST/PATCH | `/admin/products`, `/admin/products/{id}` | Catalog ADMIN | Sản phẩm gồm DRAFT/ngừng bán |
| POST/DELETE | `/admin/products/{id}/images`, `/admin/products/{id}/images/{imageId}` | Catalog ADMIN | Upload ảnh/loại ảnh |
| GET/POST/PATCH | `/admin/categories`, `/admin/categories/{id}` | Catalog ADMIN | Danh mục |
| GET | `/admin/inventory`, `/admin/inventory/{productId}/movements` | Inventory ADMIN | Tồn và nhật ký |
| POST | `/admin/inventory/items` | Inventory ADMIN | Khởi tạo tồn 0, xác minh sản phẩm Catalog |
| POST | `/admin/inventory/adjustments` | Inventory ADMIN | Điều chỉnh onHand bằng delta + lý do + expectedVersion |
| GET | `/admin/orders`, `/admin/orders/{id}` | Order ADMIN | Đơn toàn cửa hàng |
| POST | `/admin/orders/{id}/confirm`, `/cancel`, `/dispatch`, `/complete` | Order ADMIN | Đồng bộ 200 hoặc tiếp nhận 202 tùy thao tác |
| POST | `/admin/orders/{id}/exceptions` | Order ADMIN | Note và cờ cần xử lý |
| GET | `/admin/overview` | Gateway ADMIN | Tổng hợp đếm đơn và sắp hết hàng, có generatedAt |
| GET/PUT | `/admin/demo/payment-scenario` | Payment ADMIN, chỉ môi trường demo | Cấu hình kịch bản mới, không sửa kết quả cũ |

Upload đề xuất JPEG/PNG/WebP tối đa 5 MiB/file, tối đa 5 ảnh/sản phẩm; kiểm tra magic bytes, decode hợp lệ, không chỉ tin Content-Type. Sắp ảnh bằng danh sách imageId trên PATCH sản phẩm trong transaction metadata, không nhận đường dẫn file tùy ý.

`complete` nhận `{delivered:true,codCollected:true}` với COD; mô phỏng chỉ cần delivered. Khách không gọi được API thu COD hoặc truyền trạng thái tiền trực tiếp.

Triển khai Step 12–13 đã có các POST hủy/customer và confirm/cancel/dispatch/complete/exceptions của admin, cùng routing Gateway. Key/payload được replay trước kiểm tra lại trạng thái; khác payload trả 409. Hủy đơn đã CANCELLED bằng key mới trả 202 với trạng thái hiện có, không phát thêm lệnh. Confirm/exceptions trả 200; cancel/dispatch/complete giữ 202, kể cả complete mô phỏng hoàn thành ngay.

Mọi action lưu input đã validate ở cột audit riêng, không đưa vào response. Ngoại lệ giao hàng không đổi status và không tạo history chuyển trạng thái giả; reason/actor/time vẫn được lưu. Guard trạng thái, khóa và outbox đều nằm trong transaction; lỗi trước commit chưa chiếm key.

## 4. View chi tiết đơn

Order trả `status`, `paymentStatus`, snapshot, timeline và `workflow:{phase,state,requiresAttention}`. Có `allowedActions` (ví dụ CANCEL/CONFIRM/DISPATCH/COMPLETE) do server tính cho người gọi; frontend dùng để hiển thị nhưng backend vẫn kiểm tra khi nhận thao tác.

Không trả trực tiếp order_workflows với operationId, retry payload hay stack trace cho khách. Đơn của người khác trả 404. Phân trang sắp xếp ổn định theo createdAt + id; response không bao giờ là danh sách không giới hạn.

Triển khai Order Step 6: danh sách dùng createdAt giảm dần rồi id giảm dần; count và items đọc trong cùng snapshot. `q` của `/admin/orders` tìm chuỗi con trong orderNumber, không phân biệt hoa/thường; khoảng trắng hai đầu được bỏ và ký tự `%`/`_` được hiểu theo nghĩa ký tự thường. Chưa tìm theo tên/điện thoại. API đọc đơn trả `Cache-Control: no-store`.

Trạng thái tích hợp auth hiện tại: Order có dependency xác thực đóng mặc định, chưa có adapter Identity thật. Thiếu Bearer trả 401; có Bearer nhưng chưa cấu hình bộ xác minh trả 503 AUTH_UNAVAILABLE. Không lấy user/role từ X-User-Id/X-Role của client. Tests dùng dependency override để kiểm chứng quyền, chưa phải login/token end-to-end đã hoạt động.

## 5. Mã lỗi nghiệp vụ

| code | HTTP / vị trí | Cách xử lý |
| --- | --- | --- |
| VALIDATION_ERROR | 400 | Chỉ rõ field |
| AUTH_INVALID / SESSION_EXPIRED | 401 | Login/refresh phù hợp |
| FORBIDDEN | 403 | Không thử lại cùng quyền |
| NOT_FOUND | 404 | Không lộ tài nguyên người khác |
| PRICE_CHANGED | 409 trước tạo đơn | Xem quote mới, xác nhận lại |
| IDEMPOTENCY_CONFLICT | 409 | Không dùng key cũ cho payload mới |
| ORDER_STATE_CONFLICT | 409 | Tải trạng thái mới |
| STOCK_VERSION_CONFLICT | 409 | Tải tồn rồi xác nhận điều chỉnh lại |
| INSUFFICIENT_STOCK | Kết quả workflow/inventory | Không tự retry thành đơn mới |
| PAYMENT_FAILED | Kết quả workflow | Chờ hủy xong rồi đặt lại nếu muốn |
| DEPENDENCY_UNAVAILABLE | 503 trước tiếp nhận | Retry có kiểm soát; nếu mất phản hồi vẫn replay cùng key |

## 6. API nội bộ

Chỉ mạng nội bộ + xác thực service, không đưa qua routing public:

- Catalog `POST /internal/products/batch`: lấy id/SKU/tên/status/price/version cho tối đa 50 sản phẩm. [OpenAPI internal](catalog-internal.openapi.yaml) hiện là dự thảo dùng bởi caller/test Order; chờ chủ Catalog xác nhận request/response/lỗi/Bearer service credential và triển khai handler thật.
- Inventory `POST /internal/availability/batch`: trạng thái có thể bán theo danh sách ID; không giữ hàng.
- Inventory `GET /internal/reservations/by-order/{orderId}`: đối chiếu reservation khi tiến trình treo.
- Payment `GET /internal/payments/by-order/{orderId}`: đối chiếu trạng thái/version và refund nếu có.

Step 14 có [OpenAPI recovery dự thảo](order-recovery.openapi.yaml) và caller Order. Producer cần xác nhận/triển khai response/auth. Trạng thái kết thúc cần kèm message kết quả gốc để replay qua inbox; PENDING chỉ được phản chiếu khi khớp đúng command/operation/số tiền. 404/timeout không tự tạo PaymentFailed hoặc hủy đơn. Endpoint nội bộ không được route qua Gateway.

MVP có thể dùng credential riêng từng caller trong secret cấu hình, truyền qua TLS khi qua host; không dùng chung JWT khách làm credential service. Rotation và giới hạn caller/route phải được ghi khi dựng môi trường. Các API internal cần đặc tả OpenAPI riêng trước khi triển khai caller, tránh đưa secret scheme vào API công khai.
