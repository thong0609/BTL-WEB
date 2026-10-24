# Kế hoạch thực hiện nhóm 5 người

Khung 8 tuần tính từ ngày nhóm bắt đầu, chưa gán lịch cá nhân. Payment mô phỏng thuộc MVP. Người 1–5 là vị trí tạm, nhóm cần điền tên và thời gian có thể làm mỗi tuần.

## 1. Phân công và review

| Người | Phần chính | Review/phối hợp |
| --- | --- | --- |
| 1 | Identity, gateway, cấu hình Compose/CI | Review quyền; cùng người 2 review Payment |
| 2 | Catalog và Payment mô phỏng | Người 5 hỗ trợ UI quản trị sản phẩm; người 1 hỗ trợ tích hợp |
| 3 | Inventory, counter/reservation/movement | Cùng người 4 review transaction và bù trừ |
| 4 | Order, workflow, idempotency | Review event với người 2/3; tránh ôm UI |
| 5 | Frontend mua sắm, tích hợp UI, E2E | Chủ service hỗ trợ UI quản trị và fixture |

Mỗi chủ service phụ trách schema/migration, Dockerfile, validation, test và tài liệu API của mình. Cả nhóm cùng kiểm thử tích hợp; không giao tất cả QA/DevOps cho người 5.

## 2. Backlog theo đầu ra

| Task | Nội dung | Chủ trì | Phụ thuộc | Bằng chứng hoàn thành |
| --- | --- | --- | --- | --- |
| PL-01 | Review phạm vi, thuật ngữ, state và contract v0.1 | 1 + cả nhóm | Không | Quyết định ghi trong decisions |
| INF-01 | Khung monorepo, Compose, DB accounts, broker | 1 | PL-01 | Healthcheck và chạy môi trường có hướng dẫn |
| INF-02 | CI typecheck/lint/test/build | 1 + chủ service | INF-01 | PR mẫu pass |
| ID-01 | Register/login/refresh/logout, seed ADMIN | 1 | INF-01 | AT-01/02, không lộ secret |
| CAT-01 | Danh mục/sản phẩm/ảnh, query công khai | 2 | INF-01 | AT-03/11, seed hàng |
| INV-01 | Khởi tạo, adjustment, counter và history | 3 | CAT-01 | AT-12 |
| INV-02 | Reserve/release/commit + inbox/outbox | 3 | Contract message | AT-16/17/21 |
| PAY-01 | COD, mô phỏng success/fail/delay | 2 | Contract message | AT-06/19/20 |
| PAY-02 | Cancel/refund, retry, version, outbox | 2 | PAY-01 | AT-08/09/22 |
| ORD-01 | Quote, tạo đơn, snapshot, idempotency | 4 | CAT-01 | AT-05/18/23 |
| ORD-02 | Workflow checkout và phục hồi | 4 | INV-02, PAY-01 | Hai phương thức chạy xuyên hệ thống |
| ORD-03 | Hủy, dispatch, complete và exceptions | 4 | ORD-02, PAY-02 | AT-07–15 |
| UI-01 | Browse, cart, login, checkout | 5 | Contract HTTP | Luồng khách có loading/error |
| UI-02 | Đơn khách và quản trị | 5 + 4 | ORD-03 | Không phải dùng công cụ API để demo |
| UI-03 | UI sản phẩm/kho/demo | 2/3 + 5 | CAT/INV/PAY | Tạo hàng, nhập kho và chọn demo qua UI |
| QA-01 | Fault/concurrency/contract/E2E | Cả nhóm | Luồng tối thiểu | Báo cáo test có kết quả thật |
| REL-01 | Demo, backup/restore, tài liệu chạy | 1 + cả nhóm | QA-01 | Thành viên khác dựng lại được |

## 3. Mốc từng tuần

| Tuần | Kết quả bắt buộc | Nếu chậm |
| --- | --- | --- |
| 1 | Chốt giả định; bộ khung; message thử; fixture hợp đồng | Cắt trang trí và báo cáo nâng cao, không bỏ contract |
| 2 | Một SKU đặt mô phỏng thành công qua Order–Inventory–Payment; UI tối thiểu | Ghép cặp xử lý tích hợp, chưa thêm feature |
| 3 | Failure/delay, COD, cancel/refund, outbox/inbox, idempotency | Giữ COD + mô phỏng theo phạm vi đã chốt, giảm dashboard/ảnh phức tạp |
| 4 | Khách mua và ADMIN xử lý đến hoàn thành qua UI | Dừng feature mở rộng |
| 5 | Test cạnh tranh, timeout, restart, event cũ/trùng; sửa sai dữ liệu | Ưu tiên lỗi đúng đắn hơn UI đẹp |
| 6 | MVP đạt ma trận nghiệm thu, triển khai demo và khôi phục thử | Dành tuần 7 sửa điểm chưa đạt |
| 7 | Ổn định; tối đa một mở rộng nhỏ nếu mọi điều kiện đã đạt | Không thêm Kubernetes khi luồng lõi còn lỗi |
| 8 | Đóng băng, tổng duyệt, báo cáo/video/bằng chứng | Chỉ sửa lỗi ảnh hưởng nghiệm thu |

## 4. Definition of Ready / Done

Task sẵn sàng khi có use case, chủ trì/reviewer, contract cần dùng và ca kiểm thử mong đợi. Task xong khi code được review/merge, migration/test phù hợp pass, chạy được trong môi trường chung và tài liệu liên quan đã cập nhật. Task tích hợp chỉ xong khi consumer thật gọi được; service tự trả mock chưa đủ.

PR nhỏ theo một mục tiêu; ít nhất một người review. Khi đổi contract phải có người bị ảnh hưởng review. Demo tích hợp mỗi tuần bằng dữ liệu mẫu; ghi blocker cùng chủ xử lý và mốc tiếp theo. Thay đổi phạm vi phải cập nhật decisions, use case, contract và test trong cùng đợt.

## 5. Rủi ro cần theo dõi

Payment/Catalog cùng người 2 và Order ở người 4 là hai điểm dễ quá tải. Khi chậm, chuyển UI quản trị cho người 5/1, ghép người 3–4 kiểm thử workflow, không chia nhỏ service thêm. Chưa biết năng lực nhóm nên phân công này là đề xuất, cần review sau tuần 1.
