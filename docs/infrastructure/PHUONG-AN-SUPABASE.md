# Phương án PostgreSQL dùng chung trên Supabase

Ngày chốt: 28/10/2026. Trạng thái: **ACCEPTED — người dùng xác nhận và làm rõ**. **Môi trường dev hằng ngày của cả nhóm dùng chung một Supabase project**, database `postgres`, 5 schema và role riêng theo service. Thành viên có thể chạy FastAPI trên máy mình và kết nối database dev này để thấy cùng dữ liệu. **Production chưa được quyết định.** Chưa tạo project, tài khoản, schema hoặc kết nối thật. Identity tiếp tục quản lý đăng nhập, ảnh tiếp tục do Catalog lưu theo thiết kế hiện tại.

## 1. Mục đích và giới hạn

Dùng Supabase làm database dev chung ngay trong quá trình phát triển. Ví dụ một thành viên thêm sản phẩm qua Catalog thì các thành viên khác đọc cùng sản phẩm từ database dev đó. Không yêu cầu mỗi người duy trì một database local riêng để làm việc hằng ngày. Chạy backend local chỉ nói về nơi chạy code, không có nghĩa database cũng phải nằm trên máy cá nhân.

Test tự động cần reset dữ liệu, fault test hoặc thử migration phá cấu trúc dùng database test riêng. PostgreSQL local là lựa chọn tùy lúc cần làm offline/thử nghiệm, không phải luồng dev bắt buộc. Dùng chung dữ liệu vẫn giữ quyền riêng từng service; không dùng chung tài khoản postgres quyền cao. Production chưa bàn tới, không mặc định dùng cấu hình dev làm production.

Khi chạy checkout đầy đủ, các service và worker cần dùng broker dev chung để phối hợp với database dev chung. Nếu consumer/outbox worker trên mỗi máy đọc cùng DB nhưng gửi broker riêng thì công việc có thể đi sai nơi. Thành viên có thể chạy service mình trên laptop; địa chỉ gọi HTTP giữa các service cần cấu hình tới máy/host dev mà cả nhóm truy cập được. Cùng Supabase không tự tạo kết nối HTTP hoặc RabbitMQ giữa các máy.

## 2. Hai lựa chọn triển khai

| Lựa chọn | Tổ chức | Hệ quả |
| --- | --- | --- |
| Đã chọn cho dev nhóm | Một project, database postgres, 5 schema nghiệp vụ, role riêng theo service | Cùng dữ liệu khi phát triển, cô lập quyền theo service |
| Phương án tham khảo sau này | Project/database riêng cho từng service | Chưa triển khai; cần đánh giá tài nguyên và công quản lý khi chuyển |

Ánh xạ đã chốt cho database `postgres` như sau:

| Tên logic trong thiết kế DB | Schema vật lý trong database postgres | Runtime role đề xuất |
| --- | --- | --- |
| identity_db | commerce_identity | identity_runtime |
| catalog_db | commerce_catalog | catalog_runtime |
| inventory_db | commerce_inventory | inventory_runtime |
| orders_db | commerce_orders | order_runtime |
| payments_db | commerce_payments | payment_runtime |

Đây là **schema-per-service trong một database**, không phải 5 database vật lý. Danh sách bảng/field hiện tại giữ ý nghĩa nghiệp vụ. Không tạo FK hoặc join xuyên schema giữa service, dù PostgreSQL có thể cho phép. Không tạo đối tượng nghiệp vụ trong schema hệ thống của Supabase.

Database test và PostgreSQL local tùy chọn dùng cùng tên schema để migration nhất quán. Backend local dùng DATABASE_URL trỏ Supabase dev theo role service mình. Các tên identity_db... trong tài liệu là miền dữ liệu logic, không phải database cá nhân riêng cho mỗi thành viên.

## 3. Phân quyền và truy cập

- Tài khoản quản trị/bootstrap tạo schema/role và cấp quyền; không dùng làm runtime credential.
- Mỗi service có runtime role chỉ USAGE schema mình và quyền bảng/sequence cần thiết; không DDL hoặc quyền sang schema service khác.
- Migration dùng role riêng từng schema, có DDL trong schema đó. Cấp default privileges phù hợp cho bảng/sequence mới, kiểm thử lại quyền sau migration.
- SQLAlchemy khai báo schema tường minh; Alembic có version table trong schema service, include_schemas/include_object giới hạn đúng phạm vi, không autogenerate drop bảng của service khác.
- Schema nghiệp vụ không được expose qua Supabase Data API. Kiểm tra danh sách schema expose và quyền anon/authenticated/PUBLIC; thu hồi quyền không cần thiết trên đối tượng của nhóm, không sửa bừa role/schema do Supabase quản lý.
- Frontend Next.js chỉ truy cập nghiệp vụ qua gateway/FastAPI, kể cả Server Components. Không đưa DB credential/service-role key vào frontend và đặc biệt không đặt secret trong NEXT_PUBLIC_*. Dashboard có quyền cao, chỉ cấp người cần vận hành; xem dữ liệu thường ngày ưu tiên quyền đọc.
- Dùng secret theo môi trường và service; không commit connection string có password, không chụp ảnh/log chứa secret.

Database role là lớp cô lập giữa service. RLS không tự thay thế kiểm tra quyền chủ đơn ở FastAPI khi backend dùng một runtime role chung cho nhiều khách; nếu thêm RLS phải thiết kế context và policy riêng, không bật rồi mặc định đã an toàn.

## 4. Kết nối FastAPI/SQLAlchemy

Đề xuất backend dài hạn dùng direct connection nếu mạng hỗ trợ, hoặc **session pooler** nếu cần IPv4. Lấy host/user/port từ mục Connect của project, không tự đoán connection string hoặc dùng URL HTTPS của project làm DB URL.

| Biến cấu hình | Ý nghĩa |
| --- | --- |
| DATABASE_URL | URL PostgreSQL cho runtime role của service; dùng driver SQLAlchemy asyncpg |
| MIGRATION_DATABASE_URL | Kết nối migration với role có DDL; ưu tiên direct, kiểm tra session mode khi môi trường không truy cập direct được |
| DB_SCHEMA | Tên schema service được allowlist/config cố định |
| DB_POOL_SIZE / DB_MAX_OVERFLOW | Giới hạn kết nối của từng process |
| APP_ENV | dev hoặc test; dev có thể chạy code trên laptop nhưng dùng Supabase chung; tool reset chỉ được chạy với DB test đã xác minh |
| BROKER_URL | Broker local khi code riêng; cùng broker/vhost khi ghép workflow giữa nhiều máy; test dùng broker riêng |

Yêu cầu SSL theo hướng dẫn nhà cung cấp và cấu hình driver; giữ xác minh chứng chỉ phù hợp. Không copy tùy tiện tham số sslmode của driver đồng bộ sang asyncpg mà chưa kiểm chứng.

Chưa chọn transaction pooler cho MVP. Chế độ này có giới hạn prepared statements/session state; không chỉ đổi port sang 6543 và coi tương thích asyncpg. Nếu chọn phải cấu hình/test driver, prepared statements, search_path, transaction và migration riêng. Một ứng dụng nhiều process nhân số pool lên; tính tổng kết nối cả 5 service, gateway nếu có DB, workers, migration và công cụ quản trị theo giới hạn project thực tế.

Nguồn: [Supabase — kết nối PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres), [pooling và giới hạn](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits).

## 5. Phối hợp migration và seed

1. Chủ service tạo migration, thử trên database test riêng bằng cùng schema vật lý.
2. Reviewer kiểm tra SQL và phạm vi schema; đặc biệt autogenerate, constraint và Alembic version table.
3. Merge rồi chủ service/người được phân công chạy migration đã duyệt trên Supabase dev chung, mỗi schema một tiến trình migration tại một thời điểm. Không mỗi người chạy migration chưa merge lên DB chung.
4. Chạy seed không phá dữ liệu: có khóa cố định/unique phù hợp, không reset tồn của đơn đang chạy hoặc ghi đè trạng thái tiền.
5. Công bố revision từng schema và bộ fixture cho cả nhóm; chạy smoke test quyền và checkout.

Không sửa cấu trúc tay trong Dashboard rồi bỏ qua migration. Emergency fix phải được ghi lại và đưa vào migration có kiểm soát. Không drop schema, truncate hoặc reset DB chung để sửa lỗi cá nhân. Backup/restore phải thử ở môi trường riêng; kiểm tra tính năng và thời hạn backup của project thực tế, không mặc định có khôi phục theo thời điểm.

## 6. Môi trường và worker

| Môi trường | DB | Broker / worker | Mục đích |
| --- | --- | --- | --- |
| Dev hằng ngày của nhóm | Supabase dev chung, database postgres/5 schema | RabbitMQ local từng máy; chạy đủ service/worker cần cho luồng local | Cùng dữ liệu DB, message tách riêng theo broker |
| Ghép service giữa nhiều máy | Supabase dev chung | Cùng broker/vhost, phân công worker và địa chỉ HTTP | Kiểm tra luồng xuyên các máy/service |
| CI/test | DB tạm hoặc DB test riêng, không trỏ Supabase dev | Broker test riêng | Reset, fault test và concurrency |
| Local độc lập tùy chọn | PostgreSQL local | Broker local nếu cần | Offline/thử nghiệm riêng; không phải yêu cầu dev mặc định |
| Production | Chưa quyết định | Chưa quyết định | Thiết kế khi nhóm có nhu cầu triển khai thực tế |

**Cách phối hợp đã chốt:** code nền tảng và hợp đồng message dùng chung; mỗi người viết handler của service mình, chạy RabbitMQ local để code riêng. Ví dụ Order trên máy A gửi vào broker A thì Inventory phải kết nối broker A để nhận; Inventory trên broker B không nhận message đó. Khi ghép service giữa nhiều máy, chuyển các phần liên quan sang cùng broker/vhost và thống nhất endpoint HTTP. Không cần máy thứ sáu để dùng chung DB. Script/Compose tại [bước 6](../development/SETUP-STEP-6.md) hỗ trợ broker local và chế độ dùng broker đã cấu hình.

Nếu một service được nhiều người cùng sửa, thống nhất bộ consumer/outbox worker nào đang hoạt động. Các bản local thử API/đọc dữ liệu có thể tắt worker để không tranh xử lý công việc của nhau. Không chạy nhiều bản consumer khác version thiếu phối hợp; lease chống lặp không bảo đảm chọn đúng phiên bản code. Dữ liệu dev chung thay đổi bởi mọi người, nên các ca kiểm thử cần kết quả cố định phải dùng test DB riêng.

Ảnh sản phẩm hiện là file do Catalog quản lý, không nằm trong PostgreSQL. Các máy muốn thấy cùng ảnh cần dùng endpoint của cùng Catalog dev và nơi lưu file đó; chung Supabase DB chưa đồng bộ file ảnh. Chưa chốt chuyển sang Supabase Storage.

## 7. Công việc triển khai quyết định đã chốt

- Hệ thống: mapping database/schema, deployment diagram, runtime role và migration URL.
- Phát triển: env example, lựa chọn direct/session, hướng dẫn kết nối và quyền đã kiểm chứng.
- Kế hoạch: INF-01 gồm Supabase dev/schema/role, broker dev, địa chỉ service và người chạy worker từng service.
- Kiểm thử: role không truy cập schema khác, migration đúng schema, test reset không dùng DB dev; backend local kết nối được Supabase dev, outbox gửi đúng broker dev.
- Quyết định: một project/5 schema đã chốt; còn phân công người vận hành và người quản lý secret. API/message và quy tắc mua hàng không đổi chỉ vì đổi nơi đặt PostgreSQL.

## 8. Điều kiện sẵn sàng cho môi trường dev chung

Cả nhóm biết ai quản lý Supabase và ai chạy worker; backend trên máy thành viên kết nối bằng role service riêng; dữ liệu do một thành viên tạo được thành viên khác nhìn thấy với quyền phù hợp; migration đúng schema; frontend không có secret DB. Luồng checkout cần thêm service HTTP/broker dev kết nối được và dùng cùng bộ contract. Đây là điều kiện kiểm chứng dev, không phải kế hoạch production.
