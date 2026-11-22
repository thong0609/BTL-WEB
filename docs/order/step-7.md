# Step 7 — Lấy sản phẩm từ Catalog và báo giá checkout

Người phụ trách: **Mạnh**. Ngày thực hiện: **07/11/2026**.

**Đã làm phần Order: client Catalog, tính tiền, API báo giá và routing Gateway.** API batch của Catalog chưa có handler trong repo, nên kết nối thật còn chờ chủ Catalog. Hình dạng dữ liệu và credential bên dưới là dự thảo đã có code/test phía Order, chưa phải quyết định đã được đồng đội xác nhận.

## 1. Step này làm gì?

Khách gửi sản phẩm và số lượng; Order hỏi Catalog giá hiện tại rồi cộng phí ship do server cấu hình. Ví dụ test: 2 sản phẩm giá 200000 + ship 30000 = 430000 VND. Khách không được tự gửi giá để server dùng làm báo giá.

Quote chỉ là báo giá tại thời điểm gọi. Nó không khóa giá, không kiểm tra chắc chắn đủ tồn, không giữ hàng, không tạo đơn, không gọi Payment và không tạo message. Khi khách bấm đặt, Step 8 sẽ kiểm tra giá lại; Inventory quyết định giữ hàng ở các bước workflow sau.

## 2. Đã triển khai

| Phần | Hành vi |
| --- | --- |
| `POST /api/v1/orders/quote` | Chỉ CUSTOMER; nhận 1–50 productId khác nhau, mỗi quantity là integer 1–999 |
| Catalog client | HTTPX async dùng lại kết nối trong lifespan; timeout/pool; requestId; không follow redirect hoặc dùng proxy env |
| Gọi batch | Gửi `{productIds:[UUID]}` tới đúng `/internal/products/batch`; dùng credential riêng của Order, không chuyển token khách sang Catalog |
| Kiểm tra dữ liệu | Ghép theo ID dù Catalog trả khác thứ tự; kiểm tra SKU/tên/status, money string VND, version; từ chối trùng ID/SKU, ID ngoài yêu cầu hoặc dữ liệu sai |
| Tính tiền | Tính số nguyên có giới hạn bigint; trả tiền dạng string, quotedAt UTC; lấy SKU/tên/giá/version từ Catalog |
| API độc lập DB | Quote chạy được khi không bật DB/broker; không ghi bất kỳ bảng Order nào |
| Gateway | Có POST route cố định cho quote, giữ Bearer và requestId, response `Cache-Control: no-store` |

Mã lỗi đang triển khai theo dự thảo:

- 400 VALIDATION_ERROR: input sai hoặc phép cộng/nhân tiền vượt giới hạn.
- 404 NOT_FOUND: thiếu sản phẩm hoặc status khác ACTIVE; chỉ trả thông báo chung, không lộ tên/giá sản phẩm ngừng bán.
- 503 DEPENDENCY_UNAVAILABLE: Catalog timeout/lỗi/xác thực service thất bại, response sai, chưa cấu hình credential hoặc phí ship. Không thay lỗi bằng giá 0.
- Auth dùng chung với Step 6: chưa có verifier Identity thật thì API vẫn đóng mặc định.

## 3. Cấu hình đã chuẩn bị

| Biến | Cách dùng |
| --- | --- |
| `CATALOG_BASE_URL` | Native mặc định `http://127.0.0.1:3002`; Compose đã đặt `http://catalog-service:3002` |
| `CATALOG_SERVICE_TOKEN` | Secret riêng Order gọi Catalog; dự thảo dùng `Authorization: Bearer ...`; không commit token vào Git |
| `SHIPPING_FEE_AMOUNT` | Số nguyên VND do nhóm chốt; **chưa đặt mặc định** |
| `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_CONNECTIONS` | Dùng cấu hình client HTTP hiện có |

Các biến được ghi ở [env example](../../apps/order-service/.env.example). Compose nhận secret/phí qua env file Order đang dùng, `infra/.local/apps/order-service.env`; chạy native dùng `.env` của Order. Chỉ điền khi có quyết định thật, không lấy 30000 của fixture làm quyết định nhóm. Chưa thêm credential thật hoặc thay `.env` đang dùng.

## 4. Dự thảo để đưa chủ Catalog xem

Đọc [OpenAPI internal batch](../contracts/catalog-internal.openapi.yaml), phiên bản `0.1.0-draft`:

```json
{"productIds":["10000000-0000-4000-8000-000000000011"]}
```

Response được Order hỗ trợ:

```json
{
  "items": [{
    "id":"10000000-0000-4000-8000-000000000011",
    "sku":"DEMO-MOUSE", "name":"Chuột thử nghiệm", "status":"ACTIVE",
    "priceAmount":"200000", "currency":"VND", "version":3
  }]
}
```

ID không tồn tại được bỏ khỏi items; ID đã tìm thấy có thể trả khác thứ tự. Mỗi sản phẩm có một bản ghi, không trả thêm ID ngoài yêu cầu. Order chuyển thành `productId`, `unitPriceAmount`, `catalogVersion` ở public quote; không bắt Catalog dùng tên field riêng của Order. Route internal không được mở qua Gateway.

## 5. Cần chốt với đồng đội — riêng Step 7

| Trao đổi với ai? | Nói dễ hiểu | Cần nhận được gì? |
| --- | --- | --- |
| Người làm Catalog | “Order đã làm phần gọi lấy nhiều sản phẩm. Bạn xem file dự thảo: nhận productIds, trả items có id/SKU/tên/status/priceAmount/currency/version như này được không? ID thiếu thì bỏ khỏi items nhé?” | Xác nhận/sửa contract, triển khai batch thật và test hai service với nhau; thống nhất lỗi missing/inactive như trên |
| Người làm Catalog/người quản lý cấu hình | “Order dùng token riêng nào để gọi API nội bộ? Bên Catalog kiểm tra Bearer và cấp quyền cho Order thế nào?” | Cách cấp/xác minh/đổi credential; secret thật đưa ngoài Git. Hiện là đề xuất, không tự dùng JWT khách hoặc token demo |
| Nhóm/người chốt nghiệp vụ | “Phí giao hàng MVP là bao nhiêu VND? Có dùng một mức cố định cho mọi đơn không?” | Giá trị cho SHIPPING_FEE_AMOUNT; nếu phí phụ thuộc địa chỉ thì phải sửa contract quote vì input hiện chỉ có items |

Không cần chốt IP giữa các laptop: URL native/Compose đã có. Auth người dùng là việc còn mở từ [Step 6](step-6.md#8-riêng-step-6-cần-chốt-với-đồng-đội), vẫn là điều kiện trước khi dùng token thật.

## 6. Code và kiểm chứng

- [clients/catalog.py](../../apps/order-service/src/commerce_order/clients/catalog.py): adapter theo dự thảo, kiểm tra response và lọc lỗi.
- [services/quote.py](../../apps/order-service/src/commerce_order/services/quote.py): lấy snapshot và tính tiền.
- [api/customer.py](../../apps/order-service/src/commerce_order/api/customer.py), [main.py](../../apps/order-service/src/commerce_order/main.py), [settings.py](../../apps/order-service/src/commerce_order/settings.py): endpoint, vòng đời client và cấu hình.
- [test_checkout_quote.py](../../tests/order/test_checkout_quote.py), [test_contract.py](../../tests/order/test_contract.py), [test_checkout_api.py](../../tests/order/test_checkout_api.py): unit/contract, quote không ghi DB và lỗi Catalog.

Kết quả toàn suite và lệnh chạy được ghi chung ở [Step 8](step-8.md#5-kiểm-chứng-và-chạy-lại). Catalog được giả lập ở transport trong test; không có nhánh fake Catalog trong runtime. Test contract chỉ chứng minh caller khớp dự thảo, chưa chứng minh Catalog producer đã triển khai hoặc đồng ý.
