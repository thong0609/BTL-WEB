# Website bán hàng cho một cửa hàng

Bộ phân tích và thiết kế ban đầu cho nhóm 5 thành viên. Sản phẩm hỗ trợ mua hàng, quản trị sản phẩm, tồn kho, xử lý đơn, COD và thanh toán mô phỏng. **Đã bắt đầu setup bước 1: cấu trúc package và toolchain; chưa có ứng dụng chạy được.** Xem [kết quả và lệnh kiểm tra bước 1](docs/development/SETUP-STEP-1.md).

## Đọc từ đâu?

Xem [mục lục theo nhóm](docs/README.md) để tìm tài liệu sản phẩm, thiết kế, phát triển, hạ tầng, kế hoạch và kiểm thử.

1. [Mô tả website](docs/product/MO-TA-WEBSITE.md): người dùng, chức năng và phạm vi sản phẩm.
2. [Đặc tả nghiệp vụ](docs/product/DAC-TA-NGHIEP-VU.md): điều kiện, các bước và ngoại lệ của từng thao tác.
3. [Thiết kế giao diện](docs/design/THIET-KE-GIAO-DIEN.md): trang, form, nút và trạng thái hiển thị.
4. [Mô tả hệ thống](docs/design/MO-TA-HE-THONG.md): stack đề xuất, 5 service và database chi tiết.
5. [Thiết kế luồng xử lý](docs/design/THIET-KE-LUONG-XU-LY.md): trạng thái, sequence và phục hồi.
6. [Hợp đồng HTTP](docs/contracts/HTTP-API.md), [OpenAPI](docs/contracts/openapi.yaml) và [message](docs/contracts/MESSAGES.md): cách các phần trao đổi dữ liệu.
7. [Kế hoạch thực hiện](docs/project/KE-HOACH-THUC-HIEN.md) và [kiểm thử](docs/testing/KE-HOACH-KIEM-THU.md): đầu việc, phụ thuộc, điều kiện nghiệm thu.
8. [Hướng dẫn phát triển](docs/development/HUONG-DAN-PHAT-TRIEN.md) và [quyết định thiết kế](docs/decisions/CAC-QUYET-DINH-THIET-KE.md).

Tất cả bản chính thức nằm trong `docs/`. Không tạo thêm bản sao ở thư mục gốc. Đây là phiên bản thiết kế 0.1; các quy tắc chi tiết mới là đề xuất triển khai, cần nhóm review trước khi code, không phải sản phẩm đã được kiểm chứng.

## Phạm vi đã thống nhất

- Một cửa hàng; 5 service nghiệp vụ: Identity, Catalog, Inventory, Order, Payment.
- Payment mô phỏng nằm trong MVP. Thanh toán thật, vận chuyển tích hợp, nhiều người bán và đổi trả sau nhận nằm ngoài MVP.
- Backend **FastAPI/Python**, frontend **Next.js + TypeScript** đã được nhóm chọn. Thư viện phụ trợ đề xuất: PostgreSQL, SQLAlchemy/asyncpg, Alembic, Pydantic, aio-pika, pytest/HTTPX; triển khai dev theo cấu hình Docker Compose khi cần.
- Một kho, VND, COD, một cấu hình trên mỗi SKU và khung 8 tuần là giả định thiết kế hiện tại. Tên cửa hàng, ngành hàng, phí ship và nhân sự cụ thể còn cần nhóm chốt.

## Cách tra cứu một chức năng

Ví dụ hủy đơn: **UC-ORD-03 → UI-08 → POST /orders/{id}/cancel → ReleaseStock + CancelCodPayment/RefundPayment → AT-07, AT-08, AT-09**.

| Vai trò | Tài liệu ưu tiên |
| --- | --- |
| Cả nhóm | README, mô tả website, use case, quyết định thiết kế |
| Frontend | Giao diện, use case, HTTP/OpenAPI, trạng thái đơn |
| Backend | Hệ thống/DB, workflow, HTTP/message, test tương ứng |
| Người tích hợp | Workflow, hợp đồng, kế hoạch, hướng dẫn phát triển |

## Thuật ngữ dùng chung

| Thuật ngữ | Nghĩa trong dự án |
| --- | --- |
| MVP | Bản nhỏ nhất hoàn thành được luồng mua và xử lý đơn, gồm xử lý lỗi trọng yếu |
| SKU | Mã mặt hàng có một cấu hình bán cụ thể |
| Snapshot | Bản thông tin chốt lúc đặt, không đổi theo sản phẩm hiện tại |
| Reservation | Lượng hàng đã giữ cho đơn, chưa xuất kho |
| COD | Thu tiền khi giao; demo ghi nhận thủ công có quyền |
| Command / Event | Yêu cầu làm việc / kết quả đã xảy ra |
| Idempotency | Gửi lại cùng thao tác không làm nghiệp vụ lần hai |
| Outbox / Inbox | Công việc cần gửi / dấu message đã xử lý, ghi cùng transaction nghiệp vụ |
| Saga / Workflow | Các bước phối hợp nhiều service, có phục hồi và bù trừ |
| Bù trừ | Ví dụ giải phóng hàng hoặc hoàn tiền; không phải rollback chung 5 DB |

## Quản lý thay đổi

**Đã chốt và làm rõ 28/10/2026:** dev hằng ngày của nhóm dùng chung Supabase, database `postgres`, 5 schema/role riêng theo service. Backend có thể chạy trên laptop mỗi người và kết nối DB dev này để cùng thấy dữ liệu. Test cần reset dùng DB riêng; PostgreSQL local độc lập chỉ là tùy chọn. **Production chưa quyết định.** Xem [thiết kế Supabase](docs/infrastructure/PHUONG-AN-SUPABASE.md) về kết nối và phối hợp worker/broker. Chưa tạo/kiểm chứng tài nguyên thực tế.

Quy tắc nghiệp vụ nằm ở đặc tả; trạng thái/quy trình nằm ở thiết kế luồng; cấu trúc HTTP nằm ở OpenAPI; cấu trúc message nằm ở MESSAGES; cấu trúc DB nằm ở mô tả hệ thống. Nếu phát hiện xung đột, tạo ghi chú và sửa các tài liệu liên quan trong cùng PR trước khi triển khai. Không tự chọn cách hiểu riêng ở từng service.
