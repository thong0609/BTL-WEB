# Step 11 — Thanh toán mô phỏng

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

**Đã hoàn thiện phía Order với ba trường hợp:**

| Kết quả | Order làm gì? |
| --- | --- |
| Thành công | Chuyển Chờ xác nhận |
| Thất bại rõ ràng | Giải phóng hàng, xong mới Đã hủy; không hoàn khoản tiền chưa thu |
| Chưa có kết quả | Giữ Đang xử lý và giữ hàng; không tự hủy hoặc thu lại tiền |

Khách không chọn kết quả thanh toán. Lệnh dùng đúng tổng tiền đã lưu; kết quả cũ/lặp không thay đổi kết quả mới hoặc mở lại đơn đã kết thúc. Snapshot PENDING hợp lệ chỉ cập nhật trạng thái chờ; không phát lại lệnh thu tiền khi đã biết Payment đang xử lý.

Đã test nhận kết quả muộn, thành công/thất bại, chống trùng và luồng qua RabbitMQ thật. Code nằm ở [handlers.py](../../apps/order-service/src/commerce_order/messaging/handlers.py), [recovery.py](../../apps/order-service/src/commerce_order/services/recovery.py).

**Còn phối hợp:** đối chiếu cách tăng paymentVersion và chạy với Payment thật. Xem kết quả toàn suite ở [Step 14](step-14.md).
