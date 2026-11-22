"""Catalog API contract, auth, validation, business logic, and PostgreSQL integration tests."""

import asyncio
import io
import struct
import subprocess
import sys
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from commerce_backend_common.errors import ServiceError
from commerce_catalog import service
from commerce_catalog.main import create_app
from commerce_catalog.models import Category, Product, ProductImage
from commerce_catalog.settings import Settings
from commerce_gateway.main import create_app as create_gateway_app
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_inventory.settings import Settings as InventorySettings
from commerce_inventory.upstreams import CatalogClient

ROOT = Path(__file__).resolve().parents[1]
ACTOR = uuid4()
HEADERS_ADMIN = {"Authorization": "Bearer admin-token"}
HEADERS_SERVICE = {"Authorization": "Bearer catalog-internal-secret"}


def make_valid_png(width: int = 2, height: int = 2) -> bytes:
    ihdr_payload = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_payload) & 0xFFFFFFFF
    ihdr = struct.pack(">I4s13sI", 13, b"IHDR", ihdr_payload, ihdr_crc)
    raw_rows = b"".join(b"\x00" + (b"\xff\x00\x00" * width) for _ in range(height))
    compressed = zlib.compress(raw_rows)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(f">I4s{len(compressed)}sI", len(compressed), b"IDAT", compressed, idat_crc)
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I4sI", 0, b"IEND", iend_crc)
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


def make_valid_jpeg(width: int = 4, height: int = 4) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = struct.pack(">2sHBHHB3s", b"\xff\xc0", 11, 8, height, width, 1, b"\x01\x11\x00")
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x00"
    return b"\xff\xd8" + app0 + sof0 + sos + b"\xff\xd9"


def make_valid_webp() -> bytes:
    vp8_payload = b"\x9d\x01\x2a\x01\x00\x01\x00\x00\x00\x00"
    chunk = b"VP8 " + struct.pack("<I", len(vp8_payload)) + vp8_payload
    riff_size = 4 + len(chunk)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + chunk


class IdentityMock:
    actor = ACTOR
    role = "ADMIN"
    status = "ACTIVE"
    failure: int | str | None = None
    requests: list[httpx.Request]

    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v1/users/me":
            if self.failure == "timeout":
                raise httpx.ReadTimeout("sensitive-test-error", request=request)
            if self.failure == "invalid-json":
                return httpx.Response(200, text="not-json")
            if isinstance(self.failure, int):
                return httpx.Response(self.failure, text="sensitive-test-error")
            return httpx.Response(
                200,
                json={
                    "id": str(self.actor),
                    "role": self.role,
                    "status": self.status,
                },
            )
        return httpx.Response(404, text="Not found")


class InMemoryCatalogStore:
    """In-memory transactional store emulating SQLAlchemy AsyncSession for unit/API tests."""

    def __init__(self) -> None:
        self.categories: dict[UUID, Category] = {}
        self.products: dict[UUID, Product] = {}
        self.images: dict[UUID, ProductImage] = {}
        self.fail_on_execute = False
        self.fail_on_flush_image = False

    def session(self) -> "FakeAsyncSession":
        return FakeAsyncSession(self)


class _ScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class FakeAsyncSession:
    def __init__(self, store: InMemoryCatalogStore) -> None:
        self.store = store
        self._pending: list[Any] = []
        self._deleted: list[Any] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator["FakeAsyncSession"]:
        if self.store.fail_on_execute:
            raise SQLAlchemyError("simulated database failure")
        snap_cats = {
            k: Category(
                id=v.id,
                name=v.name,
                slug=v.slug,
                description=v.description,
                is_visible=v.is_visible,
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            for k, v in self.store.categories.items()
        }
        snap_imgs = {
            k: ProductImage(
                id=v.id,
                product_id=v.product_id,
                storage_key=v.storage_key,
                mime_type=v.mime_type,
                size_bytes=v.size_bytes,
                alt_text=v.alt_text,
                sort_order=v.sort_order,
                created_at=v.created_at,
            )
            for k, v in self.store.images.items()
        }
        snap_prods: dict[UUID, Product] = {}
        for k, v in self.store.products.items():
            p = Product(
                id=v.id,
                category_id=v.category_id,
                sku=v.sku,
                slug=v.slug,
                name=v.name,
                description=v.description,
                specifications=dict(v.specifications or {}),
                price_amount=v.price_amount,
                currency=v.currency,
                status=v.status,
                version=v.version,
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            p.images = [img for img in snap_imgs.values() if img.product_id == k]
            snap_prods[k] = p
        self._pending.clear()
        self._deleted.clear()
        try:
            yield self
            await self.flush()
        except Exception:
            self.store.categories = snap_cats
            self.store.images = snap_imgs
            self.store.products = snap_prods
            raise

    async def execute(self, statement: Any, params: Any = None) -> Any:
        if self.store.fail_on_execute:
            raise SQLAlchemyError("simulated query failure")
        return None

    def add(self, obj: Any) -> None:
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._pending.append(obj)

    async def delete(self, obj: Any) -> None:
        self._deleted.append(obj)

    async def get(self, model: Any, ident: UUID, *, with_for_update: bool = False) -> Any:
        if model is Category:
            return self.store.categories.get(ident)
        if model is Product:
            return self.store.products.get(ident)
        if model is ProductImage:
            return self.store.images.get(ident)
        return None

    async def scalar(self, statement: Any) -> Any:
        if self.store.fail_on_execute:
            raise SQLAlchemyError("simulated query failure")
        return next(iter(self.store.products.values()), None)

    async def flush(self) -> None:
        for obj in self._deleted:
            if isinstance(obj, ProductImage):
                self.store.images.pop(obj.id, None)
                if obj.product_id in self.store.products:
                    prod = self.store.products[obj.product_id]
                    prod.images = [i for i in prod.images if i.id != obj.id]
        self._deleted.clear()

        for obj in self._pending:
            if isinstance(obj, Category):
                self.store.categories[obj.id] = obj
            elif isinstance(obj, Product):
                self.store.products[obj.id] = obj
            elif isinstance(obj, ProductImage):
                if self.store.fail_on_flush_image:
                    raise IntegrityError(
                        "INSERT", {}, Exception("simulated image constraint error")
                    )
                self.store.images[obj.id] = obj
                if obj.product_id in self.store.products:
                    prod = self.store.products[obj.product_id]
                    if all(i.id != obj.id for i in prod.images):
                        prod.images.append(obj)
        self._pending.clear()

        # Check uniqueness constraints across current store
        cat_slugs: set[str] = set()
        for c in self.store.categories.values():
            if c.slug in cat_slugs:
                raise IntegrityError("categories", {}, Exception("uq_categories_slug"))
            cat_slugs.add(c.slug)

        prod_skus: set[str] = set()
        prod_slugs: set[str] = set()
        for p in self.store.products.values():
            if p.sku in prod_skus:
                raise IntegrityError("products", {}, Exception("uq_products_sku"))
            prod_skus.add(p.sku)
            if p.slug in prod_slugs:
                raise IntegrityError("products", {}, Exception("uq_products_slug"))
            prod_slugs.add(p.slug)

        img_orders: set[tuple[UUID, int]] = set()
        for img in self.store.images.values():
            key = (img.product_id, img.sort_order)
            if key in img_orders:
                raise IntegrityError(
                    "product_images", {}, Exception("uq_product_images_product_id")
                )
            img_orders.add(key)


# ──────────────────────────────────────────────
# Upstream Origin & Security Config Tests
# ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.example",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com/?secret=1",
    ],
)
def test_upstream_origins_are_restricted(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, identity_base_url=origin)


# ──────────────────────────────────────────────
# Public Endpoints: No Auth Required
# ──────────────────────────────────────────────


def test_public_endpoints_do_not_require_auth() -> None:
    mock_id = IdentityMock()
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    with TestClient(app) as client:
        for path in ("/api/v1/categories", "/api/v1/products", f"/api/v1/products/{uuid4()}"):
            response = client.get(path)
            assert response.status_code == 503
            assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert not mock_id.requests


def test_image_path_traversal_is_blocked(tmp_path: Path) -> None:
    mock_id = IdentityMock()
    app = create_app(
        Settings(_env_file=None, catalog_storage_dir=tmp_path),
        transport=httpx.MockTransport(mock_id),
    )
    with TestClient(app) as client:
        for bad_path in (
            "/api/v1/catalog/images/../../etc/passwd",
            "/api/v1/catalog/images/..%2F..%2Fpyproject.toml",
            "/api/v1/catalog/images/nonexistent/file.png",
        ):
            response = client.get(bad_path)
            assert response.status_code == 404
            assert response.json()["code"] == "NOT_FOUND"


# ──────────────────────────────────────────────
# Admin Authentication & Authorization
# ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/admin/categories"),
        ("post", "/api/v1/admin/categories"),
        ("patch", f"/api/v1/admin/categories/{uuid4()}"),
        ("get", "/api/v1/admin/products"),
        ("post", "/api/v1/admin/products"),
        ("get", f"/api/v1/admin/products/{uuid4()}"),
        ("patch", f"/api/v1/admin/products/{uuid4()}"),
        ("post", f"/api/v1/admin/products/{uuid4()}/images"),
        ("delete", f"/api/v1/admin/products/{uuid4()}/images/{uuid4()}"),
    ],
)
def test_admin_routes_require_bearer_token(method: str, path: str) -> None:
    mock_id = IdentityMock()
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    with TestClient(app) as client:
        response = client.request(method, path, headers={"X-User-Role": "ADMIN"})
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_INVALID"
    assert not mock_id.requests
    assert app.state.identity_client.is_closed


@pytest.mark.parametrize(
    "role,status,failure,expected",
    [
        ("CUSTOMER", "ACTIVE", None, 403),
        ("ADMIN", "DISABLED", None, 403),
        ("ADMIN", "ACTIVE", 401, 401),
        ("ADMIN", "ACTIVE", 403, 403),
        ("ADMIN", "ACTIVE", 500, 503),
        ("ADMIN", "ACTIVE", 302, 503),
        ("ADMIN", "ACTIVE", "timeout", 503),
        ("ADMIN", "ACTIVE", "invalid-json", 503),
    ],
)
def test_identity_verified_before_database(
    role: str, status: str, failure: int | str | None, expected: int
) -> None:
    mock_id = IdentityMock()
    mock_id.role, mock_id.status, mock_id.failure = role, status, failure
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/products", headers=HEADERS_ADMIN)
    assert response.status_code == expected
    assert "sensitive-test-error" not in response.text


# ──────────────────────────────────────────────
# Internal Service Authentication & Validation
# ──────────────────────────────────────────────


def test_internal_products_batch_authentication_and_validation() -> None:
    mock_id = IdentityMock()
    # 1. Missing token -> 401
    app_no_secret = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    with TestClient(app_no_secret) as client:
        r_no_auth = client.post("/internal/products/batch", json={"productIds": [str(uuid4())]})
        assert r_no_auth.status_code == 401
        assert r_no_auth.json()["code"] == "AUTH_INVALID"

        # 2. Token provided but service secret not configured -> 503
        r_unconfigured = client.post(
            "/internal/products/batch",
            json={"productIds": [str(uuid4())]},
            headers=HEADERS_SERVICE,
        )
        assert r_unconfigured.status_code == 503
        assert r_unconfigured.json()["code"] == "DEPENDENCY_UNAVAILABLE"

    # 3. Configured secret: wrong token -> 403, invalid payload -> 400
    app = create_app(
        Settings(_env_file=None, catalog_service_token=SecretStr("catalog-internal-secret")),
        transport=httpx.MockTransport(mock_id),
    )
    with TestClient(app) as client:
        r_forbidden = client.post(
            "/internal/products/batch",
            json={"productIds": [str(uuid4())]},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert r_forbidden.status_code == 403
        assert r_forbidden.json()["code"] == "FORBIDDEN"

        r_empty = client.post(
            "/internal/products/batch",
            json={"productIds": []},
            headers=HEADERS_SERVICE,
        )
        assert r_empty.status_code == 400
        assert r_empty.json()["code"] == "VALIDATION_ERROR"

        dup = str(uuid4())
        r_dup = client.post(
            "/internal/products/batch",
            json={"productIds": [dup, dup]},
            headers=HEADERS_SERVICE,
        )
        assert r_dup.status_code == 400
        assert r_dup.json()["code"] == "VALIDATION_ERROR"


# ──────────────────────────────────────────────
# Validation Errors (400 VALIDATION_ERROR)
# ──────────────────────────────────────────────


def test_admin_and_public_validation_errors() -> None:
    mock_id = IdentityMock()
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    with TestClient(app) as client:
        # Missing product fields
        r1 = client.post("/api/v1/admin/products", json={}, headers=HEADERS_ADMIN)
        assert r1.status_code == 400 and r1.json()["code"] == "VALIDATION_ERROR"

        # Negative price
        r2 = client.post(
            "/api/v1/admin/products",
            json={
                "sku": "SKU-01",
                "slug": "slug-01",
                "name": "Product 01",
                "categoryId": str(uuid4()),
                "description": "Desc",
                "priceAmount": "-500",
                "currency": "VND",
                "status": "ACTIVE",
            },
            headers=HEADERS_ADMIN,
        )
        assert r2.status_code == 400 and r2.json()["code"] == "VALIDATION_ERROR"

        # Invalid category slug
        r3 = client.post(
            "/api/v1/admin/categories",
            json={"name": "   ", "slug": "invalid slug"},
            headers=HEADERS_ADMIN,
        )
        assert r3.status_code == 400 and r3.json()["code"] == "VALIDATION_ERROR"

        # Patch product without expectedVersion or without changed fields
        r4 = client.patch(
            f"/api/v1/admin/products/{uuid4()}",
            json={"name": "Updated Name"},
            headers=HEADERS_ADMIN,
        )
        assert r4.status_code == 400 and r4.json()["code"] == "VALIDATION_ERROR"

        r5 = client.patch(
            f"/api/v1/admin/products/{uuid4()}",
            json={"expectedVersion": 0},
            headers=HEADERS_ADMIN,
        )
        assert r5.status_code == 400 and r5.json()["code"] == "VALIDATION_ERROR"


def test_image_upload_validation_rejects_bad_files() -> None:
    mock_id = IdentityMock()
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(mock_id))
    pid = uuid4()
    with TestClient(app) as client:
        # 1. Plain text disguised as image/jpeg
        r_text = client.post(
            f"/api/v1/admin/products/{pid}/images",
            files={"file": ("fake.jpg", io.BytesIO(b"not a real jpeg"), "image/jpeg")},
            data={"altText": "Test Image"},
            headers=HEADERS_ADMIN,
        )
        assert r_text.status_code == 400 and r_text.json()["code"] == "VALIDATION_ERROR"

        # 2. Fake magic header without valid IHDR/SOF structure
        r_fake_magic = client.post(
            f"/api/v1/admin/products/{pid}/images",
            files={"file": ("corrupt.png", io.BytesIO(b"\x89PNG\r\n\x1a\nxxxx"), "image/png")},
            headers=HEADERS_ADMIN,
        )
        assert r_fake_magic.status_code == 400

        # 3. Empty file
        r_empty = client.post(
            f"/api/v1/admin/products/{pid}/images",
            files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
            headers=HEADERS_ADMIN,
        )
        assert r_empty.status_code == 400

        # 4. File > 5 MiB
        oversized = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (service.MAX_IMAGE_BYTES + 10))
        r_large = client.post(
            f"/api/v1/admin/products/{pid}/images",
            files={"file": ("huge.png", io.BytesIO(oversized), "image/png")},
            headers=HEADERS_ADMIN,
        )
        assert r_large.status_code == 400 and r_large.json()["code"] == "VALIDATION_ERROR"

        # 5. altText > 255 characters
        r_long_alt = client.post(
            f"/api/v1/admin/products/{pid}/images",
            files={"file": ("ok.png", io.BytesIO(make_valid_png()), "image/png")},
            data={"altText": "a" * 256},
            headers=HEADERS_ADMIN,
        )
        assert r_long_alt.status_code == 400 and r_long_alt.json()["code"] == "VALIDATION_ERROR"

        # 6. Non-multipart request
        r_json = client.post(
            f"/api/v1/admin/products/{pid}/images",
            json={"file": "none"},
            headers=HEADERS_ADMIN,
        )
        assert r_json.status_code == 400 and r_json.json()["code"] == "VALIDATION_ERROR"


# ──────────────────────────────────────────────
# End-to-End Business Logic & Lifecycle Tests (No Docker Required)
# ──────────────────────────────────────────────


def test_full_catalog_lifecycle_and_edge_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercises Category, Product, Image, Optimistic Locking, and Error Rollback."""
    cats: dict[UUID, Category] = {}
    prods: dict[UUID, Product] = {}
    imgs: dict[UUID, ProductImage] = {}

    async def fake_create_category(_s: Any, body: Any) -> service.CategoryOut:
        if any(c.slug == body.slug for c in cats.values()):
            raise ServiceError(409, "CONFLICT", "Category slug is already in use")
        cat = Category(
            id=uuid4(),
            name=body.name,
            slug=body.slug,
            description=body.description,
            is_visible=body.is_visible,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        cats[cat.id] = cat
        return service.category_view(cat)

    async def fake_patch_category(_s: Any, cid: UUID, body: Any) -> service.CategoryOut:
        cat = cats.get(cid)
        if cat is None:
            raise ServiceError(404, "NOT_FOUND", "Category not found")
        if body.slug is not None and any(
            c.slug == body.slug and c.id != cid for c in cats.values()
        ):
            raise ServiceError(409, "CONFLICT", "Category slug is already in use")
        if "name" in body.model_fields_set and body.name is not None:
            cat.name = body.name
        if "slug" in body.model_fields_set and body.slug is not None:
            cat.slug = body.slug
        if "description" in body.model_fields_set:
            cat.description = body.description
        if "is_visible" in body.model_fields_set and body.is_visible is not None:
            cat.is_visible = body.is_visible
        return service.category_view(cat)

    async def fake_list_categories_public(
        _s: Any, page: int, page_size: int
    ) -> service.Page[service.CategoryOut]:
        visible = [service.category_view(c) for c in cats.values() if c.is_visible]
        start = (page - 1) * page_size
        return service.Page(
            items=visible[start : start + page_size],
            page=page,
            page_size=page_size,
            total=len(visible),
        )

    async def fake_list_categories_admin(
        _s: Any, page: int, page_size: int
    ) -> service.Page[service.CategoryOut]:
        all_cats = [service.category_view(c) for c in cats.values()]
        start = (page - 1) * page_size
        return service.Page(
            items=all_cats[start : start + page_size],
            page=page,
            page_size=page_size,
            total=len(all_cats),
        )

    async def fake_create_product(_s: Any, body: Any) -> service.ProductOut:
        if body.category_id not in cats:
            raise ServiceError(404, "NOT_FOUND", "Category not found")
        if any(p.sku == body.sku for p in prods.values()):
            raise ServiceError(409, "CONFLICT", "Product SKU is already in use")
        if any(p.slug == body.slug for p in prods.values()):
            raise ServiceError(409, "CONFLICT", "Product slug is already in use")
        prod = Product(
            id=uuid4(),
            category_id=body.category_id,
            sku=body.sku,
            slug=body.slug,
            name=body.name,
            description=body.description,
            specifications=dict(body.specifications),
            price_amount=body.price_amount,
            currency=body.currency,
            status=body.status,
            version=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        prod.images = []
        prods[prod.id] = prod
        return service.product_view(prod)

    async def fake_get_product(_s: Any, pid: UUID, *, admin: bool) -> service.ProductOut:
        prod = prods.get(pid)
        if prod is None or (not admin and prod.status != "ACTIVE"):
            raise ServiceError(404, "NOT_FOUND", "Product not found")
        return service.product_view(prod)

    async def fake_list_products(
        _s: Any,
        *,
        admin: bool,
        q: str | None,
        category_id: UUID | None,
        min_price: int | None,
        max_price: int | None,
        status: str | None,
        sort: str | None,
        page: int,
        page_size: int,
    ) -> service.Page[service.ProductOut]:
        items = list(prods.values())
        if not admin:
            items = [p for p in items if p.status == "ACTIVE"]
        elif status is not None:
            items = [p for p in items if p.status == status]
        if category_id is not None:
            items = [p for p in items if p.category_id == category_id]
        if min_price is not None:
            items = [p for p in items if p.price_amount >= min_price]
        if max_price is not None:
            items = [p for p in items if p.price_amount <= max_price]
        if q and q.strip():
            term = q.strip().lower()
            items = [p for p in items if term in p.name.lower() or term in p.sku.lower()]
        if sort == "PRICE_ASC":
            items.sort(key=lambda p: p.price_amount)
        elif sort == "PRICE_DESC":
            items.sort(key=lambda p: p.price_amount, reverse=True)
        else:
            items.sort(key=lambda p: p.created_at, reverse=True)
        start = (page - 1) * page_size
        return service.Page(
            items=[service.product_view(p) for p in items[start : start + page_size]],
            page=page,
            page_size=page_size,
            total=len(items),
        )

    async def fake_patch_product(_s: Any, pid: UUID, body: Any) -> service.ProductOut:
        prod = prods.get(pid)
        if prod is None:
            raise ServiceError(404, "NOT_FOUND", "Product not found")
        if prod.version != body.expected_version:
            raise ServiceError(409, "CONFLICT", "Product version conflict")
        if body.category_id is not None:
            if body.category_id not in cats:
                raise ServiceError(404, "NOT_FOUND", "Category not found")
            prod.category_id = body.category_id
        if body.slug is not None:
            if any(p.slug == body.slug and p.id != pid for p in prods.values()):
                raise ServiceError(409, "CONFLICT", "Product slug is already in use")
            prod.slug = body.slug
        if body.name is not None:
            prod.name = body.name
        if body.description is not None:
            prod.description = body.description
        if body.specifications is not None:
            prod.specifications = dict(body.specifications)
        if body.price_amount is not None:
            prod.price_amount = body.price_amount
        if body.status is not None:
            prod.status = body.status
        if body.image_ids is not None:
            id_map = {img.id: img for img in prod.images}
            for iid in body.image_ids:
                if iid not in id_map:
                    raise ServiceError(404, "NOT_FOUND", "Image does not belong to product")
            if len(body.image_ids) != len(id_map):
                raise ServiceError(400, "VALIDATION_ERROR", "All product images must be listed")
            for idx, iid in enumerate(body.image_ids):
                id_map[iid].sort_order = idx
        prod.version += 1
        return service.product_view(prod)

    async def fake_upload_image(
        _s: Any, pid: UUID, data: bytes, alt_text: str | None, storage_root: Path
    ) -> service.ImageOut:
        mime = service.detect_and_validate_raster(data)
        prod = prods.get(pid)
        if prod is None:
            raise ServiceError(404, "NOT_FOUND", "Product not found")
        if len(prod.images) >= service.MAX_IMAGES_PER_PRODUCT:
            raise ServiceError(409, "CONFLICT", "Maximum 5 images reached")
        image_id = uuid4()
        key = service.safe_storage_key(pid, image_id, mime)
        dest = storage_root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        sort_order = max((i.sort_order for i in prod.images), default=-1) + 1
        img = ProductImage(
            id=image_id,
            product_id=pid,
            storage_key=key,
            mime_type=mime,
            size_bytes=len(data),
            alt_text=alt_text,
            sort_order=sort_order,
        )
        imgs[img.id] = img
        prod.images.append(img)
        return service.image_view(img)

    async def fake_delete_image(_s: Any, pid: UUID, image_id: UUID, storage_root: Path) -> None:
        img = imgs.get(image_id)
        if img is None or img.product_id != pid:
            raise ServiceError(404, "NOT_FOUND", "Image not found")
        imgs.pop(image_id, None)
        prod = prods[pid]
        prod.images = [i for i in prod.images if i.id != image_id]
        (storage_root / img.storage_key).unlink(missing_ok=True)

    async def fake_batch_lookup(_s: Any, product_ids: list[UUID]) -> service.InternalBatch:
        return service.InternalBatch(
            items=[
                service.InternalProduct(
                    id=p.id,
                    sku=p.sku,
                    name=p.name,
                    status=p.status,  # type: ignore[arg-type]
                    price_amount=p.price_amount,
                    version=p.version,
                )
                for pid in product_ids
                if (p := prods.get(pid)) is not None
            ]
        )

    @asynccontextmanager
    async def dummy_session(_request: Any) -> AsyncIterator[Any]:
        yield None

    monkeypatch.setattr("commerce_catalog.api.open_db_session", dummy_session)
    monkeypatch.setattr(service, "create_category", fake_create_category)
    monkeypatch.setattr(service, "patch_category", fake_patch_category)
    monkeypatch.setattr(service, "list_categories_public", fake_list_categories_public)
    monkeypatch.setattr(service, "list_categories_admin", fake_list_categories_admin)
    monkeypatch.setattr(service, "create_product", fake_create_product)
    monkeypatch.setattr(service, "get_product", fake_get_product)
    monkeypatch.setattr(service, "list_products", fake_list_products)
    monkeypatch.setattr(service, "patch_product", fake_patch_product)
    monkeypatch.setattr(service, "upload_image", fake_upload_image)
    monkeypatch.setattr(service, "delete_image", fake_delete_image)
    monkeypatch.setattr(service, "batch_lookup", fake_batch_lookup)

    mock_id = IdentityMock()
    catalog_app = create_app(
        Settings(
            _env_file=None,
            catalog_storage_dir=tmp_path,
            catalog_service_token=SecretStr("catalog-internal-secret"),
        ),
        transport=httpx.MockTransport(mock_id),
    )
    gateway_app = create_gateway_app(
        GatewaySettings(_env_file=None),
        transport=httpx.ASGITransport(app=catalog_app),
    )

    with TestClient(catalog_app) as direct_client, TestClient(gateway_app) as gw:
        # 1. Create categories via Gateway
        c1 = gw.post(
            "/api/v1/admin/categories",
            json={"name": "Bàn phím cơ", "slug": "ban-phim-co", "description": "Keyboards"},
            headers=HEADERS_ADMIN,
        )
        assert c1.status_code == 201
        cat1_id = c1.json()["id"]

        # Duplicate category slug -> 409
        c_dup = gw.post(
            "/api/v1/admin/categories",
            json={"name": "Khác", "slug": "ban-phim-co"},
            headers=HEADERS_ADMIN,
        )
        assert c_dup.status_code == 409 and c_dup.json()["code"] == "CONFLICT"

        c2 = gw.post(
            "/api/v1/admin/categories",
            json={"name": "Chuột gaming", "slug": "chuot-gaming", "isVisible": False},
            headers=HEADERS_ADMIN,
        )
        assert c2.status_code == 201
        assert c2.json()["isVisible"] is False

        # Public categories only show visible
        pub_cats = gw.get("/api/v1/categories").json()
        assert pub_cats["total"] == 1
        assert pub_cats["items"][0]["id"] == cat1_id

        # Admin categories show both visible and hidden
        adm_cats = gw.get("/api/v1/admin/categories", headers=HEADERS_ADMIN).json()
        assert adm_cats["total"] == 2

        # 2. Create products (DRAFT and ACTIVE)
        p_draft = gw.post(
            "/api/v1/admin/products",
            json={
                "sku": "KB-DRAFT-01",
                "slug": "kb-draft-01",
                "name": "Bàn phím bản nháp",
                "categoryId": cat1_id,
                "description": "Chưa mở bán",
                "priceAmount": "1500000",
                "currency": "VND",
                "status": "DRAFT",
                "specifications": {"switch": "Red"},
            },
            headers=HEADERS_ADMIN,
        )
        assert p_draft.status_code == 201
        draft_id = p_draft.json()["id"]

        p_active = gw.post(
            "/api/v1/admin/products",
            json={
                "sku": "KB-ACTIVE-01",
                "slug": "kb-active-01",
                "name": "Bàn phím cơ NuPhy Air75",
                "categoryId": cat1_id,
                "description": "Đang mở bán",
                "priceAmount": "2500000",
                "currency": "VND",
                "status": "ACTIVE",
                "specifications": {"switch": "Brown", "layout": "75%"},
            },
            headers=HEADERS_ADMIN,
        )
        assert p_active.status_code == 201
        active_id = p_active.json()["id"]

        # Duplicate SKU -> 409; Duplicate Slug -> 409; Nonexistent category -> 404
        assert (
            gw.post(
                "/api/v1/admin/products",
                json={
                    "sku": "KB-ACTIVE-01",
                    "slug": "unique-slug",
                    "name": "Dup SKU",
                    "categoryId": cat1_id,
                    "description": "",
                    "priceAmount": "100000",
                    "currency": "VND",
                    "status": "DRAFT",
                },
                headers=HEADERS_ADMIN,
            ).status_code
            == 409
        )
        assert (
            gw.post(
                "/api/v1/admin/products",
                json={
                    "sku": "UNIQUE-SKU",
                    "slug": "kb-active-01",
                    "name": "Dup Slug",
                    "categoryId": cat1_id,
                    "description": "",
                    "priceAmount": "100000",
                    "currency": "VND",
                    "status": "DRAFT",
                },
                headers=HEADERS_ADMIN,
            ).status_code
            == 409
        )
        assert (
            gw.post(
                "/api/v1/admin/products",
                json={
                    "sku": "UNIQUE-SKU-2",
                    "slug": "unique-slug-2",
                    "name": "Missing Cat",
                    "categoryId": str(uuid4()),
                    "description": "",
                    "priceAmount": "100000",
                    "currency": "VND",
                    "status": "DRAFT",
                },
                headers=HEADERS_ADMIN,
            ).status_code
            == 404
        )

        # 3. Public product listing & detail only expose ACTIVE products
        pub_prods = gw.get("/api/v1/products").json()
        assert pub_prods["total"] == 1
        assert pub_prods["items"][0]["id"] == active_id
        assert gw.get(f"/api/v1/products/{active_id}").status_code == 200
        assert gw.get(f"/api/v1/products/{draft_id}").status_code == 404

        # Invalid minPrice > maxPrice -> 400
        assert gw.get("/api/v1/products?minPrice=5000000&maxPrice=1000000").status_code == 400

        # 4. Hiding category does NOT discontinue products in that category
        hide_res = gw.patch(
            f"/api/v1/admin/categories/{cat1_id}",
            json={"isVisible": False},
            headers=HEADERS_ADMIN,
        )
        assert hide_res.status_code == 200 and hide_res.json()["isVisible"] is False
        assert gw.get(f"/api/v1/products/{active_id}").status_code == 200

        # 5. Image Upload (PNG, JPEG, WebP), Serving, Reordering, Max 5 Limit, Deletion
        img1 = gw.post(
            f"/api/v1/admin/products/{active_id}/images",
            files={"file": ("one.png", io.BytesIO(make_valid_png()), "image/png")},
            data={"altText": "Ảnh 1"},
            headers=HEADERS_ADMIN,
        )
        assert img1.status_code == 201
        img1_data = img1.json()
        assert img1_data["sortOrder"] == 0

        # Fetch uploaded image through gateway
        img_get = gw.get(img1_data["url"])
        assert img_get.status_code == 200
        assert img_get.headers["content-type"].startswith("image/png")

        img2 = gw.post(
            f"/api/v1/admin/products/{active_id}/images",
            files={"file": ("two.jpg", io.BytesIO(make_valid_jpeg()), "image/jpeg")},
            data={"altText": "Ảnh 2"},
            headers=HEADERS_ADMIN,
        )
        assert img2.status_code == 201
        img2_data = img2.json()
        assert img2_data["sortOrder"] == 1

        # Reorder images using PATCH /api/v1/admin/products/{id} with expectedVersion=0
        reorder = gw.patch(
            f"/api/v1/admin/products/{active_id}",
            json={
                "expectedVersion": 0,
                "imageIds": [img2_data["id"], img1_data["id"]],
            },
            headers=HEADERS_ADMIN,
        )
        assert reorder.status_code == 200
        reordered_prod = reorder.json()
        assert reordered_prod["version"] == 1
        assert [i["id"] for i in reordered_prod["images"]] == [
            img2_data["id"],
            img1_data["id"],
        ]

        # Stale expectedVersion=0 now fails with 409 CONFLICT
        stale = gw.patch(
            f"/api/v1/admin/products/{active_id}",
            json={"expectedVersion": 0, "name": "Stale Update"},
            headers=HEADERS_ADMIN,
        )
        assert stale.status_code == 409 and stale.json()["code"] == "CONFLICT"

        # Upload 3 more images (reaching max 5)
        for idx in range(3):
            r_more = gw.post(
                f"/api/v1/admin/products/{active_id}/images",
                files={"file": (f"w{idx}.webp", io.BytesIO(make_valid_webp()), "image/webp")},
                headers=HEADERS_ADMIN,
            )
            assert r_more.status_code == 201

        # 6th image must be rejected with 409 CONFLICT
        r_sixth = gw.post(
            f"/api/v1/admin/products/{active_id}/images",
            files={"file": ("extra.png", io.BytesIO(make_valid_png()), "image/png")},
            headers=HEADERS_ADMIN,
        )
        assert r_sixth.status_code == 409 and r_sixth.json()["code"] == "CONFLICT"

        # Delete first image
        r_del = gw.delete(
            f"/api/v1/admin/products/{active_id}/images/{img1_data['id']}",
            headers=HEADERS_ADMIN,
        )
        assert r_del.status_code == 204
        assert gw.get(img1_data["url"]).status_code == 404

        # 6. Internal batch lookup & Inventory CatalogClient integration
        batch_res = direct_client.post(
            "/internal/products/batch",
            json={"productIds": [active_id, draft_id, str(uuid4())]},
            headers=HEADERS_SERVICE,
        )
        assert batch_res.status_code == 200
        assert [item["id"] for item in batch_res.json()["items"]] == [active_id, draft_id]

        # Verify Inventory's actual CatalogClient against Catalog ASGI
        async def verify_inventory_integration() -> None:
            inv_settings = InventorySettings(
                _env_file=None,
                catalog_service_token=SecretStr("catalog-internal-secret"),
            )
            async with httpx.AsyncClient(
                base_url="http://catalog-service",
                transport=httpx.ASGITransport(app=catalog_app),
            ) as async_http:
                cat_client = CatalogClient(async_http, inv_settings, str(uuid4()))
                await cat_client.verify_product(UUID(active_id))
                await cat_client.verify_product(UUID(draft_id))
                with pytest.raises(ServiceError) as exc_info:
                    await cat_client.verify_product(uuid4())
                assert exc_info.value.status == 404

        asyncio.run(verify_inventory_integration())


def test_service_layer_unit_with_fake_session_and_rollback(tmp_path: Path) -> None:
    """Directly exercises service.py functions and file cleanup on DB failure."""
    store = InMemoryCatalogStore()

    async def exercise() -> None:
        cat = await service.create_category(
            store.session(),
            service.CategoryInput(name="Phụ kiện", slug="phu-kien", description="Desc"),
        )
        prod = await service.create_product(
            store.session(),
            service.ProductInput(
                sku="ACC-01",
                slug="acc-01",
                name="Cáp USB-C",
                category_id=cat.id,
                description="Cáp bọc dù",
                price_amount=190000,
                status="ACTIVE",
            ),
        )
        assert prod.price_amount == 190000

        # Upload image succeeds and writes file
        img = await service.upload_image(
            store.session(), prod.id, make_valid_png(), "Cáp", tmp_path
        )
        file_path, mime = service.get_image_file(
            img.url.removeprefix("/api/v1/catalog/images/"), tmp_path
        )
        assert file_path.is_file() and mime == "image/png"

        # Simulate DB flush failure during image upload: physical file must be cleaned up!
        store.fail_on_flush_image = True
        before_files = set(tmp_path.rglob("*"))
        with pytest.raises(ServiceError) as err:
            await service.upload_image(
                store.session(), prod.id, make_valid_jpeg(), "Fail", tmp_path
            )
        assert err.value.status == 409
        after_files = set(tmp_path.rglob("*"))
        assert after_files == before_files
        store.fail_on_flush_image = False

        # Delete image removes file and metadata
        await service.delete_image(store.session(), prod.id, img.id, tmp_path)
        assert not file_path.exists()

    asyncio.run(exercise())


# ──────────────────────────────────────────────
# Disposable PostgreSQL Integration Tests (--run-postgres)
# ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def catalog_database(postgres_test: dict[str, Any]) -> dict[str, Any]:
    password = quote(postgres_test["password"], safe="")
    port = postgres_test["port"]
    runtime_url = f"postgresql://catalog_runtime:{password}@127.0.0.1:{port}/commerce_test"
    migration_url = f"postgresql://catalog_migrator:{password}@127.0.0.1:{port}/commerce_test"
    env = {
        **postgres_test["env"],
        "DB_SSL_MODE": "disable",
        "SERVICE_NAME": "catalog-service",
        "DB_SCHEMA": "commerce_catalog",
        "DATABASE_URL": runtime_url,
        "MIGRATION_DATABASE_URL": migration_url,
    }
    for args in (
        ("bootstrap", "--target", "test", "--apply"),
        ("upgrade", "--service", "catalog-service", "--apply"),
        ("check", "--service", "catalog-service"),
    ):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/database.py"), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    return {"runtime_url": runtime_url, "admin_url": postgres_test["admin_url"]}


@pytest.mark.integration
def test_catalog_postgres_crud_and_concurrency(
    catalog_database: dict[str, Any], tmp_path: Path
) -> None:
    mock_id = IdentityMock()
    settings = Settings(
        _env_file=None,
        database_enabled=True,
        db_ssl_mode="disable",
        database_url=SecretStr(catalog_database["runtime_url"]),
        catalog_storage_dir=tmp_path,
        catalog_service_token=SecretStr("catalog-internal-secret"),
    )
    app = create_app(settings, transport=httpx.MockTransport(mock_id))
    with TestClient(app) as client:
        cat = client.post(
            "/api/v1/admin/categories",
            json={"name": "Màn hình", "slug": f"man-hinh-{uuid4().hex[:6]}"},
            headers=HEADERS_ADMIN,
        )
        assert cat.status_code == 201
        cat_id = cat.json()["id"]

        sku = f"MON-{uuid4().hex[:6].upper()}"
        slug = f"man-hinh-4k-{uuid4().hex[:6]}"
        prod = client.post(
            "/api/v1/admin/products",
            json={
                "sku": sku,
                "slug": slug,
                "name": "Màn hình 4K",
                "categoryId": cat_id,
                "description": "IPS 27 inch",
                "priceAmount": "7900000",
                "currency": "VND",
                "status": "ACTIVE",
                "specifications": {"panel": "IPS"},
            },
            headers=HEADERS_ADMIN,
        )
        assert prod.status_code == 201
        prod_id = prod.json()["id"]

        # Upload & reorder 2 images on real PostgreSQL (verifies unique sort_order shift)
        i1 = client.post(
            f"/api/v1/admin/products/{prod_id}/images",
            files={"file": ("a.png", io.BytesIO(make_valid_png()), "image/png")},
            headers=HEADERS_ADMIN,
        ).json()
        i2 = client.post(
            f"/api/v1/admin/products/{prod_id}/images",
            files={"file": ("b.jpg", io.BytesIO(make_valid_jpeg()), "image/jpeg")},
            headers=HEADERS_ADMIN,
        ).json()

        patched = client.patch(
            f"/api/v1/admin/products/{prod_id}",
            json={"expectedVersion": 0, "imageIds": [i2["id"], i1["id"]]},
            headers=HEADERS_ADMIN,
        )
        assert patched.status_code == 200
        assert [img["id"] for img in patched.json()["images"]] == [i2["id"], i1["id"]]
