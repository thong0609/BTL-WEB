# Kế hoạch kiểm thử và nghiệm thu

Đây là kế hoạch, **chưa có ca nào được thực thi hoặc kết luận pass**. Mã AT dùng chung cho use case và task. Các mã MVP-xx trong tài liệu hệ thống là tiêu chí tổng quát; AT dưới đây chi tiết hóa, không thay đổi ý nghĩa.

## 1. Tầng kiểm thử

- Unit: tính tiền, transition, điều kiện hủy/thu/hoàn, validation; không mock toàn bộ rồi coi như integration.
- Integration: PostgreSQL thật cho transaction/cạnh tranh; RabbitMQ thật cho outbox/inbox/ack và recovery, môi trường test riêng.
- Contract: payload producer tương thích consumer, OpenAPI request/response và schema message.
- E2E: khách mua, ADMIN xử lý, khách tra cứu/hủy qua trình duyệt.
- Fault/concurrency: dừng đúng điểm, gửi message trùng/cũ và tranh tồn; kiểm tra cả trạng thái DB cuối, không chỉ mã HTTP.

## 2. Dữ liệu mẫu đề xuất

| Fixture | Thiết lập |
| --- | --- |
| CUSTOMER_A, CUSTOMER_B | Hai tài khoản ACTIVE khác nhau |
| ADMIN_A | Quản trị seed riêng; secret không commit |
| USER_DISABLED | Không được login/refresh |
| PROD_MOUSE | ACTIVE, 200.000 VND, tồn thực tế 10, giữ 0 |
| PROD_KEYBOARD | ACTIVE, 500.000 VND, tồn 5 |
| PROD_LAST | ACTIVE, 100.000 VND, tồn 1 |
| PROD_ZERO | ACTIVE, tồn 0 |
| PROD_DRAFT / PROD_STOPPED | Không mua mới được |
| Phí ship demo | 30.000 VND, chỉ là fixture test |
| Scenario Payment | SUCCESS, FAILURE, DELAYED_SUCCESS, DELAYED_FAILURE |
| Scenario Refund | SUCCESS, DELAYED_SUCCESS, FAIL_UNTIL_RETRY |

Reset dữ liệu giữa test độc lập. Test song song dùng đơn/SKU/key riêng. Không chạy seed/reset phá dữ liệu demo hoặc dữ liệu thật.

## 3. Ma trận ca kiểm thử

| Mã | Thao tác / tiền điều kiện | Kết quả cần xác minh |
| --- | --- | --- |
| AT-01 | Register hợp lệ, email trùng/chữ hoa, input sai | CUSTOMER duy nhất, mật khẩu hash, lỗi field đúng |
| AT-02 | Login/refresh/logout, reuse token, DISABLED | Quyền đúng, rotate/revoke family, cookie xóa; ghi nhận giới hạn access token còn hạn |
| AT-03 | Browse/filter/page/chi tiết DRAFT | Chỉ ACTIVE; lọc đúng, rỗng rõ, không lộ sản phẩm nội bộ |
| AT-04 | Thêm/sửa/xóa giỏ, login, submit chậm rồi thêm món khác | Giỏ giữ qua login, không giữ tồn, không xóa nhầm dòng mới |
| AT-05 | Đặt COD 2 chuột | Tiền 400000 + 30000; giữ 2; Payment AWAITING_COLLECTION; đơn chờ xác nhận |
| AT-06 | Đặt mô phỏng success/fail/delay | Success tiếp nhận; fail giải phóng rồi hủy; delay vẫn processing, chưa thu lại |
| AT-07 | Khách hủy COD khi chờ | Release và cancel COD xong mới CANCELLED |
| AT-08 | Khách hủy mô phỏng đã trả | Refund đủ 430000, giữ về 0, kết thúc hủy |
| AT-09 | Refund lỗi rồi thử lại, message lặp | CANCELLING/REFUND_PENDING khi lỗi; chỉ một refund thành công |
| AT-10 | A xem đơn B, ADMIN xem, list có processing/rejected | Không lộ đơn B; ADMIN đúng quyền; có dấu vết yêu cầu chưa tiếp nhận |
| AT-11 | CRUD danh mục/hàng/ảnh; giá đổi; SKU trùng | Validate, chặn file sai, ngừng bán không mất snapshot cũ |
| AT-12 | Tồn 10 giữ 3, điều chỉnh xuống 2; adjustment lặp | Từ chối âm khả năng bán; không cộng tồn thêm lần hai |
| AT-13 | Confirm/dispatch lặp | Một commit; tồn và giữ giảm đúng; SHIPPING sau event |
| AT-14 | Complete COD lặp, complete mô phỏng | Thu COD một lần; mô phỏng không thu lại; đã giao và paid mới completed |
| AT-15 | Giao thất bại | Cờ ngoại lệ, chưa complete, không tự hoàn tồn |
| AT-16 | 20 yêu cầu mua PROD_LAST mỗi yêu cầu 1 | Một reservation thành công; available không âm; không gọi Payment cho đơn thiếu hàng |
| AT-17 | Hai dòng, một hết; các command release/commit trùng | Không giữ một phần; không làm counters lệch |
| AT-18 | Cùng key/payload song song; key cũ payload khác | Một orderId, một snapshot; khác hash trả 409 |
| AT-19 | Mất HTTP sau commit; tắt broker rồi bật | Replay cùng key lấy được đơn; outbox còn việc rồi gửi lại |
| AT-20 | Payment commit success rồi chết trước event | Recovery publish kết quả, một lần thu; không tự release do timeout |
| AT-21 | Cancel cạnh tranh confirm/dispatch | Một transition hợp lệ; không RELEASED và COMMITTED cùng reservation |
| AT-22 | Event payment/refund cũ, messageId mới cùng operationId | Không đảo trạng thái, thu/hoàn lần hai; payload khác bị từ chối |
| AT-23 | Giá/phí đổi giữa quote và submit | 409 yêu cầu xác nhận mới; không tạo đơn giá khách chưa chấp nhận |
| AT-24 | Message lỗi schema/version, poison message | Retry phù hợp rồi DLQ; cảnh báo, không báo nghiệp vụ xong |
| AT-25 | Restart Order/Inventory, worker claim hết lease | Phục hồi từ workflow/outbox; không mất việc hoặc làm lại tác dụng |
| AT-26 | Backup DB/ảnh rồi restore môi trường riêng | Đơn, payment, tồn, ảnh và các công việc pending có thể đối chiếu/tiếp tục |

## 4. Kiểm tra bất biến sau các test lỗi

`0 <= reserved <= on_hand`; tổng reservation RESERVED khớp reserved counter; COMMITTED không bị RELEASED sau đó; một payment/order; một refund/payment trong MVP; đơn CANCELLED không còn hàng đang giữ và không còn nghĩa vụ tiền chưa xử lý. Không có Order COMPLETED với Payment chưa SUCCEEDED. Snapshot tiền bằng tổng dòng + phí.

Các kiểm tra trên cần chạy trong trạng thái đã ổn định hoặc đối chiếu tiến trình còn chạy; không kết luận sai chỉ vì đọc giữa hai transaction ở hai service.

## 5. Ghi bằng chứng và điều kiện release

Mỗi lần chạy ghi mã test, commit, cấu hình môi trường, fixture, thao tác, expected/actual, pass/fail, log orderId/paymentId/operationId và issue nếu lỗi. Có thể dùng bảng dưới trong báo cáo thực thi riêng:

| Test | Commit / môi trường | Actual | Kết quả | Bằng chứng / issue |
| --- | --- | --- | --- | --- |
| AT-xx | Chưa chạy | — | NOT RUN | — |

Release demo cần các luồng cốt lõi pass và không còn lỗi mất dữ liệu, vượt tồn, thu/hoàn trùng hoặc lộ quyền. Lỗi nhỏ giao diện có thể được ghi giới hạn, không tự đổi test fail thành pass. Load test chỉ báo thông số đã đo trên cấu hình cụ thể, không cam kết microservices nhanh hơn monolith.
