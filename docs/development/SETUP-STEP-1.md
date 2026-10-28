# Kết quả setup bước 1 — cấu trúc và toolchain

## Phạm vi

Repo hiện có bộ khung package và công cụ; chưa có FastAPI app, HTTP route, Next.js page/layout, kết nối Supabase hoặc worker nghiệp vụ. Phần đó thực hiện ở các bước sau trong [plan](../../plans/SETUP-BASE.md).

## Phiên bản và dependency

| Công cụ | Phiên bản chọn | Cách khóa |
| --- | --- | --- |
| Python | 3.12.8 | .python-version; requires-python giới hạn 3.12 |
| uv | 0.12.19 | required-version trong pyproject.toml |
| Node.js | 22.19.0 | .node-version, .nvmrc; engines giới hạn 22 |
| npm | 10.9.3 | packageManager và engines frontend |
| Next.js / React / TypeScript | 16.4.3 / 19.3.1 / 5.9.3 | Manifest frontend và package-lock.json |
| Backend dependencies | Phiên bản cụ thể trong uv.lock | Một lockfile cho 7 workspace packages |
| Frontend dependencies | Phiên bản cụ thể trong apps/web/package-lock.json | npm ci tái lập dependency graph |

Máy đang có Python mặc định 3.10 và các interpreter khác. Setup dùng bản 3.12.8 đã cài, không đổi Python mặc định hoặc Node hệ thống. Tên module riêng: commerce_gateway, commerce_identity, commerce_catalog, commerce_inventory, commerce_order, commerce_payment, commerce_backend_common.

Mỗi service có pyproject.toml và src-layout đóng gói bằng Hatchling. Package shared chỉ có namespace/type marker; chưa có tiện ích dùng chung. Các dependency nền tảng được khai báo theo service, không đưa nghiệp vụ/ORM model vào package chung.

## Lệnh dùng từ gốc repo

Các lệnh sau được dùng để cài và kiểm tra bước 1:

```powershell
uv sync --locked --all-packages --link-mode copy
uv lock --check
uv run --locked --all-packages ruff check apps packages
uv run --locked --all-packages ruff format --check apps packages
uv run --locked --all-packages mypy
```

`--link-mode copy` tránh cảnh báo hardlink khi cache và project khác ổ; máy có cùng ổ có thể bỏ. `uv sync --all-packages` cài tất cả service và package chung trong một virtualenv. Khi cần kiểm tra dependency độc lập của service, dùng môi trường riêng; uv workspace không tự cấm import dependency chỉ được service khác khai báo.

Kiểm tra frontend, chạy từ gốc repo:

```powershell
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
```

Trên checkout mới có đủ dung lượng, cài frontend bằng `npm --prefix apps/web ci`. File lock sẽ được tạo từ install thực tế và là nguồn phiên bản tái lập. Script dev/build/start đã được khai báo để dùng khi có app ở bước 5; hiện chưa chạy được vì chưa có page/layout. Không coi typecheck/lint lúc chưa có app là xác nhận ứng dụng hoạt động.

pytest/HTTPX/AnyIO đã có trong dev dependency và cấu hình pytest ở gốc. Chưa có test nghiệp vụ hoặc app ở bước này, nên không báo pytest pass với 0 test. Tests được bổ sung khi có hành vi cần kiểm chứng.

## Cấu trúc đã tạo và phần để sau

`apps/` có 6 Python packages và thư mục tooling frontend; `packages/backend-common` là shared namespace; `packages/contracts` hướng về nguồn contract hiện tại. `infra/supabase`, `scripts`, `.github/workflows`, `tests` có chỗ đặt nội dung cho các bước sau.

Chưa tạo compose.dev.yaml, compose.test.yaml hoặc workflow CI giả. Các file chạy thực tế thuộc bước 6/7. Chưa dựng frontend page hoặc app factory chỉ để làm script build có vẻ pass.

## Lưu ý riêng máy hiện tại: ổ D gần đầy

Trong lúc setup, ổ D chỉ còn vài MB và cài dependency dừng vì hết dung lượng. Môi trường cài dở được giữ ở `.venv-incomplete`, không xóa dữ liệu khác.

Dependency được cài trong vùng riêng tại `C:\Users\tohuy\AppData\Local\commerce-dev\BTL-WEB-step1`, liên kết bằng junction vào repo khi cần. Source, manifest và lockfile vẫn nằm ở D. Đường dẫn C này là workaround của máy hiện tại, không phải yêu cầu cho các thành viên khác hoặc cấu hình đem commit.

npm có thể xóa junction node_modules khi install/ci. Trên máy này cần cài ở thư mục staging riêng trên C, chép package-lock về repo rồi tạo lại junction; không chạy npm ci trực tiếp vào ổ D gần đầy. Khi bổ sung dependencies sau này phải cập nhật manifest và lockfile đồng bộ, không chỉ sửa staging.

Các thư mục dependency, cache, file .env, logs và uploads đều bị gitignore; .env.example vẫn được phép track. Không có credential Supabase/broker nào được tạo hoặc đưa vào repo.

## Kết quả kiểm tra bước 1

- uv lock --check và uv sync --locked --all-packages: thành công, dùng Python 3.12.8.
- Cài editable và import cả 7 workspace packages trong cùng interpreter: thành công.
- Ruff lint/format và mypy: pass trên package skeleton hiện tại.
- npm ci từ lockfile: thành công trong staging C do ổ D thiếu dung lượng; manifest/lockfile đã chép về repo và liên kết dependency để kiểm tra tại apps/web.
- Frontend ESLint và TypeScript: pass trên cấu hình hiện tại. Chưa có component/trang nên chưa đánh giá chất lượng code UI.
- npm audit trong lần ci: 0 vulnerabilities tại thời điểm chạy; không phải cam kết an toàn lâu dài.
- Kiểm tra gitignore: secret/dependency bị bỏ qua, .env.example không bị bỏ qua.
- Không chạy application build, server, pytest nghiệp vụ, CI GitHub hoặc kiểm tra kết nối cloud ở bước này.

ESLint khóa ở 9.39.5 vì các plugin của eslint-config-next hiện dùng peer range hỗ trợ 9; thử 10 cho peer conflict nên không dùng. Registry báo ESLint 9 đã hết hỗ trợ; cần xem lại cặp phiên bản khi plugin hỗ trợ 10. Đây là giới hạn toolchain được ghi nhận, không dùng --force/legacy-peer-deps để che xung đột.

Tham khảo: [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/), [Next.js installation](https://nextjs.org/docs/app/getting-started/installation). Phiên bản cụ thể dựa vào interpreter trên máy và metadata registry/lockfile đã cài thực tế, không chỉ từ ví dụ tài liệu.
