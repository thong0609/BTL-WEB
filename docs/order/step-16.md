# Step 16 — Kiểm tra và bàn giao

Ngày thực hiện: **15/11/2026**. Phụ trách: **Mạnh**.

**Đã hoàn thành phần có thể kiểm chứng riêng của Order:**

- 437 test backend với PostgreSQL/RabbitMQ riêng; 16 test frontend, 9 ca Chromium.
- Lint/typecheck backend và frontend đạt; build Next và hai image Docker đạt.
- Thử khởi động/restart image Order và frontend bằng container riêng, chạy user không phải root. API không tự chạy migration/worker.
- Tạo schema từ migration mới nhất trên PostgreSQL test; backup/restore dữ liệu Order rồi tiếp tục đơn đang chờ, giữ đúng inbox/outbox và chống lặp.
- Đối chiếu request/response và 12 route Order với OpenAPI; test hiện có tiếp tục kiểm tra 8 command/14 event và cấu trúc DB.
- Có [runbook](runbook.md), [bàn giao frontend](frontend-handoff.md), [kết quả test](test-results.md) và [sáu ca demo](demo.md).

**Chưa thể nghiệm thu toàn hệ thống:** chưa có các service nghiệp vụ của đồng đội để demo thật; chưa kiểm tra tranh tồn trong Inventory, số giao dịch bên Payment hoặc restore đồng bộ cả nhóm. Reviewer và người chạy lại tài liệu cũng cần xác nhận sau.

Không thay cấu hình bí mật, không reset/restore Supabase và không bật worker dev chung trong bước này. Migration Supabase vẫn ở `0003_action_audit` đã kiểm chứng ở Step 14. Cấu hình broker local đã được tạo bằng `infra dev init`; chưa khởi chạy stack dev.
