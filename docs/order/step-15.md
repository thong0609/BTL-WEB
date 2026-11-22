# Step 15 — Giao diện đặt và xử lý đơn

Ngày thực hiện: **15/11/2026**. Phụ trách Order: **Mạnh**.

**Đã có giao diện phía Order**, gọi API thật qua Gateway khi các service sẵn sàng:

| Trang | Chức năng |
| --- | --- |
| `/checkout` | Đọc giỏ hàng, báo giá, nhập người nhận, chọn COD/mô phỏng, đặt đơn |
| `/orders` | Khách xem đơn mình; lọc trạng thái, chuyển trang |
| `/orders/{id}` | Xem giá/tên đã lưu, lịch sử, theo dõi tiến trình, hủy khi được phép |
| `/admin/orders` | Admin tìm mã đơn, lọc trạng thái, chuyển trang |
| `/admin/orders/{id}` | Xác nhận, hủy, bàn giao, hoàn thành, ghi nhận giao lỗi |

- Nút thao tác dựa vào `allowedActions` của backend; backend vẫn kiểm tra quyền và trạng thái.
- Đơn đang xử lý tự tải lại khoảng 5 giây khi tab hiển thị. HTTP 202 chỉ báo đã nhận yêu cầu.
- COD phải tích cả đã giao và đã thu tiền. Đơn trả trước chỉ cần xác nhận giao hàng.
- Mất kết nối giữ nguyên nội dung và Idempotency-Key trong bộ nhớ phiên của tab, kể cả reload. Không tự gửi lại hoặc cho sửa một yêu cầu còn chưa rõ kết quả.
- PRICE_CHANGED hiển thị giá mới; chỉ tạo yêu cầu mới khi khách bấm xác nhận lại.
- Tiền giữ dạng string, hiển thị bằng BigInt; dữ liệu API được kiểm tra trước khi hiển thị. Không đọc lại giá Catalog để vẽ đơn cũ.

**Đã kiểm tra:** 16 test frontend và 9 ca Chromium; Next → Gateway → Order chạy HTTP thật kiểm chứng ranh giới auth 401/503. Giao diện test dùng response mẫu; không phải demo xuyên các service thật.

**Còn đợi nhóm:** Identity + routing auth Gateway + bộ xác minh token của Order; Catalog/giỏ hàng; Inventory/Payment thật. Form đăng nhập hiện gọi contract `/auth/login`, `/auth/refresh`, `/auth/logout`; chưa có endpoint Identity/routing tương ứng trong repo, nên chưa thể mua hàng thật. Không có tài khoản giả hoặc nút bỏ qua đăng nhập trong app.

Đọc [bàn giao frontend](frontend-handoff.md) để ghép giỏ hàng/auth và xem ví dụ API; [kết quả kiểm thử](test-results.md) để biết phạm vi đã chứng minh.
