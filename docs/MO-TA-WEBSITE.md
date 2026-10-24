# Mô tả sản phẩm: Website bán hàng cho một cửa hàng

Ngày lập: 24/10/2026  
Nhóm thực hiện: 5 thành viên  
Thời gian dự kiến: 8 tuần  
Trạng thái: Bản mô tả sản phẩm ban đầu để nhóm thảo luận và chốt phạm vi.

## 1. Tổng quan

Website giúp một cửa hàng giới thiệu sản phẩm, nhận đơn mua hàng và quản lý quá trình bán hàng. Khách hàng có thể tìm sản phẩm, thêm vào giỏ, đặt hàng và theo dõi đơn. Nhân viên quản lý danh mục, sản phẩm, tồn kho và xử lý đơn trên khu vực quản trị.

Đây là website của một cửa hàng duy nhất. Website không cho người dùng đăng ký mở shop, không có nhiều nhà bán hàng và không chia đơn theo shop như sàn thương mại điện tử.

Ngành hàng minh họa là phụ kiện máy tính: chuột, bàn phím, tai nghe và phụ kiện. Nhóm có thể đổi ngành hàng trước khi thiết kế dữ liệu và giao diện chi tiết.

Tài liệu này mô tả sản phẩm và nghiệp vụ, chưa lựa chọn công nghệ hoặc thiết kế kiến trúc triển khai.

## 2. Mục tiêu sản phẩm

- Khách tự tìm hiểu sản phẩm và đặt mua mà không cần nhắn tin cho cửa hàng.
- Khách biết đơn đã được tiếp nhận chưa và đang được xử lý đến đâu.
- Nhân viên có nơi tập trung để quản lý sản phẩm, lượng hàng và đơn mua.
- Hạn chế bán vượt lượng hàng có sẵn, sai tổng tiền hoặc xử lý trùng đơn.
- Hoàn thiện một quy trình mua bán có thể trình diễn từ đầu đến cuối trong phạm vi đồ án.

## 3. Người sử dụng và quyền hạn

| Vai trò | Hoạt động chính |
| --- | --- |
| Khách chưa đăng nhập | Xem, tìm kiếm và lọc sản phẩm; xem chi tiết; tạo giỏ hàng |
| Khách đã đăng nhập | Đặt hàng; xem danh sách và chi tiết đơn của mình; hủy đơn khi được phép |
| Nhân viên cửa hàng | Quản lý sản phẩm, danh mục, tồn kho; tiếp nhận và xử lý đơn |
| Chủ cửa hàng / quản trị viên | Có quyền của nhân viên; xem tổng quan hoạt động và quản lý quyền truy cập nội bộ |

Đề xuất cho bản đầu tiên: tài khoản nội bộ do quản trị viên cấp, không có đăng ký nhân viên công khai. Có thể dùng chung một vai trò quản trị trong MVP nếu nhóm cần giảm phạm vi.

Khách chỉ được xem và thao tác với đơn hàng của chính mình. Khách không được truy cập khu vực quản trị.

## 4. Phạm vi phiên bản đầu tiên

### 4.1. Chức năng bắt buộc

- Đăng ký, đăng nhập và đăng xuất cho khách hàng.
- Danh sách sản phẩm, tìm theo tên, lọc theo danh mục và khoảng giá.
- Chi tiết sản phẩm và tình trạng còn hàng.
- Giỏ hàng: thêm, sửa số lượng, xóa sản phẩm và xem tiền hàng dự kiến.
- Đặt hàng với thông tin người nhận và địa chỉ giao hàng.
- Xem kết quả đặt hàng, lịch sử đơn và chi tiết từng đơn.
- Hủy đơn khi đơn còn chờ xác nhận.
- Quản lý danh mục, sản phẩm và tồn kho.
- Xác nhận, chuẩn bị, cập nhật giao hàng và hoàn thành đơn.
- Tổng quan đơn mới, đơn cần xử lý và sản phẩm sắp hết hàng.

### 4.2. Giới hạn để phù hợp 8 tuần

- Một cửa hàng, một kho, một loại tiền là VND.
- Mỗi mặt hàng có một cấu hình bán cụ thể; ví dụ chuột màu đen và chuột màu trắng là hai mặt hàng riêng.
- Một đơn được giao toàn bộ, chưa hỗ trợ giao nhiều lần hoặc giao một phần.
- Phí giao hàng cố định theo cấu hình cửa hàng; hiển thị rõ trước khi xác nhận mua.
- Nhân viên cập nhật trạng thái giao hàng thủ công.
- MVP có COD và thanh toán mô phỏng qua Payment Service riêng. Đây là phạm vi đã chốt; không kết nối cổng thật hoặc dùng thẻ thật.
- Giỏ hàng không giữ hàng; chỉ đơn đã được hệ thống tiếp nhận mới giữ lượng hàng tương ứng.

### 4.3. Ngoài phạm vi

- Nhiều người bán, đăng ký gian hàng, hoa hồng và đối soát cho nhà bán hàng.
- Thanh toán thật, kết nối vận chuyển thật và theo dõi vị trí giao hàng.
- Voucher, tích điểm, flash sale, livestream, chat và gợi ý sản phẩm bằng AI.
- Đánh giá sản phẩm, yêu thích và so sánh sản phẩm.
- Đổi trả sau khi nhận, bảo hành và hoàn tiền thật. Hoàn tiền mô phỏng khi hủy trước giao nằm trong MVP.
- Nhiều kho, nhiều tiền tệ, ứng dụng di động riêng.

## 5. Hành trình khách hàng

Ví dụ: An muốn mua một chuột và một bàn phím.

1. An mở website, tìm chuột và lọc theo khoảng giá.
2. An xem hình ảnh, mô tả, thông số và giá của sản phẩm.
3. An thêm một chuột và một bàn phím vào giỏ.
4. An kiểm tra số lượng và tiền hàng dự kiến.
5. An đăng nhập để tiếp tục đặt hàng; các sản phẩm trong giỏ vẫn được giữ lại.
6. An nhập tên người nhận, số điện thoại, địa chỉ và ghi chú nếu có.
7. Website hiển thị tiền hàng, phí giao hàng, tổng tiền và phương thức thanh toán.
8. An xác nhận đặt hàng. Website kiểm tra lại giá, tình trạng bán và tồn kho.
9. Nếu hợp lệ, website giữ hàng và xử lý phương thức thanh toán: tạo nghĩa vụ COD hoặc chờ thanh toán mô phỏng thành công, sau đó tiếp nhận đơn. Trong lúc chờ vẫn có mã đơn để tra cứu.
10. An vào mục Đơn hàng của tôi để theo dõi tiến độ.
11. Nếu đơn còn chờ xác nhận, An có thể yêu cầu hủy.
12. Sau khi giao thành công, đơn chuyển Hoàn thành; thanh toán COD được ghi nhận theo xác nhận thu tiền của cửa hàng.

Nếu giá hoặc lượng hàng đã thay đổi, website giải thích sản phẩm bị ảnh hưởng và yêu cầu An kiểm tra lại trước khi xác nhận tiếp. Không tự tăng tổng tiền rồi tạo đơn mà khách chưa đồng ý.

## 6. Chi tiết màn hình dành cho khách hàng

### 6.1. Trang chủ và danh sách sản phẩm

**Mục đích:** giúp khách nhanh chóng tìm thấy hàng muốn mua.

Nội dung:

- Tên, logo và thông tin nhận diện cửa hàng.
- Thanh tìm kiếm theo tên sản phẩm.
- Danh mục và bộ lọc khoảng giá.
- Sắp xếp: mới nhất, giá tăng dần, giá giảm dần.
- Thẻ sản phẩm gồm hình, tên, giá và tình trạng còn/hết hàng.
- Liên kết đến giỏ hàng, tài khoản và đơn hàng.
- Thông tin liên hệ và chính sách mua hàng cơ bản ở cuối trang.

Trạng thái cần có: đang tải, không có sản phẩm, không có kết quả tìm kiếm và lỗi tải dữ liệu có nút thử lại. Có thể gộp trang chủ và danh sách thành một màn hình trong MVP.

### 6.2. Chi tiết sản phẩm

- Hình ảnh và tên sản phẩm.
- Giá hiện tại.
- Mô tả, thương hiệu nếu có và thông số cơ bản.
- Tình trạng còn hàng hoặc hết hàng.
- Chọn số lượng nguyên dương và thêm vào giỏ.
- Thông tin giao hàng và liên hệ cửa hàng.

Sản phẩm hết hàng không được thêm mới vào giỏ. Nếu sản phẩm đã có trong giỏ rồi mới hết hàng, khách được thông báo khi xem giỏ hoặc đặt hàng. Sản phẩm ngừng bán không được đặt mới.

### 6.3. Giỏ hàng

- Hiển thị hình, tên, đơn giá tham khảo, số lượng và thành tiền của từng mặt hàng.
- Cho phép tăng/giảm số lượng, xóa mặt hàng.
- Cộng số lượng khi thêm lại cùng một mặt hàng.
- Hiển thị tiền hàng dự kiến; phí giao hàng được xác nhận ở màn hình đặt hàng.
- Giỏ trống có nút quay lại mua sắm.
- Nút Tiến hành đặt hàng yêu cầu đăng nhập nếu khách chưa đăng nhập.

Giỏ hàng là danh sách dự định mua, không bảo đảm giá hoặc tồn kho cho đến khi đơn được tiếp nhận. Sau khi đơn được tạo thành công, các mặt hàng đã mua được xóa khỏi giỏ. Nếu tạo đơn thất bại, giỏ vẫn còn để khách sửa và thử lại.

### 6.4. Đăng ký và đăng nhập

- Đăng ký với họ tên, email và mật khẩu.
- Đăng nhập, đăng xuất và thông báo lỗi dễ hiểu.
- Không cho tạo nhiều tài khoản với cùng email.
- Sau khi đăng nhập từ giỏ hàng, khách được tiếp tục đặt hàng.

Khôi phục mật khẩu và xác minh email được xem là phần bổ sung, chưa bắt buộc cho bản demo đầu tiên.

### 6.5. Đặt hàng

Thông tin bắt buộc:

- Tên người nhận.
- Số điện thoại liên hệ.
- Địa chỉ đủ để giao hàng.
- Phương thức thanh toán: COD hoặc thanh toán mô phỏng.

Thông tin tùy chọn: ghi chú của khách.

Phần tổng kết hiển thị từng sản phẩm, số lượng, đơn giá, thành tiền, tổng tiền hàng, phí giao hàng và tổng thanh toán. Chỉ cho xác nhận khi thông tin hợp lệ và giỏ có hàng.

Khi đang gửi yêu cầu, hiển thị trạng thái Đang xử lý. Việc bấm nhiều lần hoặc thử lại cùng yêu cầu không được sinh thêm đơn ngoài ý muốn. Nếu chưa rõ kết quả, hướng dẫn khách kiểm tra Đơn hàng của tôi thay vì khẳng định đơn đã thất bại.

### 6.6. Kết quả đặt hàng

- Tiếp nhận thành công: mã đơn, thời điểm đặt, tổng tiền, trạng thái và nút xem chi tiết.
- Không đủ hàng hoặc sản phẩm ngừng bán: chỉ rõ mặt hàng và hướng dẫn chỉnh giỏ.
- Giá thay đổi: hiển thị giá mới và yêu cầu khách xác nhận lại.
- Chưa xác định được kết quả: hiển thị đang kiểm tra, cho phép tra cứu đơn.

### 6.7. Đơn hàng của tôi

- Danh sách đơn chỉ của khách đang đăng nhập.
- Mỗi đơn có mã, thời điểm, tổng tiền, trạng thái đơn và trạng thái thanh toán.
- Lọc theo trạng thái; mở xem chi tiết.
- Trạng thái chưa từng đặt hàng có liên kết mua sắm.

### 6.8. Chi tiết đơn hàng

- Mã đơn và thời điểm đặt.
- Các mặt hàng, số lượng, đơn giá tại thời điểm mua.
- Thông tin người nhận và địa chỉ đã xác nhận.
- Tiền hàng, phí giao hàng và tổng tiền.
- Trạng thái đơn, trạng thái thanh toán và các mốc xử lý.
- Nút hủy khi còn đủ điều kiện; hiển thị lý do nếu đơn đã hủy.

MVP không hỗ trợ sửa sản phẩm hoặc địa chỉ trực tiếp trên đơn đã đặt. Khi đơn còn chờ xác nhận, khách có thể hủy và đặt lại. Sau mốc này, hiển thị hướng dẫn liên hệ cửa hàng.

## 7. Chi tiết khu vực quản trị

### 7.1. Tổng quan

- Số đơn mới và số đơn cần chuẩn bị.
- Số đơn đang giao.
- Danh sách sản phẩm sắp hết hàng theo ngưỡng đã quy định.
- Có thể bổ sung tổng giá trị đơn hoàn thành theo khoảng thời gian; cần ghi rõ đây là giá trị bán hàng, không phải lợi nhuận.

### 7.2. Quản lý danh mục

- Xem, thêm, đổi tên và ẩn danh mục.
- Không xóa tùy tiện danh mục còn sản phẩm; yêu cầu chuyển sản phẩm hoặc ẩn danh mục.
- Ẩn danh mục khỏi điều hướng không tự động hủy đơn hoặc xóa lịch sử sản phẩm.

### 7.3. Quản lý sản phẩm

- Thêm sản phẩm với mã hàng, tên, danh mục, giá, mô tả, thông số và hình ảnh.
- Chỉnh sửa thông tin, đổi giá và chuyển trạng thái đang bán/ngừng bán.
- Tìm kiếm và lọc danh sách quản trị.
- Không xóa mất thông tin sản phẩm đã xuất hiện trong đơn hàng; ưu tiên ngừng bán.
- Đổi giá chỉ ảnh hưởng lượt mua mới, không thay đổi giá trong đơn đã tiếp nhận.

### 7.4. Quản lý tồn kho

Hiển thị ba lượng rõ ràng:

- **Tồn thực tế:** lượng hàng còn tại kho, gồm cả hàng đang dành cho đơn.
- **Đang giữ:** lượng dành cho các đơn đã tiếp nhận nhưng chưa bàn giao giao hàng.
- **Có thể bán:** tồn thực tế trừ lượng đang giữ.

Nhân viên nhập thêm hàng hoặc điều chỉnh tồn với lý do. Lưu lịch sử lượng tăng/giảm, thời gian và người thao tác. Không cho điều chỉnh khiến lượng có thể bán âm.

Ví dụ: có 10 chuột trong kho, 3 chuột đang giữ cho đơn thì chỉ còn 7 chuột có thể bán. Khi bàn giao 3 chuột cho giao hàng, tồn thực tế giảm còn 7 và lượng đang giữ giảm về 0.

### 7.5. Quản lý đơn hàng

- Xem danh sách, lọc trạng thái, tìm theo mã đơn hoặc thông tin khách.
- Mở chi tiết sản phẩm, người nhận, ghi chú và thanh toán.
- Xác nhận đơn, chuyển sang chuẩn bị, bàn giao giao hàng và hoàn thành.
- Hủy đơn trước khi giao theo quyền và quy tắc đã chốt, có lý do.
- Ghi lại người thao tác, thời gian và trạng thái trước/sau.

Nhân viên không được tùy ý sửa giá hoặc tổng tiền của đơn đã tiếp nhận.

## 8. Quy trình đơn hàng và thanh toán

### 8.1. Trạng thái đơn

| Trạng thái | Ý nghĩa | Thao tác tiếp theo |
| --- | --- | --- |
| Chờ xác nhận | Đã giữ đủ hàng; đã tạo COD hoặc thanh toán mô phỏng thành công | Nhân viên xác nhận hoặc hủy; khách có thể hủy |
| Đang chuẩn bị | Cửa hàng đã xác nhận và đang đóng gói | Nhân viên bàn giao giao hàng; có thể hủy trước khi giao kèm lý do |
| Đang giao | Hàng đã rời kho để giao cho khách | Nhân viên xác nhận hoàn thành |
| Hoàn thành | Khách đã nhận hàng | Xem lịch sử; không tự hủy |
| Đã hủy | Hàng đã giải phóng; thanh toán đã hủy hoặc hoàn mô phỏng nếu cần | Xem lý do và lịch sử |

Không cho chuyển ngược tùy tiện hoặc bỏ qua bước. Trường hợp giao thất bại và hàng quay về kho cần quy trình riêng; bản đầu tiên chưa tự động hóa, phải ghi nhận để cửa hàng xử lý và không được đánh dấu hoàn thành sai thực tế.

### 8.2. Thanh toán

MVP có hai phương thức do Payment Service quản lý:

- **COD:** chờ thu khi đặt; khi giao thành công và nhân viên xác nhận thu tiền, Payment ghi nhận Đã thanh toán. Hủy trước khi giao thì hủy nghĩa vụ thu.
- **Thanh toán mô phỏng:** sau khi giữ hàng, xử lý kết quả thành công, thất bại hoặc chậm. Thành công thì đơn chờ xác nhận; thất bại thì giải phóng hàng và hủy đơn với lý do rõ ràng. Chưa rõ kết quả thì tiếp tục hiển thị đang xử lý, không tự coi thất bại.

Khi hủy đơn đã thanh toán mô phỏng, website hiển thị Đang hoàn tiền cho đến khi xử lý xong. Đơn chỉ hoàn tất hủy khi đã giải phóng hàng và hoàn tiền mô phỏng. Không thu thập thông tin thẻ thật; luôn ghi rõ đây là thanh toán mô phỏng.

Trạng thái thanh toán: Chờ xử lý, Chờ thu COD, Đã thanh toán, Thất bại, Đang hoàn tiền, Đã hoàn tiền, Đã hủy. Khi đang xử lý hoặc hoàn tiền, khách có thể tra cứu và không được tạo thêm lần thanh toán cho cùng đơn. MVP chưa hỗ trợ thử lại thanh toán thất bại trên cùng đơn; sau khi đơn hủy xong, khách đặt đơn mới.

Trạng thái thanh toán độc lập với trạng thái đơn: một đơn đang chuẩn bị theo COD vẫn có thể chưa thanh toán.

## 9. Quy tắc nghiệp vụ bắt buộc

1. Số lượng mua là số nguyên dương; không nhận giá hoặc tổng tiền tùy ý do khách cung cấp.
2. Khi tiếp nhận đơn, kiểm tra lại sản phẩm đang bán, giá và lượng có thể bán.
3. Đơn nhiều mặt hàng phải được giữ đủ toàn bộ hoặc không giữ mặt hàng nào; MVP không tự tách đơn.
4. Nhiều khách đặt đồng thời không được làm bán vượt lượng hàng có thể bán.
5. Thêm vào giỏ không giữ hàng. Tiếp nhận đơn mới giữ hàng.
6. Hủy đơn giải phóng hàng đúng một lần. Hủy lặp không làm tăng tồn thêm.
7. Bàn giao giao hàng giảm tồn thực tế và kết thúc giữ hàng đúng một lần.
8. Một yêu cầu đặt hàng bị gửi lặp không được tạo nhiều đơn ngoài ý muốn.
9. Đơn lưu tên sản phẩm, đơn giá, số lượng, phí giao hàng và thông tin nhận hàng tại thời điểm đặt.
10. Thay đổi sản phẩm hoặc tài khoản về sau không sửa lịch sử đơn cũ.
11. Khách chỉ xem/hủy đơn thuộc mình và trong trạng thái được phép.
12. Nếu thao tác hủy và xác nhận xảy ra đồng thời, hệ thống chỉ chấp nhận kết quả hợp lệ theo trạng thái thực tế và thông báo rõ cho bên còn lại.
13. Trong MVP chưa tự động hết hạn đơn chờ xác nhận; nhân viên cần theo dõi và xử lý để tránh giữ hàng kéo dài.

## 10. Các tình huống cần thể hiện trên giao diện

| Tình huống | Cách website phản hồi |
| --- | --- |
| Không có kết quả tìm kiếm | Gợi ý bỏ bộ lọc hoặc đổi từ khóa |
| Sản phẩm trong giỏ hết hàng | Đánh dấu mặt hàng và yêu cầu chỉnh giỏ |
| Giá thay đổi trước khi đặt | Hiển thị giá mới và xin xác nhận lại |
| Thiếu thông tin giao hàng | Báo lỗi ngay tại trường cần sửa |
| Gửi đơn chậm hoặc mất phản hồi | Giữ trạng thái rõ ràng, cho kiểm tra đơn, không khuyến khích tạo lại mù quáng |
| Đơn vừa được nhân viên xác nhận nên không hủy được | Cập nhật trạng thái và giải thích quy tắc hủy |
| Khách mở đơn của người khác | Từ chối truy cập, không lộ thông tin đơn |
| Chức năng tạm không hoạt động | Thông báo dễ hiểu và có cách thử lại |

## 11. Danh sách màn hình tổng hợp

| Khu khách hàng | Khu quản trị |
| --- | --- |
| Trang chủ / danh sách sản phẩm | Tổng quan |
| Chi tiết sản phẩm | Danh sách / thêm / sửa sản phẩm |
| Giỏ hàng | Quản lý danh mục |
| Đăng ký / đăng nhập | Quản lý tồn và lịch sử điều chỉnh |
| Đặt hàng | Danh sách đơn |
| Kết quả đặt hàng | Chi tiết và xử lý đơn |
| Đơn hàng của tôi | |
| Chi tiết đơn | |

Website cần dùng được trên máy tính và điện thoại. Các màn hình phải có trạng thái đang tải, dữ liệu trống và lỗi phù hợp. Nút và thông báo dùng ngôn ngữ dễ hiểu, không hiển thị thông tin kỹ thuật nội bộ cho khách.

## 12. Tiêu chí hoàn thành sản phẩm

- Khách có thể hoàn thành hành trình tìm sản phẩm → giỏ hàng → đăng nhập → đặt hàng → theo dõi đơn.
- Nhân viên có thể đưa sản phẩm mới lên bán, nhập kho và xử lý đơn đến hoàn thành.
- Đơn thành công hiển thị đúng người nhận, mặt hàng, số lượng, giá và tổng tiền.
- Hai khách tranh mua lượng hàng cuối không làm vượt tồn.
- Khách hủy đúng điều kiện và hàng được trả lại khả năng bán đúng một lần.
- Khách không xem được đơn của người khác hoặc truy cập khu quản trị.
- Giá đơn cũ không đổi khi cửa hàng chỉnh giá sản phẩm.
- Thao tác lặp không tạo thêm đơn hoặc làm sai tồn kho.
- Thanh toán mô phỏng thành công/thất bại/chậm đều hiển thị đúng; timeout không tạo lần thanh toán thứ hai.
- Hủy đơn đã thanh toán chỉ hoàn tất sau giải phóng hàng và hoàn tiền mô phỏng; retry không hoàn thêm lần nữa.
- Có dữ liệu mẫu và kịch bản trình diễn đầy đủ, gồm cả tình huống không đủ hàng.

## 13. Kịch bản trình diễn đề xuất

### Kịch bản A — Mua hàng thành công

Khách chọn chuột và bàn phím, đặt COD. Nhân viên xác nhận, chuẩn bị, chuyển đang giao và hoàn thành sau khi xác nhận thu tiền. Khách theo dõi các mốc trên trang đơn hàng.

### Kịch bản B — Hủy trước khi xác nhận

Khách đặt hàng rồi hủy khi đơn chờ xác nhận. Đơn chuyển Đã hủy, lượng giữ được giải phóng. Thử hủy lại không làm thay đổi tồn kho thêm.

### Kịch bản C — Hai người mua sản phẩm cuối

Chuẩn bị một sản phẩm chỉ còn một đơn vị có thể bán. Hai khách cùng đặt mua. Chỉ một đơn được tiếp nhận; khách còn lại nhận thông báo hết hàng.

### Kịch bản D — Thay đổi giá

Khách thêm hàng vào giỏ; cửa hàng đổi giá trước khi khách đặt. Website yêu cầu khách xác nhận giá mới. Sau khi đơn được tiếp nhận, đổi giá lần nữa không ảnh hưởng đơn cũ.

### Kịch bản E — Thanh toán mô phỏng thất bại hoặc chậm

Khách chọn phương thức mô phỏng. Nếu kết quả thất bại, đơn hủy sau khi giải phóng hàng. Nếu kết quả chậm, giao diện giữ trạng thái đang xử lý và cho tra cứu; khách không bị yêu cầu thanh toán lại. Kết quả mô phỏng được cấu hình bởi quản trị demo, không do khách tự xác nhận thành công.

### Kịch bản F — Hủy đơn đã thanh toán mô phỏng

Khách thanh toán thành công rồi hủy trước khi nhân viên xác nhận. Website hiển thị đang hủy/hoàn tiền; chỉ hoàn tất khi hàng đã được giải phóng và tiền mô phỏng đã hoàn. Thử lại yêu cầu không tạo thêm lần hoàn. Nếu hoàn tiền lỗi, vẫn hiển thị đang xử lý và cho quản trị theo dõi.

## 14. Các quyết định cần nhóm xác nhận

Phần đã chốt: website cho một cửa hàng, nhóm 5 người, tập trung sản phẩm thương mại điện tử.

Thanh toán mô phỏng và Payment Service đã được xác nhận thuộc MVP. Các lựa chọn còn lại dưới đây là đề xuất để nhóm chốt:

| Nội dung | Đề xuất ban đầu |
| --- | --- |
| Ngành hàng | Phụ kiện máy tính |
| Tên cửa hàng và nhận diện | Chọn trước khi thiết kế giao diện |
| Thanh toán — đã chốt | COD và thanh toán mô phỏng, Payment Service riêng trong MVP |
| Phí giao hàng | Một mức cố định, số tiền do nhóm chốt |
| Vai trò nội bộ | Có thể gộp nhân viên và quản trị trong MVP |
| Biến thể | Mỗi cấu hình bán là một mặt hàng riêng |
| Hủy đơn | Khách hủy khi chờ xác nhận; nhân viên hủy trước khi giao kèm lý do |
| Vận chuyển | Cập nhật thủ công; chưa tích hợp đối tác |

Sau khi chốt các lựa chọn này, nhóm có thể dùng tài liệu làm cơ sở vẽ giao diện, viết user story và chia công việc mà chưa cần quyết định công nghệ.
