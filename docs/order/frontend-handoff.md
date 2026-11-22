# Bàn giao Order cho frontend và các chủ service

Đã có màn hình ở [Step 15](step-15.md). Chạy frontend bằng `npm.cmd --prefix apps/web run dev`; mở `http://localhost:3100/checkout` hoặc `/orders`. Hiện chưa đăng nhập/mua hàng thật được vì các phần tích hợp dưới đây chưa có.

Muốn bấm thử ngay: chạy `npm.cmd --prefix apps/web run demo:orders` sau khi frontend đã bật. Script mở hai cửa sổ Chromium có nhãn DEMO, khách/admin đăng nhập sẵn và dùng chung các đơn mẫu trong RAM; xem [hướng dẫn demo](demo.md#mở-giao-diện-bấm-thử-ngay-khi-chưa-có-identity). Auth thật của app không thay đổi.

## 1. Cần đồng đội nối những gì?

| Người/phần phụ trách | Đầu ra cần có |
| --- | --- |
| Identity + Gateway | Login/refresh/logout public; trả Token đúng OpenAPI; cookie refresh HttpOnly và kiểm tra Origin/CSRF phía server |
| Identity + Order | Bộ xác minh token thật qua seam `create_app(token_verifier=...)`; lấy UUID/role đã xác minh, xử lý hết hạn/thu hồi |
| Catalog + frontend giỏ hàng | Sản phẩm thật, thao tác thêm giỏ và chuyển sang `/checkout` |
| Catalog + Order | API batch nội bộ và service credential theo bản dự thảo đã gửi; chốt cấu hình phí ship |
| Inventory/Payment | Nhận 8 command, phát 14 loại event liên quan đúng contract; API recovery/token theo bản dự thảo |

Order đã có routing Gateway cho đủ 12 API của mình. Routing `/auth/*` và chức năng Identity **chưa được viết thay cho đồng đội**. Giao diện không dùng JWT tự giải mã để giả quyền, không nhận token qua URL hay ô nhập kỹ thuật.

## 2. Nối giỏ hàng

Trang sản phẩm/giỏ hàng gọi hàm sau trong Client Component, rồi chuyển tới `/checkout`:

```ts
import { parseCart } from "@/lib/orders";
import { saveCart } from "@/lib/order-intent";

saveCart(parseCart([
  { productId: product.id, quantity: 2 },
]));
router.push("/checkout");
```

Đầu vào chỉ có productId/quantity, tối đa 50 dòng khác nhau và quantity 1–999. Dữ liệu ở `sessionStorage["commerce.cart.v1"]`, không chứa giá tự quyết định. Order lấy tên/giá/version/phí từ server khi báo giá. Đây là giao diện ghép tạm cần frontend xác nhận; có thể thay adapter giỏ hàng mà giữ nguyên API Order.

## 3. Phiên đăng nhập

Provider dùng response `Token` trong [OpenAPI](../contracts/openapi.yaml): `{accessToken, expiresIn, user:{id,fullName,role,status,...}}`. Access token chỉ giữ trong RAM; không lưu mật khẩu/token vào localStorage/sessionStorage. Mở lại trang có thể bấm **Khôi phục phiên đã đăng nhập** để gọi refresh bằng cookie cùng origin. Khi hết hạn, màn hình yêu cầu đăng nhập/khôi phục, không tự phát lại thao tác ghi.

Logout khóa UI và xóa các yêu cầu Order đang lưu trong tab; nếu server logout lỗi, UI nói rõ chưa xác nhận thu hồi phiên. Frontend/Identity cần ghép chính sách CSRF/refresh thực tế trước khi bật cho người dùng.

## 4. API và ví dụ

Tất cả URL sau được gọi dưới `/api/v1`, với Bearer thật. Ví dụ request/response đầy đủ có trong [fixtures/http.json](fixtures/http.json); UUID, người nhận và giá ở đó chỉ là dữ liệu test.

| Việc | API | Lưu ý |
| --- | --- | --- |
| Báo giá | POST `/orders/quote`, body `{items:[{productId,quantity}]}` | Không giữ hàng/giá |
| Đặt đơn | POST `/orders` | Dùng expectedUnitPriceAmount/catalogVersion/phí từ quote đã xác nhận; Idempotency-Key bắt buộc |
| Xem | GET `/orders?page=1&pageSize=20`; GET `/orders/{id}` | Backend lấy chủ đơn từ token; không gửi customerId tự khai |
| Khách hủy | POST `/orders/{id}/cancel`, body `{reason}` | Theo allowedActions; có Idempotency-Key |
| Admin xem | GET `/admin/orders`; GET `/admin/orders/{id}` | Có `status`, `q` tìm mã đơn, phân trang |
| Admin thao tác | POST `/admin/orders/{id}/confirm`, `/cancel`, `/dispatch`, `/complete`, `/exceptions` | Mỗi yêu cầu có Idempotency-Key |

Confirm/dispatch gửi `{}`; cancel/exceptions gửi `{reason}`. Complete trả trước gửi `{delivered:true}`; COD gửi thêm `{codCollected:true}`. Actor, số tiền thu/hoàn và trạng thái lấy từ server.

HTTP 409 `PRICE_CHANGED` có quote mới ở `details.quote`. UI hiện hỗ trợ vị trí này: hiển thị lại, giữ người nhận, đợi khách bấm đặt hàng lần nữa bằng key mới. Nhóm vẫn cần review contract này trước tích hợp thật.

## 5. Gửi lại khi mất mạng

`mutate()` lưu `{path,key,body}` theo **user + endpoint** trong sessionStorage trước khi gửi. Timeout, lỗi 5xx hoặc response hỏng giữ bản này để retry cùng key/nội dung, kể cả sau reload. Lỗi 400/401/403/404/409 xác định cho phép sửa và gửi yêu cầu mới. Không tự retry POST theo timer.

Body đang chờ có thể chứa người nhận/lý do; chỉ giữ trong tab hiện tại và xóa khi nhận kết quả xác định hoặc logout. Không ghi body/token vào log. Không xóa bộ nhớ trình duyệt trong lúc yêu cầu còn chưa rõ kết quả; hãy kiểm tra danh sách đơn trước khi bắt đầu một yêu cầu mua mới.

GET chi tiết mới là trạng thái hiện tại; response replay/HTTP 202 không thay thế việc này. Tên/giá/địa chỉ của đơn lấy từ snapshot Order, không lấy lại Catalog.

## 6. Kiểm tra frontend độc lập

```powershell
npm.cmd --prefix apps/web ci
npm.cmd --prefix apps/web run lint
npm.cmd --prefix apps/web run typecheck
npm.cmd --prefix apps/web test
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) 'infra/.local/order-step1516/browsers'
& apps/web/node_modules/.bin/playwright.cmd install chromium
npm.cmd --prefix apps/web run test:e2e
```

Chromium mở Next ở cổng 3191, mock API chỉ trong test. Không coi kết quả này là login hoặc tích hợp Inventory/Payment thật.
