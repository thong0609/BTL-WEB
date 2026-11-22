# Step 13 — Admin xử lý đơn

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

Đã thêm API tại Order và routing Gateway:

| POST sau `/api/v1/admin/orders/{id}` | Kết quả |
| --- | --- |
| `/confirm` | 200; chuyển Chuẩn bị hàng |
| `/dispatch` | 202; gửi lệnh xuất kho, chỉ Đang giao sau Inventory xác nhận |
| `/complete` | 202; đơn trả trước hoàn thành khi đã giao và đã trả tiền; COD chờ Payment xác nhận ghi nhận thu tiền |
| `/exceptions` | 200; lưu lý do giao lỗi/cờ cần xử lý, giữ Đang giao |

Mọi thao tác bắt buộc `Idempotency-Key` và role ADMIN. Complete nhận `delivered:true`; COD còn cần `codCollected:true`. Actor thu COD lấy từ danh tính đã xác minh, không lấy từ body/header tự khai.

Lý do và xác nhận được lưu trong `order_action_requests.request_body` cùng actor/time/hash/response. Ghi ngoại lệ không tạo lịch sử chuyển trạng thái giả. Gửi lặp không xuất/thu lại; thao tác cạnh tranh được khóa và kiểm tra trạng thái trong transaction.

Code chính: [actions.py](../../apps/order-service/src/commerce_order/services/actions.py), [admin.py](../../apps/order-service/src/commerce_order/api/admin.py), [Gateway](../../apps/api-gateway/src/commerce_gateway/orders.py). Migration audit là `0003_action_audit`.

Đã kiểm tra toàn luồng COD và trả trước qua PostgreSQL/RabbitMQ thật với producer mẫu. **Chưa có UI và token Identity thật**; chúng tiếp tục ở Step 6/15. Kết quả toàn suite tại [Step 14](step-14.md).
