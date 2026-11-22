# Step 12 — Hủy đơn và hoàn tiền

Ngày triển khai: **15/11/2026**. Phụ trách: **Mạnh**.

**Đã có hai API:**

- Khách: `POST /api/v1/orders/{id}/cancel`.
- Admin: `POST /api/v1/admin/orders/{id}/cancel`.

Body là `{"reason":"Lý do hủy"}`, bắt buộc có `Idempotency-Key`. Khách chỉ hủy đơn mình ở Chờ xác nhận; admin được hủy thêm lúc Chuẩn bị hàng. Chặn khi đang thanh toán, bàn giao hoặc hoàn thành.

Khi nhận hủy, Order lưu Đang hủy và hai yêu cầu trong cùng transaction: giải phóng hàng; hủy COD hoặc hoàn toàn bộ tiền đã trả, gồm phí ship. Chỉ Đã hủy khi cả hai nhánh xong. Hoàn tiền lỗi thì giữ Đang hủy; retry chỉ nhánh chưa xong.

Gửi lại cùng key/payload trả kết quả cũ. Cùng key khác lý do trả 409. Hủy đơn đã hủy bằng key mới trả trạng thái hiện có, không tạo lệnh giải phóng/hoàn tiền mới. Sai chủ đơn trả 404.

Code: [actions.py](../../apps/order-service/src/commerce_order/services/actions.py), [API customer](../../apps/order-service/src/commerce_order/api/customer.py), [API admin](../../apps/order-service/src/commerce_order/api/admin.py). Đã test hai thứ tự hoàn tất kho/tiền, rollback khi lỗi DB, hủy cạnh tranh xác nhận/bàn giao và refund lỗi rồi thành công.

Migration `0003_action_audit` thêm một cột JSON nullable `request_body` trong `order_action_requests` để giữ input đã validate phục vụ audit. Không thêm bảng hoặc sửa migration `0002`; dữ liệu cũ được giữ nguyên.

**Còn phối hợp:** chạy với Inventory/Payment và Identity thật; nguyên tắc token Identity vẫn theo điểm mở Step 6. Kết quả kiểm tra tại [Step 14](step-14.md).
