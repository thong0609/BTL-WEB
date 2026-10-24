# Nhật ký quyết định thiết kế

Ngày lập 24/10/2026. Phân biệt **đã xác nhận bởi người dùng** và **đề xuất kỹ thuật để nhóm review**. Mỗi quyết định mới ghi ngày, người chốt, lý do, hệ quả và tài liệu cần sửa; chưa có tên người review thì không tự ghi là đã được cả nhóm duyệt.

| Mã | Quyết định | Trạng thái | Lý do / hệ quả |
| --- | --- | --- | --- |
| DEC-01 | Một cửa hàng, không sàn nhiều người bán | Người dùng xác nhận | Không có shop, hoa hồng hoặc chia đơn theo người bán |
| DEC-02 | Nhóm 5 người, định hướng microservices | Người dùng xác nhận | Cần contract và tích hợp sớm |
| DEC-03 | Payment riêng, mô phỏng thuộc MVP | Người dùng xác nhận | 5 service nghiệp vụ; test thành công/thất bại/chậm và hoàn mô phỏng |
| DEC-04 | React/NestJS/PostgreSQL/Prisma/RabbitMQ/Compose | Đề xuất | Thống nhất stack; nhóm cần kiểm tra năng lực và khóa phiên bản |
| DEC-05 | Một kho, VND, COD và phí ship cố định | Đề xuất kế thừa | Giảm biến thể quy trình; giá trị phí chưa chốt |
| DEC-06 | Một payment/order, một refund toàn phần/payment | Đề xuất | Retry cùng ID; thất bại đặt đơn mới sau hủy xong; không trả một phần |
| DEC-07 | Order điều phối, không có Saga service riêng | Đề xuất | Workflow lưu DB và outbox, không chỉ giữ RAM |
| DEC-08 | Outbox/inbox + unique operationId | Đề xuất cần thiết cho luồng | Gửi/nhận có thể trùng; không tuyên bố exactly-once |
| DEC-09 | Bản chính docs/, README ở gốc | Đề xuất tổ chức | Không sửa song song hai bản mô tả |
| DEC-10 | Quote không giữ giá/tồn; kiểm tra lại lúc tạo | Đề xuất mới | Thêm endpoint quote; PRICE_CHANGED yêu cầu xác nhận lại |
| DEC-11 | Khách chưa hủy khi PENDING; không tự hết hạn giữ | Đề xuất MVP | Cần job cảnh báo/đối chiếu để không mất dấu tiến trình |
| DEC-12 | Kubernetes/tracing nâng cao sau MVP | Đề xuất | Chỉ đổi nếu môn học bắt buộc, phải điều chỉnh thời gian |

## Các mục cần chốt trong buổi khởi động

Tên/ngành hàng; thời hạn và giờ mỗi người; phí ship; quyền ADMIN có cần tách không; giới hạn ảnh/số dòng; khoảng polling/retry/cảnh báo; cách triển khai HTTPS/service credential; tiêu chí môi trường demo. Kiểm tra yêu cầu giảng viên trước khi biến Kubernetes hoặc thanh toán thật thành đầu việc.

## Mẫu quyết định mới

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
