# Step 8 — Tiếp nhận tạo đơn và ghi lệnh giữ hàng

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Đã triển khai `POST /api/v1/orders` ở Order và Gateway, dùng PostgreSQL thật để kiểm tra lưu nguyên khối, gửi lặp và rollback.** API trả 202 PROCESSING khi đã lưu tiếp nhận. Publisher phát lệnh và consumer nhận kết quả còn thuộc Step 9 trở đi; hiện chưa thể chạy hoàn chỉnh luồng giữ hàng/thanh toán.

## 1. Luồng đã có

1. Xác định CUSTOMER qua dependency xác thực; không nhận customerId/role do client tự khai. Kiểm tra body và `Idempotency-Key` bắt buộc, dài 1–128 ký tự.
2. Tìm yêu cầu đã được tiếp nhận theo customer/key. Cùng payload thì trả đúng response 202 cũ ngay, không gọi Catalog; khác payload trả 409 IDEMPOTENCY_CONFLICT.
3. Nếu là yêu cầu mới, gọi Catalog và tính quote hiện tại ở ngoài transaction DB. So sánh expectedUnitPriceAmount, expectedCatalogVersion và expectedShippingFeeAmount.
4. Nếu giá/version/phí khác, trả 409 PRICE_CHANGED và quote mới trong `details.quote`. Chưa ghi đơn/key/outbox; frontend phải cho khách xác nhận lại rồi dùng key mới cho payload mới.
5. Nếu khớp, mở transaction và kiểm tra key lại để xử lý request cạnh tranh. Lưu toàn bộ dữ liệu ở mục 2 trong một transaction; lỗi sẽ rollback.
6. Commit xong mới trả `{orderId,orderNumber,status:"PROCESSING"}` với HTTP 202. Khách GET chi tiết để biết tiến trình/kết quả sau đó.

Khách retry sau timeout phải giữ nguyên key và payload. Kể cả Catalog lỗi, phí đổi hoặc đơn đã tiến triển, yêu cầu đã tiếp nhận vẫn replay response ban đầu. Hai key khác nhau được coi là hai yêu cầu mua khác nhau.

## 2. Những gì được lưu cùng nhau

| Bảng | Nội dung lúc tiếp nhận |
| --- | --- |
| orders | UUID, mã đơn unique, customer từ principal, PROCESSING; tổng tiền server tính, người nhận/note/paymentMethod; chưa có paymentId |
| order_items | Snapshot productId, SKU/tên, giá, số lượng, line total, catalogVersion |
| order_status_history | Lịch sử đầu tiên từ chưa có trạng thái sang PROCESSING, actor CUSTOMER |
| order_workflows | CHECKOUT/WAITING, RESERVE_PENDING, NOT_REQUESTED; reserve_operation_id ổn định, reservation_id chưa có |
| idempotency_requests | Hash payload đã chuẩn hóa, key, orderId và response 202 để replay |
| outbox_messages | Đúng một ReserveStock tới commerce.commands / inventory.reserve, chứa orderId/operationId/items |

RequestId đã chuẩn hóa được dùng làm correlationId của workflow/history/outbox. Payload giữ hàng không chứa địa chỉ, số điện thoại hoặc token khách. Không gọi Inventory/Payment qua HTTP, không chờ RabbitMQ trong transaction và không giả lập thanh toán thành công.

Mã đơn hiện dùng UUID hex hoa 32 ký tự như Step 5; không thay định dạng ở bước này. Không thêm migration hoặc sửa schema của service khác.

## 3. PRICE_CHANGED trả ở đâu?

Giữ envelope lỗi chung; `ServiceError` đã được mở rộng với `details` tùy chọn. Gateway giữ code/status/quote public và chuẩn hóa requestId:

```json
{
  "code":"PRICE_CHANGED",
  "message":"Prices changed; confirm the new quote",
  "requestId":"10000000-0000-4000-8000-000000000901",
  "details":{
    "quote":{
      "items":[{
        "productId":"10000000-0000-4000-8000-000000000011",
        "sku":"DEMO-MOUSE", "name":"Chuột thử nghiệm", "quantity":2,
        "unitPriceAmount":"250000", "lineTotalAmount":"500000", "catalogVersion":4
      }],
      "subtotalAmount":"500000", "shippingFeeAmount":"30000",
      "totalAmount":"530000", "currency":"VND", "quotedAt":"2026-11-07T02:00:00Z"
    }
  }
}
```

Đây là ví dụ để frontend review; giá/phí/thời gian minh họa. Không tự gửi lại đơn theo giá mới mà chưa hỏi khách. Chi tiết lỗi chỉ chứa DTO quote được dựng từ dữ liệu đã kiểm tra, không đưa raw response Catalog/exception/credential vào lỗi.

## 4. Cần chốt với đồng đội — riêng Step 8

| Trao đổi với ai? | Nói dễ hiểu | Hiện đã làm được gì? |
| --- | --- | --- |
| Frontend + người review phần lỗi chung | “Nếu giá/phí thay đổi, đọc quote mới ở details.quote, cho khách xác nhận lại và tạo key mới. Nếu chỉ mất mạng sau bấm đặt thì giữ key cũ để tránh đặt hai đơn.” | Đã có handler chung, API/Gateway và test. Chờ frontend xác nhận cách đọc lỗi/UX; ORD-OPEN-08 chưa coi là đã được nhóm chốt |
| Catalog + nhóm | Dùng đúng quyết định API nội bộ/credential và phí ship của Step 7 | Caller/kiểm tra giá đã có; chưa có producer thật/credential/phí thật. Xem [bảng việc Step 7](step-7.md#5-cần-chốt-với-đồng-đội--riêng-step-7) |

Auth Identity thật còn mở từ Step 6; không thêm cơ chế giả để mở API dùng thử. **Step 7–8 chưa cần chốt lại command ReserveStock với Inventory/Payment:** payload theo contract hiện có và chỉ lưu outbox; test kết nối worker/message thật nằm ở các bước tiếp theo.

## 5. Kiểm chứng và chạy lại

Các ca mới bao gồm:

- Quote đúng số tiền/UTC, mapping batch khác thứ tự, cấu hình thiếu, response sai/trùng/ngoài ID, sản phẩm missing/inactive, timeout/redirect, bigint overflow; không tạo đơn/message khi quote.
- Tạo COD và SIMULATED đều chỉ tiếp nhận PROCESSING; kiểm tra snapshot, sáu nhóm dữ liệu được lưu và đúng một ReserveStock.
- Replay sau mất response khi Catalog lỗi hoặc đơn đã đổi trạng thái; key khác payload bị 409; hai HTTP request cạnh tranh chỉ có một đơn/outbox.
- Thay giá/version/phí nhận 409 kèm quote qua Gateway; không giữ key; xác nhận lại tạo được đơn.
- Catalog lỗi không để rác DB; lỗi sau khi flush đủ các insert vẫn rollback đơn/key/outbox; cùng key retry được sau khi hết lỗi.
- Input/key sai, body tự khai customerId/total/scenario bị chặn; thiếu token, giả header và ADMIN mua hàng bị từ chối.

**Kết quả toàn backend: 305 passed, 1 warning, không skip, trong 93.35 giây.** Có 48 ca mới của Step 7–8: 35 ca quote/client/config/auth/Gateway, 1 ca đối chiếu dự thảo internal với DTO và 12 ca API/PostgreSQL. Lint/format pass trên 116 file; typecheck pass trên 75 source file. Warning là TestClient/HTTPX deprecation đã có từ trước.

Container disposable được fixture dọn sau khi test kết thúc.

```powershell
# Các ca không cần container.
.\.venv\Scripts\python.exe -m pytest tests/order/test_checkout_quote.py tests/order/test_contract.py -q -o cache_dir=infra/.local/order-step78/unit-cache
.\.venv\Scripts\python.exe scripts/dev.py lint backend
.\.venv\Scripts\python.exe scripts/dev.py typecheck backend

# Docker Desktop đang chạy; test tự tạo và dọn PostgreSQL/RabbitMQ riêng.
$env:DOCKER_CONFIG = Join-Path (Get-Location) 'infra/.local/order-step2/docker-config'
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
$env:PYTEST_ADDOPTS = '-o cache_dir=infra/.local/order-step78/full-integration-cache'
.\.venv\Scripts\python.exe scripts/dev.py test backend --integration
```

PostgreSQL/RabbitMQ là container thật dùng một lần. Catalog là HTTP transport fixture, principal là dependency override chỉ trong test. Không tuyên bố đã test Catalog/Identity/Inventory/Payment thật hoặc checkout end-to-end; không dùng Supabase/DB dev và không reset dữ liệu nhóm.

## 6. File chính

- [api/customer.py](../../apps/order-service/src/commerce_order/api/customer.py), [api/dependencies.py](../../apps/order-service/src/commerce_order/api/dependencies.py): POST, principal CUSTOMER, lỗi và dependency.
- [services/persistence.py](../../apps/order-service/src/commerce_order/services/persistence.py): tiếp nhận nguyên khối, replay/race và PriceChanged mang quote mới.
- [errors.py dùng chung](../../packages/backend-common/src/commerce_backend_common/errors.py): details tùy chọn, caller cũ vẫn dùng được.
- [Gateway orders.py](../../apps/api-gateway/src/commerce_gateway/orders.py): hai POST cố định quote/create, chuyển JSON/key/Bearer/requestId.
- [test_checkout_api.py](../../tests/order/test_checkout_api.py): API Order/Gateway + PostgreSQL, rollback và cạnh tranh.

API dùng lại model/migration/repository/hash của các bước trước; publisher/consumer sẽ dùng outbox đã lưu ở Step 9.
