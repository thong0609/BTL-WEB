# Đặc tả nghiệp vụ MVP

Phiên bản 0.1 — 24/10/2026. Tham chiếu [sản phẩm](MO-TA-WEBSITE.md), [workflow](../design/THIET-KE-LUONG-XU-LY.md), [API](../contracts/HTTP-API.md). Đây là đề xuất chi tiết hóa phạm vi đã thống nhất.

## 1. Vai trò và quy tắc chung

Khách chưa đăng nhập được xem hàng và dùng giỏ trên cùng trình duyệt. CUSTOMER đặt và xem đơn của mình. ADMIN quản lý sản phẩm/tồn/đơn; tài khoản ADMIN cấp sẵn, không có đăng ký công khai.

| Mã | Quy tắc |
| --- | --- |
| BR-01 | Giá do Catalog cung cấp; Order tính tổng. Không dùng tổng tiền từ client |
| BR-02 | Chỉ ACTIVE được đặt. Giỏ không giữ tồn; giữ tất cả dòng hoặc không dòng nào |
| BR-03 | Snapshot SKU, tên, giá, địa chỉ và phí tại lần xác nhận đặt; đơn cũ không đổi theo Catalog |
| BR-04 | Một đơn có một payment record. Không thử thanh toán FAILED lại trên cùng đơn trong MVP |
| BR-05 | Khách chỉ hủy AWAITING_CONFIRMATION; ADMIN hủy thêm PREPARING, luôn có lý do |
| BR-06 | Không hủy khi thanh toán đang PENDING. Trạng thái CANCELLING phải chặn xác nhận/giao |
| BR-07 | Chỉ CANCELLED sau giải phóng hàng và hủy nghĩa vụ COD/hoàn tiền nếu cần |
| BR-08 | Timeout chưa chứng minh thất bại. Tra cứu cùng orderId/paymentId, không tạo lần thu mới |
| BR-09 | available = on_hand − reserved; giữ, giải phóng, xuất và thu/hoàn chỉ một lần |
| BR-10 | Đã giao + Payment xác nhận SUCCEEDED mới COMPLETED. Thanh toán không có nghĩa đã giao |
| BR-11 | Một kho, VND, phí ship cố định cấu hình server. Hoàn mô phỏng toàn bộ gồm phí ship trước giao |
| BR-12 | Giao thất bại đánh dấu cần xử lý; không tự hoàn tồn trước khi kiểm nhận hàng thực tế |

Đầu vào đề xuất: tên 1–150 ký tự sau trim, điện thoại 8–15 chữ số và dấu `+` đầu nếu có, địa chỉ 10–1.000 ký tự, ghi chú/lý do tối đa 1.000. Mật khẩu 10–128 ký tự. Tối đa 50 SKU/đơn, số lượng mỗi SKU 1–999; đây là giới hạn sản phẩm để nhóm review, không cam kết hiệu năng. Chặn payload trùng SKU thay vì tự gộp âm thầm khi checkout.

## 2. Danh mục use case

| Mã | Tên | Vai trò | Màn hình | Test chính |
| --- | --- | --- | --- | --- |
| UC-ID-01 | Đăng ký | Khách | UI-04 | AT-01 |
| UC-ID-02 | Đăng nhập/refresh/logout | Khách, ADMIN | UI-04 | AT-02 |
| UC-CAT-01 | Tìm/xem hàng | Mọi người | UI-01, UI-02 | AT-03 |
| UC-CART-01 | Quản lý giỏ | Khách | UI-03 | AT-04 |
| UC-ORD-01 | Đặt COD | CUSTOMER | UI-05, UI-06 | AT-05 |
| UC-ORD-02 | Đặt thanh toán mô phỏng | CUSTOMER | UI-05, UI-06 | AT-06 |
| UC-ORD-03 | Hủy đơn | Chủ đơn, ADMIN | UI-08, UI-A05 | AT-07–09 |
| UC-ORD-04 | Tra cứu đơn | Chủ đơn, ADMIN | UI-07, UI-08 | AT-10 |
| UC-ADM-01 | Quản lý danh mục/sản phẩm | ADMIN | UI-A02, UI-A03 | AT-11 |
| UC-INV-01 | Khởi tạo/nhập/điều chỉnh kho | ADMIN | UI-A04 | AT-12 |
| UC-ADM-02 | Xác nhận/bàn giao | ADMIN | UI-A05 | AT-13 |
| UC-ADM-03 | Hoàn thành/thu COD | ADMIN | UI-A05 | AT-14 |
| UC-ADM-04 | Ghi ngoại lệ giao hàng | ADMIN | UI-A05 | AT-15 |

## 3. Đặc tả từng use case

### UC-ID-01 — Đăng ký

**Điều kiện:** chưa có email tương ứng. **Đầu vào:** họ tên, email, mật khẩu. Chuẩn hóa email, kiểm tra định dạng và độ dài, tạo CUSTOMER ACTIVE, băm mật khẩu. **Kết quả:** tài khoản tạo thành công, chuyển đăng nhập; không tự tạo ADMIN. Email trùng trả xung đột, lỗi validation chỉ rõ field; không lưu bản ghi dang dở hoặc mật khẩu trong log. Nghiệm thu AT-01.

### UC-ID-02 — Đăng nhập và phiên

Nhập email/mật khẩu → kiểm tra ACTIVE → cấp access token và refresh cookie. Lỗi đăng nhập có thông báo chung, không tiết lộ mật khẩu/email nào sai. Frontend refresh một lần khi access token hết hạn; nhiều request đồng thời dùng chung một lần refresh. Token cũ được rotate và phát hiện tái sử dụng theo family. Logout thu hồi refresh session và xóa cookie; access token đã cấp còn hiệu lực đến hạn nếu chưa bổ sung thu hồi. DISABLED không được đăng nhập/refresh. AT-02.

### UC-CAT-01 — Tìm và xem hàng

Xem danh sách ACTIVE, tìm tên, lọc danh mục/giá, sắp xếp, phân trang → mở chi tiết. Không kết quả hiển thị rỗng; không lấy được tồn hiển thị chưa xác định, không giả định còn hàng. Giá/tồn có thể thay đổi trước checkout. Khách không đọc sản phẩm DRAFT/ngừng bán qua API công khai. AT-03.

### UC-CART-01 — Giỏ hàng

Chọn số lượng hợp lệ → thêm SKU; thêm lại cộng số lượng trong giới hạn → sửa/xóa → tính tiền tham khảo. Lưu cùng trình duyệt, không đồng bộ thiết bị, giữ qua đăng nhập. Giỏ không chứa địa chỉ hoặc dữ liệu thanh toán nhạy cảm. Chỉ xóa các dòng của snapshot checkout khi đơn tiếp nhận; mặt hàng được thêm mới trong lúc chờ không bị xóa theo. Tạo đơn bị từ chối giữ nguyên giỏ. AT-04.

### UC-ORD-01 — Đặt COD

**Trước:** CUSTOMER, giỏ hợp lệ, đủ thông tin nhận hàng. **Luồng:**

1. Tải báo giá checkout gồm giá hiện tại và phí ship; khách đọc và xác nhận.
2. Gửi giỏ, giá đã xác nhận, phí đã xác nhận, địa chỉ, COD và Idempotency-Key.
3. Kiểm tra giá lại; khác giá/phí thì trả PRICE_CHANGED, chưa tiếp nhận và yêu cầu xác nhận lại với key mới.
4. Tạo PROCESSING cùng mã tra cứu; giữ đủ hàng; tạo nghĩa vụ COD trong Payment.
5. Sau StockReserved và PaymentInitialized, chuyển AWAITING_CONFIRMATION.

**Ngoại lệ:** thiếu hàng → REJECTED, không giữ sót; dependency đọc giá lỗi trước tiếp nhận → báo lỗi có thể thử lại; đã tiếp nhận mà chưa rõ kết quả → hiển thị đang xử lý và tra cứu, gửi lại cùng key. Không tự tạo key mới khi timeout. AT-05, AT-16–19.

### UC-ORD-02 — Đặt thanh toán mô phỏng

Giống UC-ORD-01 đến giữ hàng, sau đó ProcessPayment. SUCCESS → AWAITING_CONFIRMATION. FAILURE xác định → giải phóng hàng → CANCELLED với lý do PAYMENT_FAILED. DELAYED vẫn PROCESSING/PENDING, polling và đối chiếu; không tự giải phóng hàng. Không đủ hàng thì không gọi Payment. Chế độ demo do ADMIN cấu hình; khách không được truyền kết quả thành công vào checkout. Không nhập thẻ thật. AT-06, AT-18–20.

### UC-ORD-03 — Hủy đơn

**Trước:** chủ đơn ở AWAITING_CONFIRMATION hoặc ADMIN ở trạng thái đó/PREPARING; lý do không rỗng. Order khóa chuyển trạng thái → CANCELLING → yêu cầu giải phóng reservation và CancelCodPayment hoặc RefundPayment. Chỉ CANCELLED khi hai nhánh hoàn tất. Refund lỗi giữ đang hủy, cờ cần xử lý; tiếp tục cùng operationId. Đơn đã hủy trả trạng thái hiện tại, không bù trừ lần nữa. Nếu xác nhận/giao thắng cạnh tranh trước, trả ORDER_STATE_CONFLICT và cập nhật giao diện. AT-07–09, AT-21.

### UC-ORD-04 — Tra cứu đơn

Khách xem danh sách chỉ của mình, lọc trạng thái, mở snapshot và lịch sử; ADMIN có danh sách chung. Cả PROCESSING/REJECTED đều có thể tra cứu để không mất dấu yêu cầu. Truy cập đơn người khác trả 404 để không tiết lộ tồn tại đơn. Không trả địa chỉ khách khác, token, payload message hoặc lỗi nội bộ. AT-10.

### UC-ADM-01 — Danh mục và sản phẩm

ADMIN thêm danh mục, tạo DRAFT với SKU duy nhất, sửa tên/giá/ảnh, ACTIVE/ngừng bán. Giá không âm, VND, ảnh kiểm tra trước lưu. SKU và slug duy nhất; không đổi SKU sau tạo trong MVP. Ẩn danh mục chỉ ẩn điều hướng, không tự ngừng bán sản phẩm. Không xóa lịch sử đã mua. Tạo sản phẩm chưa tạo hàng trong kho: tiếp tục UC-INV-01; thiếu stock_item coi có thể bán 0. AT-11.

### UC-INV-01 — Quản lý kho

ADMIN chọn sản phẩm Catalog hợp lệ → khởi tạo stock_item với tồn 0 → nhập/điều chỉnh bằng delta và lý do. Trước/ sau đều phải on_hand >= reserved >= 0. Lưu operationId, actor, movement và kết quả; gửi lại không cộng thêm. Hai chỉnh sửa cạnh tranh phải phát hiện version cũ. Không chỉnh số reserved trực tiếp. AT-12.

### UC-ADM-02 — Xác nhận và bàn giao

AWAITING_CONFIRMATION → xác nhận → PREPARING, không giữ lần nữa. Bàn giao: đặt workflow DISPATCH đang chạy, chặn hủy đồng thời, gửi CommitStock; chỉ SHIPPING sau StockCommitted. Gửi lại bàn giao không xuất thêm. Không được bàn giao khi chưa đủ điều kiện thanh toán (COD đã tạo hoặc mô phỏng SUCCEEDED). AT-13, AT-21.

### UC-ADM-03 — Hoàn thành

**Trước:** SHIPPING. Mô phỏng đã trả: ADMIN xác nhận giao thành công → COMPLETED. COD: phải xác nhận đã giao và đã thu đủ tiền → RecordCodCollection → CodCollected → COMPLETED. Chưa có event thì hiển thị đang hoàn tất; không tự sửa Payment DB. Gửi lặp chỉ thu một lần. AT-14.

### UC-ADM-04 — Ngoại lệ giao hàng

ADMIN ghi lý do giao không thành công/thiếu thông tin bằng note, đánh requires_attention. Giữ SHIPPING; không báo COMPLETED, không tự hoàn tiền/hoàn tồn. Quy trình nhận lại hàng và đổi trả sau giao ngoài MVP, phải hiển thị rõ giới hạn này trong demo. AT-15.

## 4. Giới hạn và điểm phải review

Đề xuất chi tiết mới: checkout quote không giữ giá/tồn; chỉ lần tạo đơn chốt snapshot. Ngưỡng số dòng/số lượng, độ dài đầu vào, giới hạn ảnh và thời gian cảnh báo tiến trình cần nhóm duyệt. Không thêm khách mua không tài khoản, sửa đơn sau đặt, giao một phần hoặc thanh toán lại cùng đơn vào MVP.
