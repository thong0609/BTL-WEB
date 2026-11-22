# Step 10 — Đơn COD

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

**Đã hoàn thiện phía Order:** giữ hàng xong mới yêu cầu Payment tạo khoản COD. Nhận xác nhận hợp lệ mới chuyển đơn sang Chờ xác nhận. Thiếu hàng thì từ chối đơn và không tạo khoản COD.

- Kiểm tra đúng đơn, công việc, mã giữ hàng, sản phẩm/số lượng và số tiền.
- Kết quả lặp không tạo thêm khoản COD. Kết quả bị từ chối được ghi cờ cần kiểm tra.
- Đã test toàn luồng Order/Gateway + PostgreSQL/RabbitMQ thật, producer Inventory/Payment do test đóng vai.

Code dùng chung với Step 9: [handlers.py](../../apps/order-service/src/commerce_order/messaging/handlers.py). Các bài test mới nằm trong [test_lifecycle_api.py](../../tests/order/test_lifecycle_api.py) và [test_lifecycle_broker.py](../../tests/order/test_lifecycle_broker.py).

**Còn phối hợp:** ghép Inventory/Payment thật khi đồng đội triển khai xong. Chưa coi test producer mẫu là tích hợp service đồng đội. Kết quả toàn suite được ghi chung tại [Step 14](step-14.md).
