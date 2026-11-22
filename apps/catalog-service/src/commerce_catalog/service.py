"""Catalog business logic use cases. Transactions own metadata and file cleanup."""

import struct
import tempfile
import zlib
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, Select, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from commerce_backend_common.errors import ServiceError
from commerce_catalog.models import Category, Product, ProductImage
from commerce_catalog.schemas import (
    MAX_BIGINT,
    MAX_INTEGER,
    AvailabilityStatus,
    CategoryInput,
    CategoryOut,
    CategoryPatch,
    ImageOut,
    InternalBatch,
    InternalProduct,
    Page,
    ProductInput,
    ProductOut,
    ProductPatch,
    ProductStatus,
    SortOrder,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_IMAGES_PER_PRODUCT = 5
DEFAULT_STORAGE_ROOT = Path(tempfile.gettempdir()) / "commerce-catalog-images"

_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def image_url(storage_key: str) -> str:
    return f"/api/v1/catalog/images/{storage_key}"


def image_view(img: ProductImage) -> ImageOut:
    return ImageOut(
        id=img.id,
        url=image_url(img.storage_key),
        alt_text=img.alt_text,
        sort_order=img.sort_order,
    )


def product_view(product: Product, availability: AvailabilityStatus = "UNKNOWN") -> ProductOut:
    ordered_images = sorted(product.images, key=lambda item: item.sort_order)
    specs = {str(k): str(v) for k, v in (product.specifications or {}).items()}
    return ProductOut(
        id=product.id,
        sku=product.sku,
        slug=product.slug,
        name=product.name,
        category_id=product.category_id,
        description=product.description,
        specifications=specs,
        price_amount=product.price_amount,
        currency="VND",
        status=cast(ProductStatus, product.status),
        version=product.version,
        images=[image_view(img) for img in ordered_images],
        availability=availability,
    )


def category_view(cat: Category) -> CategoryOut:
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description,
        is_visible=cat.is_visible,
    )


def _validate_png(data: bytes) -> bool:
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    length, chunk_type = struct.unpack(">I4s", data[8:16])
    if length != 13 or chunk_type != b"IHDR":
        return False
    ihdr_data = data[16:29]
    width, height, bit_depth, color_type = struct.unpack(">IIBB", ihdr_data[:10])
    if width == 0 or height == 0 or bit_depth not in {1, 2, 4, 8, 16}:
        return False
    if color_type not in {0, 2, 3, 4, 6}:
        return False
    expected_crc = struct.unpack(">I", data[29:33])[0]
    actual_crc = zlib.crc32(data[12:29]) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        return False
    return b"IEND" in data[-20:]


def _validate_jpeg(data: bytes) -> bool:
    if len(data) < 20 or not data.startswith(b"\xff\xd8\xff"):
        return False
    idx = 2
    n = len(data)
    found_sof = False
    while idx < n - 1:
        if data[idx] != 0xFF:
            return False
        while idx < n and data[idx] == 0xFF:
            idx += 1
        if idx >= n:
            break
        marker = data[idx]
        idx += 1
        if marker == 0xD9:  # EOI
            return found_sof
        if marker == 0xDA:  # SOS (entropy-coded data follows until EOI)
            return found_sof and data.endswith(b"\xff\xd9")
        if marker in {0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01}:
            continue
        if idx + 2 > n:
            return False
        seg_len = struct.unpack(">H", data[idx : idx + 2])[0]
        if seg_len < 2 or idx + seg_len > n:
            return False
        if marker in _SOF_MARKERS:
            if seg_len < 7:
                return False
            height, width = struct.unpack(">HH", data[idx + 3 : idx + 7])
            if width == 0 or height == 0:
                return False
            found_sof = True
        idx += seg_len
    return found_sof


def _validate_webp(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    riff_size = struct.unpack("<I", data[4:8])[0]
    if riff_size < 12 or riff_size + 8 > len(data):
        return False
    chunk = data[12:16]
    if chunk not in {b"VP8 ", b"VP8L", b"VP8X"}:
        return False
    chunk_size = int(struct.unpack("<I", data[16:20])[0])
    return bool(chunk_size > 0 and 20 + chunk_size <= len(data))


def detect_and_validate_raster(data: bytes) -> str:
    if not data:
        raise ServiceError(400, "VALIDATION_ERROR", "Uploaded image file must not be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ServiceError(400, "VALIDATION_ERROR", "Image exceeds maximum 5 MiB")
    if _validate_png(data):
        return "image/png"
    if _validate_jpeg(data):
        return "image/jpeg"
    if _validate_webp(data):
        return "image/webp"
    raise ServiceError(
        400, "VALIDATION_ERROR", "Only valid JPEG, PNG or WebP raster images are accepted"
    )


def parse_multipart_image(content_type: str | None, body: bytes) -> tuple[bytes, str | None]:
    if not content_type or not content_type.lower().startswith("multipart/form-data"):
        raise ServiceError(400, "VALIDATION_ERROR", "Content-Type must be multipart/form-data")
    if "boundary=" not in content_type.lower():
        raise ServiceError(400, "VALIDATION_ERROR", "Multipart boundary is required")
    if len(body) > MAX_IMAGE_BYTES + 65536:
        raise ServiceError(400, "VALIDATION_ERROR", "Image exceeds maximum 5 MiB")

    raw_mime = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    msg = BytesParser(policy=HTTP).parsebytes(raw_mime)
    if not msg.is_multipart():
        raise ServiceError(400, "VALIDATION_ERROR", "Invalid multipart payload")

    file_bytes: bytes | None = None
    alt_text: str | None = None
    seen_fields: set[str] = set()

    for part in msg.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        if not isinstance(field_name, str) or field_name not in {"file", "altText"}:
            raise ServiceError(400, "VALIDATION_ERROR", "Unexpected multipart form field")
        if field_name in seen_fields:
            raise ServiceError(400, "VALIDATION_ERROR", f"Duplicate form field: {field_name}")
        seen_fields.add(field_name)

        payload = part.get_payload(decode=True)
        part_bytes = payload if isinstance(payload, bytes) else b""
        if field_name == "file":
            file_bytes = part_bytes
        elif field_name == "altText":
            try:
                decoded = part_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ServiceError(400, "VALIDATION_ERROR", "altText must be valid UTF-8") from exc
            if len(decoded) > 255:
                raise ServiceError(
                    400, "VALIDATION_ERROR", "altText must not exceed 255 characters"
                )
            alt_text = decoded if decoded else None

    if file_bytes is None:
        raise ServiceError(400, "VALIDATION_ERROR", "Multipart field 'file' is required")
    return file_bytes, alt_text


def safe_storage_key(product_id: UUID, image_id: UUID, mime_type: str) -> str:
    ext_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    ext = ext_map[mime_type]
    return f"{product_id}/{image_id}.{ext}"


def get_image_file(storage_key: str, storage_root: Path = DEFAULT_STORAGE_ROOT) -> tuple[Path, str]:
    if not storage_key or "\\" in storage_key or ".." in storage_key:
        raise ServiceError(404, "NOT_FOUND", "Image not found")
    safe_root = storage_root.resolve()
    target = (safe_root / storage_key).resolve()
    if not target.is_relative_to(safe_root) or not target.is_file():
        raise ServiceError(404, "NOT_FOUND", "Image not found")
    ext = target.suffix.lower()
    mime = (
        "image/jpeg"
        if ext in {".jpg", ".jpeg"}
        else "image/png"
        if ext == ".png"
        else "image/webp"
        if ext == ".webp"
        else "application/octet-stream"
    )
    return target, mime


# ─────────────────────────────────────────────────────────────────────────────
# Category use cases
# ─────────────────────────────────────────────────────────────────────────────


async def list_categories_public(
    session: AsyncSession, page: int, page_size: int
) -> Page[CategoryOut]:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        predicate = Category.is_visible.is_(True)
        total = await session.scalar(select(func.count()).select_from(Category).where(predicate))
        rows = (
            await session.scalars(
                select(Category)
                .where(predicate)
                .order_by(Category.created_at.asc(), Category.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return Page[CategoryOut](
            items=[category_view(c) for c in rows],
            page=page,
            page_size=page_size,
            total=total or 0,
        )


async def list_categories_admin(
    session: AsyncSession, page: int, page_size: int
) -> Page[CategoryOut]:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        total = await session.scalar(select(func.count()).select_from(Category))
        rows = (
            await session.scalars(
                select(Category)
                .order_by(Category.created_at.asc(), Category.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return Page[CategoryOut](
            items=[category_view(c) for c in rows],
            page=page,
            page_size=page_size,
            total=total or 0,
        )


async def create_category(session: AsyncSession, body: CategoryInput) -> CategoryOut:
    cat = Category(
        id=uuid4(),
        name=body.name,
        slug=body.slug,
        description=body.description,
        is_visible=body.is_visible,
    )
    async with session.begin():
        session.add(cat)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ServiceError(409, "CONFLICT", "Category slug is already in use") from exc
    return category_view(cat)


async def patch_category(
    session: AsyncSession, category_id: UUID, body: CategoryPatch
) -> CategoryOut:
    async with session.begin():
        cat = await session.get(Category, category_id, with_for_update=True)
        if cat is None:
            raise ServiceError(404, "NOT_FOUND", "Category not found")
        if "name" in body.model_fields_set and body.name is not None:
            cat.name = body.name
        if "slug" in body.model_fields_set and body.slug is not None:
            cat.slug = body.slug
        if "description" in body.model_fields_set:
            cat.description = body.description
        if "is_visible" in body.model_fields_set and body.is_visible is not None:
            cat.is_visible = body.is_visible
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ServiceError(409, "CONFLICT", "Category slug is already in use") from exc
    return category_view(cat)


# ─────────────────────────────────────────────────────────────────────────────
# Product use cases
# ─────────────────────────────────────────────────────────────────────────────


def parse_price_query(
    min_price: str | None, max_price: str | None
) -> tuple[int | None, int | None]:
    min_p: int | None = None
    max_p: int | None = None
    if min_price is not None:
        min_p = int(min_price)
        if min_p > MAX_BIGINT:
            raise ServiceError(400, "VALIDATION_ERROR", "minPrice exceeds maximum allowed value")
    if max_price is not None:
        max_p = int(max_price)
        if max_p > MAX_BIGINT:
            raise ServiceError(400, "VALIDATION_ERROR", "maxPrice exceeds maximum allowed value")
    if min_p is not None and max_p is not None and min_p > max_p:
        raise ServiceError(400, "VALIDATION_ERROR", "minPrice must not be greater than maxPrice")
    return min_p, max_p


def _build_product_query(
    *,
    admin: bool,
    q: str | None,
    category_id: UUID | None,
    min_price: int | None,
    max_price: int | None,
    status: ProductStatus | None,
    sort: SortOrder | None,
    page: int,
    page_size: int,
) -> tuple[Select[Product], list[ColumnElement[bool]]]:
    predicates: list[ColumnElement[bool]] = []
    if not admin:
        predicates.append(Product.status == "ACTIVE")
    elif status is not None:
        predicates.append(Product.status == status)
    if category_id is not None:
        predicates.append(Product.category_id == category_id)
    if min_price is not None:
        predicates.append(Product.price_amount >= min_price)
    if max_price is not None:
        predicates.append(Product.price_amount <= max_price)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        predicates.append(
            or_(Product.name.ilike(term, escape="\\"), Product.sku.ilike(term, escape="\\"))
        )

    base = select(Product).where(*predicates)
    if sort == "PRICE_ASC":
        query = base.order_by(Product.price_amount.asc(), Product.id.asc())
    elif sort == "PRICE_DESC":
        query = base.order_by(Product.price_amount.desc(), Product.id.desc())
    else:
        query = base.order_by(Product.created_at.desc(), Product.id.desc())

    return query.offset((page - 1) * page_size).limit(page_size), predicates


async def list_products(
    session: AsyncSession,
    *,
    admin: bool,
    q: str | None,
    category_id: UUID | None,
    min_price: int | None,
    max_price: int | None,
    status: ProductStatus | None,
    sort: SortOrder | None,
    page: int,
    page_size: int,
) -> Page[ProductOut]:
    query, predicates = _build_product_query(
        admin=admin,
        q=q,
        category_id=category_id,
        min_price=min_price,
        max_price=max_price,
        status=status,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        total = await session.scalar(select(func.count()).select_from(Product).where(*predicates))
        rows = (await session.scalars(query.options(selectinload(Product.images)))).all()
        return Page[ProductOut](
            items=[product_view(p) for p in rows],
            page=page,
            page_size=page_size,
            total=total or 0,
        )


async def get_product(session: AsyncSession, product_id: UUID, *, admin: bool) -> ProductOut:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        product = await session.scalar(
            select(Product).where(Product.id == product_id).options(selectinload(Product.images))
        )
        if product is None or (not admin and product.status != "ACTIVE"):
            raise ServiceError(404, "NOT_FOUND", "Product not found")
        return product_view(product)


async def create_product(session: AsyncSession, body: ProductInput) -> ProductOut:
    async with session.begin():
        category = await session.get(Category, body.category_id)
        if category is None:
            raise ServiceError(404, "NOT_FOUND", "Category not found")
        product = Product(
            id=uuid4(),
            category_id=body.category_id,
            sku=body.sku,
            slug=body.slug,
            name=body.name,
            description=body.description,
            specifications=body.specifications,
            price_amount=body.price_amount,
            currency=body.currency,
            status=body.status,
            version=0,
        )
        product.images = []
        session.add(product)
        try:
            await session.flush()
        except IntegrityError as exc:
            detail = str(exc.orig).lower() if exc.orig else ""
            if "sku" in detail:
                raise ServiceError(409, "CONFLICT", "Product SKU is already in use") from exc
            if "slug" in detail:
                raise ServiceError(409, "CONFLICT", "Product slug is already in use") from exc
            raise ServiceError(409, "CONFLICT", "Product constraint violation") from exc
        return product_view(product)


async def patch_product(session: AsyncSession, product_id: UUID, body: ProductPatch) -> ProductOut:
    async with session.begin():
        product = await session.scalar(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images))
            .with_for_update()
        )
        if product is None:
            raise ServiceError(404, "NOT_FOUND", "Product not found")
        if product.version != body.expected_version:
            raise ServiceError(
                409,
                "CONFLICT",
                "Product version conflict; reload the latest product before saving",
            )
        if product.version >= MAX_INTEGER:
            raise ServiceError(409, "CONFLICT", "Product version limit exceeded")

        if body.category_id is not None:
            category = await session.get(Category, body.category_id)
            if category is None:
                raise ServiceError(404, "NOT_FOUND", "Category not found")
            product.category_id = body.category_id
        if body.slug is not None:
            product.slug = body.slug
        if body.name is not None:
            product.name = body.name
        if body.description is not None:
            product.description = body.description
        if body.specifications is not None:
            product.specifications = body.specifications
        if body.price_amount is not None:
            product.price_amount = body.price_amount
        if body.currency is not None:
            product.currency = body.currency
        if body.status is not None:
            product.status = body.status

        if body.image_ids is not None:
            id_to_img = {img.id: img for img in product.images}
            for iid in body.image_ids:
                if iid not in id_to_img:
                    raise ServiceError(
                        404, "NOT_FOUND", "One or more imageIds do not belong to this product"
                    )
            if len(body.image_ids) != len(id_to_img):
                raise ServiceError(
                    400,
                    "VALIDATION_ERROR",
                    "imageIds must include all existing images of the product",
                )
            # Two-phase sort_order shift avoids intermediate unique constraint collisions.
            for offset_idx, iid in enumerate(body.image_ids):
                id_to_img[iid].sort_order = offset_idx + 1000
            await session.flush()
            for final_idx, iid in enumerate(body.image_ids):
                id_to_img[iid].sort_order = final_idx

        product.version += 1
        try:
            await session.flush()
        except IntegrityError as exc:
            detail = str(exc.orig).lower() if exc.orig else ""
            if "slug" in detail:
                raise ServiceError(409, "CONFLICT", "Product slug is already in use") from exc
            raise ServiceError(409, "CONFLICT", "Product constraint violation") from exc
        return product_view(product)


# ─────────────────────────────────────────────────────────────────────────────
# Image use cases
# ─────────────────────────────────────────────────────────────────────────────


async def upload_image(
    session: AsyncSession,
    product_id: UUID,
    data: bytes,
    alt_text: str | None,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> ImageOut:
    mime_type = detect_and_validate_raster(data)
    image_id = uuid4()
    storage_key = safe_storage_key(product_id, image_id, mime_type)
    dest = storage_root / storage_key
    written = False

    try:
        async with session.begin():
            product = await session.scalar(
                select(Product)
                .where(Product.id == product_id)
                .options(selectinload(Product.images))
                .with_for_update()
            )
            if product is None:
                raise ServiceError(404, "NOT_FOUND", "Product not found")
            if len(product.images) >= MAX_IMAGES_PER_PRODUCT:
                raise ServiceError(
                    409,
                    "CONFLICT",
                    f"Product already has the maximum number of images ({MAX_IMAGES_PER_PRODUCT})",
                )
            sort_order = max((img.sort_order for img in product.images), default=-1) + 1

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                written = True
            except OSError as exc:
                raise ServiceError(
                    503, "DEPENDENCY_UNAVAILABLE", "Could not store image file"
                ) from exc

            img = ProductImage(
                id=image_id,
                product_id=product_id,
                storage_key=storage_key,
                mime_type=mime_type,
                size_bytes=len(data),
                alt_text=alt_text,
                sort_order=sort_order,
            )
            session.add(img)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ServiceError(409, "CONFLICT", "Image storage conflict") from exc
            return image_view(img)
    except (ServiceError, SQLAlchemyError, Exception):
        if written:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        raise


async def delete_image(
    session: AsyncSession,
    product_id: UUID,
    image_id: UUID,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> None:
    async with session.begin():
        img = await session.get(ProductImage, image_id, with_for_update=True)
        if img is None or img.product_id != product_id:
            raise ServiceError(404, "NOT_FOUND", "Image not found")
        storage_key = img.storage_key
        await session.delete(img)
        await session.flush()

    dest = storage_root / storage_key
    try:
        dest.unlink(missing_ok=True)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Internal API
# ─────────────────────────────────────────────────────────────────────────────


async def batch_lookup(session: AsyncSession, product_ids: list[UUID]) -> InternalBatch:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        rows = (await session.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
        by_id = {p.id: p for p in rows}
        items = [
            InternalProduct(
                id=p.id,
                sku=p.sku,
                name=p.name,
                status=cast(ProductStatus, p.status),
                price_amount=p.price_amount,
                version=p.version,
            )
            for pid in product_ids
            if (p := by_id.get(pid)) is not None
        ]
        return InternalBatch(items=items)
