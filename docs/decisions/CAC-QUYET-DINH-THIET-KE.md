# Nhật ký quyết định thiết kế

Ngày lập 24/10/2026. Phân biệt **đã xác nhận bởi người dùng** và **đề xuất kỹ thuật để nhóm review**. Mỗi quyết định mới ghi ngày, người chốt, lý do, hệ quả và tài liệu cần sửa; chưa có tên người review thì không tự ghi là đã được cả nhóm duyệt.

| Mã | Quyết định | Trạng thái | Lý do / hệ quả |
| --- | --- | --- | --- |
| DEC-01 | Một cửa hàng, không sàn nhiều người bán | Người dùng xác nhận | Không có shop, hoa hồng hoặc chia đơn theo người bán |
| DEC-02 | Nhóm 5 người, định hướng microservices | Người dùng xác nhận | Cần contract và tích hợp sớm |
| DEC-03 | Payment riêng, mô phỏng thuộc MVP | Người dùng xác nhận | 5 service nghiệp vụ; test thành công/thất bại/chậm và hoàn mô phỏng |
| DEC-04 | Next.js/TypeScript + FastAPI/Python; PostgreSQL/SQLAlchemy/Alembic/RabbitMQ/Compose | Frontend Next.js/TypeScript và backend FastAPI được người dùng xác nhận; thư viện phụ trợ là đề xuất | Thay frontend Vite và backend NestJS trước đây; khóa phiên bản và kiểm tra tích hợp |
| DEC-05 | Một kho, VND, COD và phí ship cố định | Đề xuất kế thừa | Giảm biến thể quy trình; giá trị phí chưa chốt |
| DEC-06 | Một payment/order, một refund toàn phần/payment | Đề xuất | Retry cùng ID; thất bại đặt đơn mới sau hủy xong; không trả một phần |
| DEC-07 | Order điều phối, không có Saga service riêng | Đề xuất | Workflow lưu DB và outbox, không chỉ giữ RAM |
| DEC-08 | Outbox/inbox + unique operationId | Đề xuất cần thiết cho luồng | Gửi/nhận có thể trùng; không tuyên bố exactly-once |
| DEC-09 | Bản chính docs/, README ở gốc | Đề xuất tổ chức | Không sửa song song hai bản mô tả |
| DEC-10 | Quote không giữ giá/tồn; kiểm tra lại lúc tạo | Đề xuất mới | Thêm endpoint quote; PRICE_CHANGED yêu cầu xác nhận lại |
| DEC-11 | Khách chưa hủy khi PENDING; không tự hết hạn giữ | Đề xuất MVP | Cần job cảnh báo/đối chiếu để không mất dấu tiến trình |
| DEC-12 | Kubernetes/tracing nâng cao sau MVP | Đề xuất | Chỉ đổi nếu môn học bắt buộc, phải điều chỉnh thời gian |

## Các mục cần chốt trong buổi khởi động

**DEC-13 — Supabase PostgreSQL cho dev chung (28/10/2026, ACCEPTED, đã làm rõ):** dev hằng ngày của nhóm dùng một project, database `postgres`, 5 schema và role runtime/migration riêng. Thành viên chạy backend trên laptop kết nối DB dev này, không bắt buộc DB local cá nhân. Test reset dùng DB riêng cùng schema; local độc lập là tùy chọn. Broker dev chung, worker/service chạy theo phân công trên máy thành viên hoặc host dev. Production chưa quyết định. Tên *_db là miền dữ liệu logic; cấm truy cập chéo/FK xuyên service. Chưa tạo tài nguyên thực tế. Xem [chi tiết](../infrastructure/PHUONG-AN-SUPABASE.md).

Tên/ngành hàng; thời hạn và giờ mỗi người; phí ship; quyền ADMIN có cần tách không; giới hạn ảnh/số dòng; khoảng polling/retry/cảnh báo; cách triển khai HTTPS/service credential; tiêu chí môi trường demo. Kiểm tra yêu cầu giảng viên trước khi biến Kubernetes hoặc thanh toán thật thành đầu việc.

## Mẫu quyết định mới

**DEC-14 — Tích hợp INV-01 (07/11/2026, PROPOSED cho review liên service):**
Inventory xác minh token qua Identity `GET /api/v1/users/me` và kiểm tra ADMIN/ACTIVE,
không tin header danh tính do client truyền. Catalog lookup dùng service credential
riêng theo [contract nội bộ](../contracts/catalog-internal.openapi.yaml).
Thêm operation type INITIALIZE để đáp ứng Idempotency-Key của API khởi tạo, giữ
7 bảng hiện tại và thêm revision thay CHECK thay vì sửa migration cũ. Chủ Identity,
Catalog và Order cần review phần giao tiếp liên quan; chưa xác nhận tích hợp thật.
Xem [triển khai và kiểm thử INV-01](../development/INV-01.md).

## Quyết định Identity cần review liên service

### DEC-15 — Gateway forward route Identity, hỗ trợ Cookie, Redirect và HTML

- **Ngày:** 21/11/2026
- **Người đề xuất:** Identity
- **Người duyệt:** Chưa có
- **Trạng thái:** PROPOSED

#### Bối cảnh và vấn đề

Gateway chưa có `identity_base_url` và chưa có route Identity.

Hàm `forward()` trong `apps/api-gateway/src/commerce_gateway/inventory.py` hiện tại:
- Chỉ chuyển tiếp các header `Authorization`, `Idempotency-Key`, `Content-Type` và `X-Request-Id`.
- Chỉ trả về response body dạng JSON.
- Chỉ cho phép các HTTP status: `{200, 201, 400, 401, 403, 404, 409, 429, 503}`.

Không thể sử dụng nguyên trạng hàm này cho Identity vì luồng đăng nhập cần hỗ trợ Cookie, HTTP 204, Redirect và HTML.

Ngoài ra, Gateway hiện chưa có test.

#### Quyết định

Thêm route Identity vào Gateway, do chủ Identity triển khai.

**Chiều request vào Identity:**
- Chuyển tiếp thêm các header `Cookie`, `Origin`, `Referer`, `User-Agent`.

**Chiều response từ Identity:**
- Chuyển tiếp `Set-Cookie` (có thể có nhiều cookie).
- Chuyển tiếp `Cache-Control`, `Content-Type`, `Referrer-Policy` (trang callback của DEC-18 cần `no-store` và HTML).
- Hỗ trợ HTTP 204.
- Hỗ trợ HTTP 302 kèm header `Location`.
- Hỗ trợ response body dạng HTML.

Gateway không tin tưởng các header danh tính do client gửi lên.

#### Lý do và phương án đã cân nhắc

Browser chỉ nhìn thấy một origin thông qua Next rewrite:

`/api/v1/:path*` → Gateway.

Không tái sử dụng hàm `forward()` hiện tại vì thiếu các khả năng cần thiết cho Identity.

Thay vào đó, tạo router và hàm forward riêng cho Identity để không làm thay đổi hành vi của route Inventory.

#### Hệ quả / công việc phát sinh

Gateway là thành phần dùng chung nên chủ Inventory, Catalog và các service khác cần review thay đổi này.

Các công việc cần thực hiện:
- Bổ sung `identity_base_url` trong `settings.py`, sử dụng cùng validator origin như Catalog và Inventory.
- Khởi tạo HTTP client trong lifespan của `main.py`.
- Tạo router Identity mới.
- Viết test mới cho Gateway.

Không sửa route Inventory.

Gateway không lưu trữ trạng thái đăng nhập.

#### Tài liệu, contract và test cần đổi

- `MO-TA-HE-THONG.md`: cập nhật bảng route.
- `HTTP-API.md`: cập nhật mô tả API.
- Test Gateway:
  - Chuyển tiếp Cookie.
  - Chuyển tiếp User-Agent.
  - Chuyển tiếp Set-Cookie, bao gồm nhiều cookie.
  - Chuyển tiếp Cache-Control, Content-Type, Referrer-Policy.
  - Hỗ trợ HTTP 204.
  - Hỗ trợ HTTP 302 và Location.
  - Hỗ trợ response HTML.
  - Đảm bảo không rò rỉ header danh tính.

---

### DEC-16 — Refresh Cookie: HttpOnly, SameSite=Lax, Path `/api/v1/auth`

- **Ngày:** 21/11/2026
- **Người đề xuất:** Identity
- **Người duyệt:** Chưa có
- **Trạng thái:** PROPOSED

#### Bối cảnh và vấn đề

Refresh Token phải nằm ngoài phạm vi truy cập của JavaScript.

Access Token chỉ được lưu trong bộ nhớ frontend.

Cookie này đi qua Gateway nên ảnh hưởng đến cơ chế chuyển tiếp request/response dùng chung.

#### Quyết định

Refresh Token được lưu trong cookie với cấu hình:

- **Tên cookie:** `refreshToken` (theo `openapi.yaml`).
- **HttpOnly:** `true`.
- **SameSite:** `Lax`.
- **Path:** `/api/v1/auth`.
- **Secure:** Bật khi chạy HTTPS.

#### Lý do và phương án đã cân nhắc

- HttpOnly giúp giảm rủi ro XSS đọc được Refresh Token.
- Path hẹp giúp giảm phạm vi request gửi kèm cookie.
- SameSite=Lax là mức cân bằng cho MVP, kết hợp kiểm tra Origin/Referer (DEC-17). Chưa kiểm chứng việc Strict có chạy được với luồng popup Google (DEC-18).

#### Hệ quả / công việc phát sinh

Gateway phải chuyển tiếp:
- `Cookie` ở chiều request.
- `Set-Cookie` ở chiều response.

Nội dung này phụ thuộc DEC-15.

Các service khác không đọc cookie này.

#### Tài liệu, contract và test cần đổi

- `openapi.yaml`: cập nhật `refreshCookie`.
- `HTTP-API.md`: cập nhật cấu hình cookie.
- Test cookie:
  - Kiểm tra các thuộc tính cookie.
  - Kiểm tra Path.
  - Kiểm tra cookie bị xóa khi logout.

---

### DEC-17 — Endpoint sử dụng Cookie phải kiểm tra Origin/Referer

- **Ngày:** 21/11/2026
- **Người đề xuất:** Identity
- **Người duyệt:** Chưa có
- **Trạng thái:** PROPOSED

#### Bối cảnh và vấn đề

Các endpoint sử dụng cookie có nguy cơ bị tấn công CSRF.

Mục G của `MO-TA-HE-THONG.md` yêu cầu kiểm tra Origin.

#### Quyết định

Các endpoint dựa vào cookie, chẳng hạn:
- `/auth/refresh`
- `/auth/logout`

Phải kiểm tra nguồn gốc request theo thứ tự:

1. Kiểm tra header `Origin`.
2. Nếu thiếu `Origin`, sử dụng `Referer`.
3. Đối chiếu với danh sách origin đáng tin cậy.

Danh sách endpoint chính xác sẽ được chốt trong quá trình thiết kế API.

#### Lý do và phương án đã cân nhắc

Đây là cơ chế bổ sung cho SameSite=Lax nhằm giảm nguy cơ CSRF.

Trong MVP, chưa cần triển khai CSRF token riêng.

#### Hệ quả / công việc phát sinh

- Gateway phải chuyển tiếp `Origin` và `Referer` theo DEC-15.
- Cần cấu hình danh sách origin đáng tin cậy.
- Tên biến cấu hình hiện chưa được chốt.

#### Tài liệu, contract và test cần đổi

- `HTTP-API.md`: cập nhật yêu cầu kiểm tra Origin/Referer.
- Test:
  - Origin không nằm trong danh sách tin cậy.
  - Thiếu cả Origin và Referer.
  - Referer hợp lệ khi thiếu Origin.

---

### DEC-18 — Đăng nhập Google bằng Popup, Backend Identity điều khiển Callback

- **Ngày:** 21/11/2026
- **Người đề xuất:** Identity
- **Người duyệt:** Chưa có
- **Trạng thái:** PROPOSED

#### Bối cảnh và vấn đề

Backend cần giữ các giá trị `state`, `nonce`, `code_verifier` giữa thời điểm chuyển hướng sang Google và thời điểm callback quay trở lại.

MVP không sử dụng Redis.

Luồng đăng nhập này đi qua Next rewrite và Gateway nên phụ thuộc vào DEC-15.

#### Quyết định

Đăng nhập Google được thực hiện trong popup.

Backend Identity điều khiển cả hai bước:
- Khởi tạo đăng nhập (start).
- Xử lý callback.

Các giá trị `state`, `nonce`, `code_verifier` được lưu trong cookie ngắn hạn, có mã hóa và xác thực tính toàn vẹn.

#### Lý do và phương án đã cân nhắc

Không cần triển khai kho lưu trữ phiên phía server.

Phương án lưu trạng thái phía server được hoãn do cần bổ sung hạ tầng.

#### Hệ quả / công việc phát sinh

Các nội dung dưới đây mới là đề xuất chi tiết, chưa được chốt:

**1. Redirect URI đề xuất**

`http://localhost:3100/api/v1/auth/google/callback`

**2. Cookie lưu trạng thái OAuth**

- Path: `/api/v1/auth/google`.
- TTL: Vài phút.
- SameSite: Lax.
- Nội dung: `state`, `nonce`, `code_verifier`.
- Cần chốt tên cookie, phương thức mã hóa và secret.

**3. Luồng callback**

1. Google redirect về callback của Identity.
2. Identity xác thực callback và xử lý đăng nhập.
3. Identity tạo Refresh Cookie theo DEC-16.
4. Identity trả về một trang HTML nhỏ sử dụng `postMessage` để thông báo kết quả cho cửa sổ mở popup.
5. Frontend kiểm tra origin của message.
6. Frontend gọi `POST /auth/refresh` để lấy Access Token.
7. Access Token không truyền qua URL.

**4. Rủi ro cần kiểm chứng**

COOP có thể làm mất `window.opener`.

Cần kiểm tra và chuẩn bị phương án dự phòng, ví dụ `BroadcastChannel`.

Cần có test cho:
- Popup bị trình duyệt chặn.
- Mất `window.opener`.
- Cookie hết hạn.
- Callback không hợp lệ.

**5. Các nội dung chưa chốt**

- Path endpoint Google start.
- Tên cookie OAuth.
- Phương thức mã hóa và xác thực.
- Secret sử dụng để mã hóa cookie.
- Phương án dự phòng khi không sử dụng được `window.opener`.

#### Tài liệu, contract và test cần đổi

- `openapi.yaml`.
- `HTTP-API.md`.
- `THIET-KE-GIAO-DIEN.md`.
- `KE-HOACH-KIEM-THU.md`.

Phần đi qua Gateway cần review theo DEC-15; chưa xác nhận tích hợp thật (chưa chạy thử popup và cookie qua Gateway).

Xem [quyết định phía Identity (IDN-02)](NHAT-KY-QUYET-DINH-IDENTITY.md).

---

### DEC-19 — Bootstrap ADMIN bằng One-off CLI

- **Ngày:** 21/11/2026
- **Người đề xuất:** Identity
- **Người duyệt:** Chưa có
- **Trạng thái:** PROPOSED

#### Bối cảnh và vấn đề

Hệ thống không cho phép đăng ký tài khoản ADMIN công khai.

Theo `DAC-TA-NGHIEP-VU.md`, tài khoản ADMIN được cấp sẵn.

Tuy nhiên, Inventory, Order và các service khác cần có tài khoản ADMIN để kiểm thử.

#### Quyết định

Tạo tài khoản ADMIN đầu tiên bằng một lệnh CLI chạy một lần (one-off CLI).

Không triển khai API công khai để tạo ADMIN.

#### Lý do và phương án đã cân nhắc

Tránh tạo ra endpoint có thể bị lạm dụng để cấp quyền ADMIN trái phép.

#### Hệ quả / công việc phát sinh

Người kiểm thử các service khác cần biết cách tạo và sử dụng tài khoản ADMIN.

Các nội dung chưa chốt:
- Cách nhập mật khẩu.
- Tính idempotent của lệnh CLI.
- Vị trí đặt lệnh trong source code.
- Cách hướng dẫn người kiểm thử sử dụng.

#### Tài liệu, contract và test cần đổi

- Các tài liệu `HUONG-DAN-*.md`.
- `DAC-TA-NGHIEP-VU.md`: xác nhận quy định ADMIN được cấp sẵn.
- Test CLI.
---


```text
DEC-xx — Tên
Ngày / người đề xuất / người duyệt:
Trạng thái: PROPOSED / ACCEPTED / SUPERSEDED
Bối cảnh và vấn đề:
Quyết định:
Lý do và phương án đã cân nhắc:
Hệ quả / công việc phát sinh:
Tài liệu, contract và test cần đổi:
Thay thế quyết định nào (nếu có):
```
