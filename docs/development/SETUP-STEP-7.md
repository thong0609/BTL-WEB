# Setup bước 7 — CI và bàn giao base

## 1. Phạm vi và trạng thái

Đã thêm workflow `.github/workflows/ci.yml` và kiểm tra bàn giao repository. Đây là cấu hình CI cho base hiện tại, không phải bộ nghiệm thu nghiệp vụ MVP. **Workflow mới chưa được commit/push hoặc chạy trên GitHub trong lần triển khai này.** Kết quả local được ghi riêng bên dưới; không dùng kết quả local để kết luận GitHub CI đã xanh.

## 2. Workflow hoạt động thế nào

Workflow chạy khi push vào `main`, khi mở/cập nhật pull request và khi chọn Run workflow trên GitHub. Hai job độc lập dùng runner `ubuntu-24.04`, timeout 20 phút/job. Lần chạy cũ trên cùng ref bị hủy khi có lần mới.

| Job | Các bước |
| --- | --- |
| `Backend checks` | Checkout; uv 0.12.19/Python 3.12.8; `uv sync --locked --all-packages`; kiểm tra repository; Ruff lint/format; mypy; toàn bộ pytest có PostgreSQL/RabbitMQ Docker tạm |
| `Frontend checks and HTTP smoke` | Node theo `.node-version`; `npm ci` bằng lockfile frontend; ESLint; TypeScript; test API client; Next.js build; cài backend từ uv.lock; smoke frontend → gateway → Catalog |

Các action checkout/setup-node/setup-uv được ghim bằng commit SHA, có chú thích major version để theo dõi khi cập nhật. Cache chỉ giúp tải dependency; bước cài bằng lockfile vẫn chạy. Token workflow chỉ cần `contents: read`, checkout không giữ credential Git. Không có `pull_request_target`, không deploy/push image/commit hoặc chạy bootstrap/migration dev.

Workflow đặt `APP_ENV=test`, DB/broker mặc định tắt. Fixture pytest tự tạo PostgreSQL database `commerce_test` và RabbitMQ vhost test trên Docker runner, dùng password ngẫu nhiên/cổng loopback rồi cleanup. Không dùng GitHub repository secrets, `.env` của thành viên, Supabase dev hoặc broker dev chung. Không trỏ workflow vào Compose dev/test đang được thành viên sử dụng.

Smoke HTTP tự mở Catalog, gateway và Next.js dev trên cổng tạm; backend bỏ đọc env file dev, DB/broker tắt. Nó kiểm tra health đi qua gateway, chuyển tiếp cookie/header/query/Set-Cookie và lỗi khi Catalog/gateway dừng. Đây là smoke HTTP, chưa phải browser E2E hay kiểm tra luồng checkout.

## 3. Kiểm tra repository trước bàn giao

```powershell
uv run --locked --all-packages python scripts/check_repository.py
```

Script lấy danh sách file tracked và untracked không bị ignore từ Git; không mở các file credential bị ignore. Nó chặn env thật, thư mục local/dependency/cert, file chứng chỉ/key được thêm nhầm; yêu cầu các field credential đang bật trong env template phải để trống; kiểm tra link Markdown local và code fence. Lỗi chỉ ghi tên file/dòng, không in credential. Giá trị mẫu URL đặt trong comment, thông tin thật chỉ lưu ngoài Git.

Kiểm tra này có phạm vi file/env template; vẫn phải review thay đổi code/log để tránh hardcode secret ở nơi khác. Các test đã có tiếp tục kiểm tra lỗi DB/broker không lộ URL/password và test không đọc `.env` dev.

## 4. Kiểm tra tương đương trên máy

Từ root repository, Docker Desktop Linux engine đang chạy:

```powershell
uv sync --locked --all-packages
uv run --locked --all-packages python scripts/check_repository.py
.\scripts\dev.ps1 lint all
.\scripts\dev.ps1 typecheck all
.\scripts\dev.ps1 test all --integration
.\scripts\dev.ps1 build web
.\scripts\dev.ps1 smoke-web
```

Máy clone mới cần cài frontend bằng `npm --prefix apps/web ci` trước các lệnh frontend. Không copy `.venv`, `node_modules`, credential hoặc file `infra/.local/` của người khác. Các phiên bản Python/Node/uv/npm và lockfiles đã khóa từ bước 1. Cách chạy hằng ngày, `.env`, broker local và test reset nằm ở [bước 6](SETUP-STEP-6.md).

Kết quả local của bước 7:

- `uv sync --locked --all-packages`, kiểm tra repository, Ruff lint/format, mypy 49 file backend và frontend ESLint/TypeScript: pass.
- **86 test backend pass**, gồm PostgreSQL/RabbitMQ integration và 2 ca mới bảo vệ việc không đọc/in credential trong kiểm tra bàn giao.
- **7 test frontend pass**, Next.js production build và smoke frontend → gateway → Catalog thật pass.
- Workflow qua **actionlint v1.7.12** chính thức, đã đối chiếu checksum bản tải; chỉ kiểm tra cú pháp workflow, không chạy GitHub-hosted job. ShellCheck không được chạy trong lần kiểm tra actionlint trên Windows này.
- Container test/process smoke đã cleanup; không truy cập Supabase dev hoặc broker dev để kiểm thử bước 7. Deprecation warning Starlette TestClient/HTTPX cũ vẫn còn, không che bằng filter.

**GitHub CI: chưa chạy cho thay đổi này**, chưa có run URL/SHA pass để ghi nhận. Cần commit/push rồi xem kết quả cả hai job. Kết quả trên máy Windows không thay cho việc kiểm chứng runner Ubuntu trên GitHub.

## 5. Tình trạng bàn giao

| Hạng mục | Tình trạng |
| --- | --- |
| Toolchain và lockfiles | Đã có; bước 1 và các lần build/install local đã kiểm chứng |
| Gateway + 5 API | Có app factory, settings, log/request ID, Error envelope, health; kiểm chứng ở bước 2 và 6 |
| Frontend | Có Next.js App Router/Tailwind, API client và trang kiểm tra kết nối; bước 5–6 đã build/chạy |
| Database | Có session/migration từng schema, runtime/migrator/owner, kiểm thử quyền và reset trên PostgreSQL test |
| RabbitMQ | Có transport/envelope/topology/smoke; broker local/worker monitor tách API; chưa có handler nghiệp vụ |
| Docker/script dev | Đã build/chạy cả bộ ứng dụng offline, kiểm tra reset test và giữ dữ liệu broker qua down/up ở bước 6 |
| CI | Workflow đã viết; kết quả GitHub cho phiên bản này đang chờ push/chạy thực tế |
| Supabase dev thật | Nhóm quản lý credential/cấu hình riêng; bước 7 không chạy lại bootstrap, migration hoặc xác minh toàn bộ quyền cloud |
| Broker chung giữa nhiều máy | Chưa cấp và chưa kiểm chứng; dev riêng dùng broker local |
| API/UI nghiệp vụ, inbox/outbox/Saga, production | Ngoài phạm vi base, chưa triển khai |

Nhóm có thể bắt đầu viết nghiệp vụ trên base local/test. Chưa kết luận môi trường tích hợp giữa nhiều máy hoặc production đã sẵn sàng. Khi dùng Supabase chung, mọi người cùng thấy thay đổi dữ liệu nhưng broker local vẫn giữ message riêng; chạy đầy đủ luồng cần đủ service/worker và handler tương ứng.

## 6. Kiểm tra sau khi đưa workflow lên GitHub

1. Commit/push khi được yêu cầu; mở tab [Actions của repository](https://github.com/thong0609/BTL-WEB/actions).
2. Chọn workflow CI cho đúng commit. Cả hai job phải thành công; xem log step bị lỗi nếu có.
3. Ghi URL run và SHA commit đã pass trước khi thông báo GitHub CI đã xanh. Không cần thêm secret Supabase để sửa lỗi test CI.
4. Nếu nhóm muốn chặn merge khi CI thất bại, người quản lý repo cấu hình branch protection/ruleset với tên hai job trên. Bước này chưa thay đổi thiết lập repository hoặc quyền merge của nhóm.

Nguồn chính thức: [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [setup-uv](https://github.com/astral-sh/setup-uv), [setup-node](https://github.com/actions/setup-node).
