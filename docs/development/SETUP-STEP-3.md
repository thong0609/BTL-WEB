# Setup bước 3 — PostgreSQL, SQLAlchemy và Alembic

## 1. Trạng thái và phạm vi

Đã triển khai hạ tầng DB cho Identity, Catalog, Inventory, Order và Payment: engine/session async, metadata riêng, migration riêng, bootstrap schema/role và kiểm tra quyền. Gateway không tạo engine/session DB. **Chưa có thông tin kết nối Supabase, nên chưa tạo hoặc thay đổi tài nguyên cloud.**

Kiểm thử dùng PostgreSQL thật trong container riêng, không thay SQLite hoặc dùng database dev của nhóm. Bảng nghiệp vụ, seed người dùng/sản phẩm, broker và workflow chưa thuộc bước này. Foundation revision chỉ tạo version table Alembic trong từng schema; schema/role do bootstrap tường minh quản lý.

## 2. Mapping và vai trò

| Service | Schema | Owner không đăng nhập | Migrator | Runtime |
| --- | --- | --- | --- | --- |
| Identity | commerce_identity | identity_owner | identity_migrator | identity_runtime |
| Catalog | commerce_catalog | catalog_owner | catalog_migrator | catalog_runtime |
| Inventory | commerce_inventory | inventory_owner | inventory_migrator | inventory_runtime |
| Order | commerce_orders | order_owner | order_migrator | order_runtime |
| Payment | commerce_payments | payment_owner | payment_migrator | payment_runtime |

Runtime có USAGE schema mình và SELECT/INSERT/UPDATE/DELETE trên bảng nghiệp vụ, USAGE/SELECT trên sequence. Không có CREATE/TRUNCATE, không được SET ROLE sang owner, không truy cập schema service khác. Version table Alembic không cấp quyền runtime.

Migrator dùng NOINHERIT và được SET ROLE sang owner schema mình khi chạy Alembic. Vì vậy bảng được owner tạo và default privileges áp dụng đúng chủ thể. Bootstrap cấp membership owner cho tài khoản quản trị đang chạy để thực hiện quản lý trên managed PostgreSQL; không dùng tài khoản đó chạy API.

## 3. Cấu trúc code

- `commerce_backend_common.database`: mapping, kiểm tra URL/TLS, engine/session kỹ thuật.
- `commerce_backend_common.database_lifespan`: đăng ký engine/checker, đóng pool, dependency get_session.
- `commerce_backend_common.database_bootstrap`: DDL schema/role và quyền; không chạy ở startup.
- `commerce_backend_common.migrations`: cơ chế Alembic giới hạn schema.
- `apps/<service>/src/commerce_*/db.py`: Base/metadata riêng, chưa có model nghiệp vụ.
- `apps/<service>/alembic.ini`, `migrations/env.py`, `script.py.mako`, `versions/0001_base.py`.
- `scripts/database.py`: CLI quản trị tường minh, không nhận password qua argument.
- [infra/supabase](../../infra/supabase/README.md): hướng dẫn bootstrap và danh sách tên biến cần cấp.

Shared package sử dụng extra `[database]` cho 5 service, gateway không khai báo extra này. Không chia sẻ Base/model hoặc join xuyên schema giữa service. Alembic-generated scripts được loại khỏi mypy tránh trùng tên env/revision giữa các thư mục; cơ chế migration dùng chung và code service vẫn được typecheck, migration được kiểm chứng trên DB thật.

## 4. Cấu hình service

Copy `.env.example` của service thành `.env` cùng thư mục và cấp secret ngoài Git. Template không có credential hoạt động. Các biến bổ sung:

| Biến | Mặc định / tác dụng |
| --- | --- |
| DATABASE_ENABLED | false; bật để API tạo engine và kiểm tra DB khi readiness |
| DATABASE_URL | Runtime URL, đúng *_runtime; nhận postgresql:// hoặc postgresql+asyncpg:// |
| MIGRATION_DATABASE_URL | Đúng *_migrator; bắt buộc khi chạy Alembic, không fallback runtime |
| DB_SCHEMA | Literal cố định theo service; không cho đổi sang public/service khác |
| DB_SSL_MODE | verify-full; require có mã hóa nhưng không kiểm tra certificate/hostname; disable chỉ cho loopback test |
| DB_SSL_CA_FILE | Đường dẫn tuyệt đối tới CA tải từ Supabase Database settings nếu hệ thống chưa tin certificate chain; dùng cho cả runtime và migration |
| DB_POOL_SIZE / DB_MAX_OVERFLOW | 2 / 1, tính trên từng process; không mặc định nhân pool cho mọi laptop |
| DB_CONNECT_TIMEOUT_SECONDS | 5 |
| DB_POOL_TIMEOUT_SECONDS | 5 |
| DB_QUERY_TIMEOUT_SECONDS | 5 |
| READINESS_TIMEOUT_SECONDS | 6; checker vượt hạn trả unavailable |

URL dùng role riêng; với Supabase session pooler, username có thể là `catalog_runtime.<project-ref>` theo Connect/config role thực tế, còn current_user trong PostgreSQL là catalog_runtime. Cần kiểm chứng cách đăng nhập custom role với project thật, chưa xác nhận được từ môi trường local.

Không nhận query params tùy ý trong URL, bao gồm sslmode/pgbouncer; thiết lập TLS qua DB_SSL_MODE. Base này chỉ hỗ trợ direct/session; từ chối cổng transaction pooler 6543. Lấy URI đúng từ cấu hình project và percent-encode password trong URI nếu có ký tự đặc biệt. Secret không được đặt trong NEXT_PUBLIC_*.

Từng engine có pool riêng và search_path chỉ schema service + pg_catalog; metadata/table vẫn khai báo schema tường minh. Pooler session không có nghĩa mọi máy có thể mở pool lớn: phải tính tổng số connection trong giới hạn dev project.

## 5. Trình tự áp dụng trên Supabase dev thật

1. Chủ môi trường xác nhận đúng project dev và quyền bootstrap. Kiểm tra schema commerce_* không được expose qua Data API. Chưa có thao tác này được chạy tự động.
2. Cấp các biến môi trường cho tiến trình quản trị theo `infra/supabase/bootstrap.env.example`: BOOTSTRAP_DATABASE_URL, SUPABASE_PROJECT_REF, TLS mode và 10 password runtime/migrator tối thiểu 16 ký tự. File template không tự được load; dùng cơ chế secret/env của máy, không paste secret vào command line hoặc log.
3. Chạy bootstrap có --apply. Dev target kiểm tra database postgres và host/project-ref tương ứng. Test target chỉ chấp nhận loopback/database commerce_test.
4. Điền runtime/migration URL trong .env của từng service. Chạy upgrade trước, sau đó current/check/inspect.
5. Bật DATABASE_ENABLED và chạy service; readiness chỉ trả database=ready sau kết nối và xác minh current_user/schema/USAGE/không CREATE đúng kỳ vọng.

```powershell
# Chạy từ gốc repo; đã cấp biến môi trường ngoài Git trước đó.
uv run --locked --all-packages python scripts/database.py bootstrap --target dev --apply

uv run --locked --all-packages python scripts/database.py upgrade --service catalog-service --apply
uv run --locked --all-packages python scripts/database.py current --service catalog-service
uv run --locked --all-packages python scripts/database.py check --service catalog-service
uv run --locked --all-packages python scripts/database.py inspect --service catalog-service
```

Các lệnh trên đã được kiểm tra với PostgreSQL test và role tương ứng; **lệnh target dev trên Supabase chưa chạy**. Thiếu quyền quản trị/custom role/SSL trên project thật cần xử lý trước khi công bố dev chung sẵn sàng.

Bootstrap chạy trong transaction, không drop schema/table hoặc sửa role hệ thống Supabase. Role/schema có owner/quyền bất thường sẽ bị từ chối. Rerun có thể đặt lại password được cung cấp, vì vậy chỉ chạy khi phối hợp cập nhật secret; không dùng bootstrap như lệnh start hằng ngày.

## 6. Session và transaction cho phần nghiệp vụ sau này

API có thể import session_dependency từ db.py của chính service và dùng Depends. Worker/job có thể dùng `async with database.session() as session`. Mỗi lần nhận session là một đối tượng mới; không dùng chung session trong asyncio.gather.

Session helper không tự commit. Use case dùng `async with session.begin():` để commit toàn bộ thay đổi cục bộ, tự rollback khi có lỗi. Đóng session cũng rollback phần chưa commit; engine được dispose khi lifespan đóng. Không gọi HTTP/broker trong lúc giữ transaction kho/tiền. Chưa viết ORM repository hoặc bảng nghiệp vụ.

## 7. Quy trình migration

Model mới phải kế thừa Base của service, được import vào metadata trước autogenerate. Lệnh tạo revision:

```powershell
uv run --locked --all-packages python scripts/database.py revision --service catalog-service --message "add products" --apply
```

Đây là ví dụ cho bước nghiệp vụ, chưa tạo revision products. Review SQL, tên constraint và chỉ định schema trước khi upgrade. Nếu khai báo table ở schema ngoài service thì autogenerate bị từ chối. include_name chỉ phản chiếu schema mình; không sinh drop table ở public, auth hoặc schema khác.

Mỗi schema có alembic_version riêng và revision khởi đầu 0001_base. Khi online, connection migration có session advisory lock theo schema, SET ROLE owner, chạy migration và thu hồi quyền runtime trên version table. Kết nối được đóng sau lệnh. Direct/session pooler là yêu cầu; không dùng transaction pooler cho lock/SET ROLE này.

Không gọi Alembic trong startup API và không create_all thay migration. Baseline downgrade không drop schema/role chung. CLI upgrade không dùng DATABASE_URL khi thiếu MIGRATION_DATABASE_URL. Lỗi CLI chỉ in loại lỗi, không in SQL/URI có password; khi cần debug phải bảo đảm không công khai exception/statement chứa secret.

Readiness hiện kiểm tra kết nối và quyền runtime cơ bản, không thay thế inspect (cách ly schema/version quyền) hoặc kiểm tra revision head. Cần chạy migration/current/check trong quy trình bàn giao.

## 8. Kiểm chứng và phần còn chờ

```powershell
uv run --locked --all-packages pytest -q --run-postgres
uv run --locked --all-packages ruff check apps packages scripts tests
uv run --locked --all-packages mypy
uv lock --check
```

Opt-in --run-postgres tạo container PostgreSQL 16 riêng, database commerce_test, password ngẫu nhiên và port loopback ngẫu nhiên. Bootstrap/migration chạy trong container này; fixture dừng/xóa container khi xong. Không cần/cũng không nhận URL dev để chạy test integration này. Không có --run-postgres thì integration case được skip rõ ràng.

Kiểm tra gồm: 5 schema/15 role, bootstrap và upgrade rerun, chỉ có version table sau baseline, quyền DML/default sequence, chặn DDL/TRUNCATE/SET ROLE/cross-schema/version write, commit/rollback, session đồng thời, autogenerate bỏ qua bảng thực ở schema khác, URL/TLS/migration credential guards, offline SQL không có password, FastAPI readiness/session lifecycle với PostgreSQL thật.

Kết quả cuối: **46 test pass**, Ruff lint/format và mypy pass, uv.lock hợp lệ. Docker test container đã dừng và được xóa. Có một deprecation warning TestClient/HTTPX kế thừa từ bước 2; không có test fail. Password test có ký tự đặc biệt để kiểm chứng quoting/percent-encoding, không dùng credential thật.

Supabase cloud, TLS/custom-role/session-pooler của project thật và cấu hình Data API vẫn pending vì chưa có thông tin truy cập; không coi test local là bằng chứng đã kết nối Supabase.

## 9. Xử lý SSLCertVerificationError

Nếu báo self-signed certificate in certificate chain, mở Supabase Dashboard → Database settings → SSL Configuration và tải CA certificate của database. Lưu file PEM/CRT trong `infra/supabase/certs/` (đã gitignore), ví dụ `supabase-ca.crt`. Không tự tin certificate chỉ lấy từ một kết nối chưa xác minh.

Trong `infra/supabase/.env.bootstrap` thêm:

```dotenv
BOOTSTRAP_SSL_MODE=verify-full
BOOTSTRAP_SSL_CA_FILE=D:/Single-Store-Ecommerce/infra/supabase/certs/supabase-ca.crt
```

Load lại file bằng lệnh bootstrap đã hướng dẫn rồi chạy lại. Với từng service, đặt `DB_SSL_MODE=verify-full` và `DB_SSL_CA_FILE` cùng đường dẫn trong .env để cả runtime và Alembic dùng CA đó. Không chỉ thêm biến bootstrap rồi bỏ cấu hình CA của service. Khi đổi máy/container, đường dẫn phải trỏ tới file CA thực tế trên máy/container đó.

Đây là cấu hình bổ sung CA tin cậy, không tắt hostname/certificate verification. File thiếu hoặc không đúng định dạng sẽ bị từ chối. Nếu vẫn lỗi, kiểm tra CA tải đúng project, hostname connection và certificate còn hạn; không đổi sang disable để che lỗi.

## 10. Bootstrap chậm và log REVOKE

SQLSTATE 00000 là successful_completion, không phải lỗi. REVOKE dùng để loại quyền truy cập chéo giữa service. Bản đầu gửi 180 câu REVOKE riêng cho bước cuối; phiên bản hiện tại gộp nhiều role trong mỗi câu, còn 15 câu cho bước này và giữ nguyên phạm vi quyền.

CLI hiện in tiến độ kèm số giây: kết nối, chuẩn bị từng schema, thu hồi quyền chéo và commit. Các thông báo Prepared/Preparing không chứng minh dữ liệu đã commit; chỉ dòng Bootstrap complete sau khi transaction kết thúc mới xác nhận thành công.

Bootstrap có transaction advisory lock chung để từ chối chạy trùng giữa các phiên bản đã cập nhật, lock_timeout 10 giây cho khóa DDL và timeout tổng mặc định 180 giây. Có thể cấu hình BOOTSTRAP_TIMEOUT_SECONDS trong khoảng 1–600. Timeout/mất kết nối lúc commit chưa chứng minh trạng thái cuối; kiểm tra trước khi retry. Connection có application_name=commerce-bootstrap để tra cứu hoạt động.

Phiên Python đã chạy trước lúc cập nhật vẫn dùng code cũ và không có cơ chế khóa mới. Không mở thêm bootstrap song song với phiên đó. Đợi phiên cũ kết thúc hoặc Ctrl+C tại terminal của nó, sau đó chạy lại một lần bằng code mới. Thay đổi chưa commit trong transaction sẽ bị rollback khi hủy; không cần drop schema hoặc reset project để thử lại.

Bản tối ưu đã qua **51 test trên PostgreSQL test riêng**, gồm kiểm tra chỉ có 15 nhóm REVOKE và từ chối phiên bootstrap đồng thời; các quyền cách ly service và migration vẫn được kiểm tra. Chưa tự chạy lại bootstrap trên Supabase của nhóm.

Nguồn tham khảo: [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html), [Alembic schema-level cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html), [PostgreSQL default privileges](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html), [SQLSTATE codes](https://www.postgresql.org/docs/current/errcodes-appendix.html).
