# Nhật ký quyết định Identity

Ngày lập 21/11/2026.
Người quyết định: vq (Identity Backend và Frontend).

File này ghi quyết định của riêng Identity. Quyết định chung của nhóm nằm ở
[CAC-QUYET-DINH-THIET-KE.md](CAC-QUYET-DINH-THIET-KE.md). Schema Identity vẫn nằm ở
`MO-TA-HE-THONG.md` (F.2, F.3, F.3A);
file này không giữ bản sao song song (DEC-09).

## Phân loại quyết định

Hỏi: **nếu quyết định này đổi, ai phải sửa code hoặc test?**

1. **Service-local:** chỉ mình Identity tự sửa. Chủ Identity tự quyết và ghi ở file này (mã `IDN-xx`).
2. **Cross-component:** chỉ các phần do chủ Identity phụ trách (Backend, Frontend), nhưng có chạm kiến trúc dùng chung. Ghi nhận và kiểm tra tương thích; nếu chạm thành phần dùng chung (như Gateway) thì ghi ở file chung.
3. **Cross-service:** có service hoặc thành phần khác phải sửa hoặc bị ảnh hưởng. Ghi ở `CAC-QUYET-DINH-THIET-KE.md` dạng PROPOSED, thông báo và xin review bên liên quan.

Luật cứng: thứ gì nhìn thấy được từ bên ngoài Identity thì không phải service-local. Gồm nội dung
`openapi.yaml` và `HTTP-API.md`, error code, response của `GET /users/me`, cookie hoặc header đi qua Gateway,
format hoặc claim của token nếu service khác verify, route Gateway, `packages/backend-common`, và schema
lệch với `MO-TA-HE-THONG.md`. Nếu một quyết định có cả phần local lẫn phần chạm ra ngoài, phần local ghi ở đây,
phần chạm ra ngoài đi theo kênh riêng và được ghi ở dòng "Chạm ra ngoài Identity".

Trạng thái: ACCEPTED hoặc SUPERSEDED. Không sửa đè quyết định cũ; muốn đổi thì tạo mã mới và chuyển mã cũ sang SUPERSEDED.

## Bảng tóm tắt

| Mã | Quyết định | Trạng thái |
| --- | --- | --- |
| IDN-01 | Hai phương thức đăng nhập; Identity tự cấp token nội bộ | ACCEPTED |
| IDN-02 | Google OIDC: Authorization Code + PKCE + state + nonce | ACCEPTED |
| IDN-03 | Email Google trùng: không auto-merge, đăng nhập tài khoản cũ rồi liên kết | ACCEPTED |
| IDN-04 | Bảng `user_identities`, định danh bằng Google `sub` | ACCEPTED |
| IDN-05 | `users.password_hash` nullable | ACCEPTED |
| IDN-06 | Access Token JWT RS256, TTL 15 phút | ACCEPTED |
| IDN-07 | Refresh Token opaque, chỉ lưu hash, rotation + reuse detection theo family | ACCEPTED |
| IDN-08 | Refresh TTL: idle 7 ngày, absolute 30 ngày | ACCEPTED |
| IDN-09 | Giữ lịch sử refresh sau rotation, dọn theo cấu hình vận hành | ACCEPTED |
| IDN-10 | Hoãn xác minh email khi đăng ký khỏi MVP | ACCEPTED |
| IDN-11 | Hoãn đặt mật khẩu cho tài khoản chỉ có Google khỏi MVP | ACCEPTED |

Tham chiếu sang file chung: cookie (DEC-16), Origin/Referer (DEC-17), popup Google (DEC-18),
Gateway (DEC-15), bootstrap ADMIN (DEC-19).

---

**IDN-01 — Hai phương thức đăng nhập, Identity tự cấp token nội bộ**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Tài liệu hiện chỉ mô tả Email/Password. Yêu cầu bổ sung là đăng nhập bằng Google.
- **Quyết định:** Hỗ trợ Email/Password và Google. Dù đăng nhập bằng cách nào, Identity xác minh, tìm hoặc tạo User nội bộ rồi cấp Access Token và Refresh Token của BTL-WEB. Google chỉ xác thực danh tính. Không dùng Google token làm token hệ thống và không lưu Google token (MVP không gọi Google API).
- **Lý do và phương án đã cân nhắc:** Identity là nơi quản lý role, status và phiên. Đã loại: chỉ Email/Password, chỉ Google, dùng Google Access/Refresh Token thay token nội bộ.
- **Hệ quả / công việc phát sinh:** Thêm endpoint Google start/callback ngoài 5 endpoint hiện có.
- **Chạm ra ngoài Identity:** việc thêm endpoint vào `openapi.yaml` và `HTTP-API.md` là PR contract chung, ngoài file này.
- **Tài liệu, contract và test cần đổi:** `DAC-TA-NGHIEP-VU.md` (UC đăng nhập Google), `KE-HOACH-KIEM-THU.md`.

**IDN-02 — Google dùng OIDC Authorization Code + PKCE + state + nonce**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Cần luồng Google chống CSRF, replay và chặn authorization code.
- **Quyết định:** Dùng Authorization Code + PKCE, kèm `state` và `nonce`. Backend Identity trao đổi code và xác minh ID Token; frontend không xử lý Client Secret hay ID Token.
- **Lý do và phương án đã cân nhắc:** Đây là luồng chuẩn hiện hành cho ứng dụng web có backend.
- **Hệ quả / công việc phát sinh:** Cần cấu hình `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (tên là đề xuất; không commit secret). Cần thư viện xác minh ID Token: chưa thêm dependency, chờ duyệt từng thư viện. Chi tiết kiểm tra claim ID Token để ở thiết kế Google OIDC.
- **Chạm ra ngoài Identity:** nơi lưu `state`/`nonce`/`code_verifier` và việc đi qua popup, Gateway thuộc DEC-18 và DEC-15.
- **Tài liệu, contract và test cần đổi:** `MO-TA-HE-THONG.md` mục G, `KE-HOACH-KIEM-THU.md` (state sai, nonce sai, code replay).

**IDN-03 — Email Google trùng tài khoản cũ: không auto-merge**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Người dùng đăng nhập Google bằng email đã có tài khoản Email/Password.
- **Quyết định:** Không cấp phiên và không tự gộp. Người dùng đăng nhập tài khoản cũ, xác thực lại mật khẩu, rồi chủ động liên kết. Điều kiện liên kết: Google identity đã xác minh, email Google đã xác minh và khớp email nội bộ, `sub` chưa gắn User khác. Mỗi User tối đa một Google identity trong MVP.
- **Lý do và phương án đã cân nhắc:** Tránh chiếm tài khoản và tài khoản trùng. Đã loại: tự liên kết khi email trùng.
- **Hệ quả / công việc phát sinh:** Cần endpoint và UI liên kết. Chưa chốt: request, response, error code của linking.
- **Chạm ra ngoài Identity:** endpoint linking đi vào contract chung (PR contract).
- **Tài liệu, contract và test cần đổi:** `DAC-TA-NGHIEP-VU.md`, `KE-HOACH-KIEM-THU.md` (email trùng, sai mật khẩu, `sub` đã gắn User khác, email Google chưa xác minh).

**IDN-04 — Bảng `user_identities`; định danh Google bằng `sub`**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Cần lưu danh tính từ provider mà không nhét vào `users`.
- **Quyết định:** Thêm bảng `user_identities` (`id`, `user_id`, `provider`, `provider_subject`, `provider_email` nullable, `created_at`). Định danh Google bằng `sub`, không dùng email. UNIQUE `(provider, provider_subject)` và UNIQUE `(user_id, provider)`. Không lưu Google token.
- **Lý do và phương án đã cân nhắc:** Tách danh tính provider khỏi User. Đã loại: lưu Google identity trong `users`.
- **Hệ quả / công việc phát sinh:** Migration `0002_identity_auth_schema` tạo bảng. Race khi liên kết dựa vào UNIQUE rồi bắt `IntegrityError`, không check-then-insert. Chi tiết cột, CHECK và tên constraint ở `MO-TA-HE-THONG.md` (F.2, F.3, F.3A).
- **Chạm ra ngoài Identity:** cập nhật `MO-TA-HE-THONG.md` (bảng `identity_db`, quan hệ F.1, mục mới F.3A) là sửa file chung, theo DEC-09 không để hai bản song song.
- **Tài liệu, contract và test cần đổi:** test DB cho hai UNIQUE, CHECK `provider` và FK RESTRICT.

**IDN-05 — `users.password_hash` nullable**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Tài khoản tạo bằng Google không có mật khẩu.
- **Quyết định:** `password_hash` cho phép NULL. Quy tắc "có password hoặc có ít nhất một identity" enforce bằng application validation, không dùng trigger và không CHECK xuyên bảng.
- **Lý do và phương án đã cân nhắc:** CHECK của PostgreSQL không tham chiếu bảng khác; trigger làm MVP nặng thêm. Đã loại: trigger hoặc CHECK xuyên bảng.
- **Hệ quả / công việc phát sinh:** Register luôn yêu cầu mật khẩu. Google signup tạo `users` và `user_identities` trong cùng một transaction. Login Email/Password với `password_hash` NULL phải trả lỗi chung. Cần test chứng minh invariant.
- **Chạm ra ngoài Identity:** sửa F.2 trong `MO-TA-HE-THONG.md`.
- **Tài liệu, contract và test cần đổi:** test application cho invariant; xem thêm IDN-11.

**IDN-06 — Access Token JWT RS256, TTL 15 phút**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Cần định dạng Access Token ngắn hạn.
- **Quyết định:** JWT ký RS256, TTL 15 phút, private key chỉ thuộc Identity. Quyết định này không chốt service nào verify token.
- **Lý do và phương án đã cân nhắc:** Theo quyết định RS256 đã duyệt trước đó. Topology verify để ngoài để không đụng DEC-14, nơi Inventory hiện xác minh qua `GET /api/v1/users/me`.
- **Hệ quả / công việc phát sinh:** Access Token đã phát hành còn hiệu lực đến `exp` (mục G). Cần thư viện ký JWT: chưa thêm dependency, chờ duyệt. Chưa có tên biến cấu hình key và issuer.
- **Chạm ra ngoài Identity:** `GET /users/me` phải tiếp tục trả `id`, `role`, `status` với ngữ nghĩa 401/403 đúng, vì Inventory phụ thuộc (`upstreams.py`, `require_admin`). Không thay đổi hành vi này nếu chưa thông báo. Nếu sau này service khác muốn tự verify JWT thì public key và claims trở thành contract và phải đi qua file chung.
- **Tài liệu, contract và test cần đổi:** `MO-TA-HE-THONG.md` mục G, test JWT (hết hạn, sai chữ ký, sai key) và test tương thích `/users/me`.

**IDN-07 — Refresh Token opaque, chỉ lưu hash, rotation và reuse detection theo family**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Cần phiên dài hạn an toàn, thu hồi được.
- **Quyết định:** Refresh Token là chuỗi ngẫu nhiên opaque; DB chỉ lưu SHA-256 hex (64 ký tự). Mỗi lần login tạo family mới. Rotation tạo record mới, không ghi đè. Xuất trình lại token đã rotate thì revoke cả family (reuse detection). Logout revoke family. Disable User revoke các session của User; User DISABLED không login và không refresh. Rotation chạy trong một transaction với `SELECT ... FOR UPDATE`, kèm partial unique index một family chỉ có một record chưa revoke.
- **Lý do và phương án đã cân nhắc:** Giảm thiệt hại khi lộ token, phát hiện đánh cắp. Không có grace window: hai request refresh song song cùng token sẽ bị coi là reuse, nên frontend phải single-flight (đã có trong `DAC-TA-NGHIEP-VU.md`).
- **Hệ quả / công việc phát sinh:** Thứ tự rotation: khóa record cũ, revoke, insert record mới, set `replaced_by_id`. Chi tiết schema (index, CHECK) ở `MO-TA-HE-THONG.md` F.3. Cách token đi qua cookie thuộc DEC-16 và DEC-17.
- **Tài liệu, contract và test cần đổi:** `MO-TA-HE-THONG.md` F.3, `KE-HOACH-KIEM-THU.md` (rotation, reuse, race, logout, disabled user).

**IDN-08 — Refresh TTL: idle 7 ngày, absolute 30 ngày**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Cần giới hạn tuổi thọ phiên kể cả khi người dùng hoạt động liên tục.
- **Quyết định:** Mỗi refresh token có idle TTL 7 ngày; mỗi family có absolute TTL 30 ngày. Thêm cột `family_expires_at`, bất biến trong family; `expires_at` không vượt `family_expires_at`.
- **Lý do và phương án đã cân nhắc:** Idle TTL tự trượt theo rotation nên cần mốc tuyệt đối để phiên không sống vô hạn.
- **Hệ quả / công việc phát sinh:** Record mới có `expires_at = min(now + 7 ngày, family_expires_at)`. DB có CHECK `expires_at <= family_expires_at`.
- **Chạm ra ngoài Identity:** sửa F.3 trong `MO-TA-HE-THONG.md`.
- **Tài liệu, contract và test cần đổi:** test hết hạn idle và absolute.

**IDN-09 — Giữ lịch sử refresh sau rotation; thời gian dọn theo cấu hình vận hành**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Reuse detection cần biết token đã rotate; nếu xóa ngay sẽ không phân biệt được token đã dùng với token không tồn tại.
- **Quyết định:** Không xóa record sau rotation. Thời gian lưu và cách dọn không cố định trong schema mà do cấu hình vận hành.
- **Lý do và phương án đã cân nhắc:** Cần cho reuse detection; chưa có yêu cầu lưu trữ dài hạn.
- **Hệ quả / công việc phát sinh:** Cần job dọn. Hướng thiết kế: xóa cả family khi `family_expires_at` đã qua mốc cắt (có index `ix_refresh_sessions_family_expires_at`). Self-FK `replaced_by_id` để NO ACTION để xóa cả chuỗi trong một câu lệnh và đã có test trong `tests/test_identity_models.py`.
- **Tài liệu, contract và test cần đổi:** test dọn family.

**IDN-10 — Hoãn xác minh email khi đăng ký khỏi MVP**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Xác minh email cần gửi mail, ngoài phạm vi MVP.
- **Quyết định:** Đăng ký không xác minh email trong MVP; sẽ gửi mail về email đăng ký sau MVP.
- **Lý do và phương án đã cân nhắc:** Giữ MVP gọn.
- **Hệ quả / công việc phát sinh:** Email nội bộ chưa được xác minh. Rủi ro: ai đó có thể đăng ký trước bằng email của người khác; khi chủ email đăng nhập Google, IDN-03 chặn thay vì gộp, nên không bị chiếm tài khoản nhưng bị kẹt. Cần ghi vào giới hạn MVP.
- **Tài liệu, contract và test cần đổi:** `MO-TA-HE-THONG.md` mục 8 (giới hạn MVP), `DAC-TA-NGHIEP-VU.md`.

**IDN-11 — Hoãn đặt mật khẩu cho tài khoản chỉ có Google khỏi MVP**

- **Ngày / người đề xuất / người duyệt:** 21/11/2026 / vq / vq
- **Trạng thái:** ACCEPTED
- **Bối cảnh và vấn đề:** Tài khoản chỉ có Google không có mật khẩu (IDN-05).
- **Quyết định:** MVP không có chức năng đặt mật khẩu cho tài khoản chỉ có Google. Tài khoản này chỉ đăng nhập bằng Google. Chức năng đặt mật khẩu làm sau MVP, kèm re-authentication.
- **Lý do và phương án đã cân nhắc:** Giữ MVP gọn, tránh mở thêm luồng nhạy cảm.
- **Hệ quả / công việc phát sinh:** Frontend phải xử lý trường hợp đăng nhập Email/Password vào tài khoản Google-only bằng lỗi chung.
- **Tài liệu, contract và test cần đổi:** `MO-TA-HE-THONG.md` mục 8, `KE-HOACH-KIEM-THU.md`.
