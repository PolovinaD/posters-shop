import os
import httpx
from decimal import Decimal
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import (Column, Integer, String, Numeric, Boolean, Text, ForeignKey,
                        UniqueConstraint, select, text)
from sqlalchemy.orm import Session, relationship
from pydantic import BaseModel, ConfigDict, Field

from logger import get_logger, LoggingMiddleware
from service_auth import internal_headers, require_service_or_owner
from database import Base, engine, get_db
from metrics import metrics_endpoint, track_metrics
from auth import require_owner

logger = get_logger(__name__)

SERVICE_NAME = "catalog"
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8000")
ROOT_PATH = os.getenv("ROOT_PATH", "")

app = FastAPI(title=f"{SERVICE_NAME} service", root_path=ROOT_PATH)

app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info("Catalog service started. Database migrations managed by Alembic.")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# ============== Models ==============

class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "catalog_schema"}
    id = Column(Integer, primary_key=True)
    sku = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=False, default="General")
    image_url = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    # listed=False hides a family from GET /products and /categories (custom AI
    # motifs) while direct reads and pricing keep working.
    listed = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    variants = relationship("ProductVariant", back_populates="product",
                            cascade="all, delete-orphan",
                            order_by="ProductVariant.id")


class Size(Base):
    __tablename__ = "sizes"
    __table_args__ = {"schema": "catalog_schema"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False, default=0)


class FrameOption(Base):
    __tablename__ = "frame_options"
    __table_args__ = {"schema": "catalog_schema"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    sku_prefix = Column(String, nullable=False, default="FRAME")

    variants = relationship("FrameVariant", back_populates="frame",
                            cascade="all, delete-orphan",
                            order_by="FrameVariant.id")



class ProductVariant(Base):
    """A sellable poster: one motif in one format, with its own SKU and price."""
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "size", name="uq_product_variant_size"),
        {"schema": "catalog_schema"},
    )
    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("catalog_schema.products.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku = Column(String, unique=True, nullable=False, index=True)
    size = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    active = Column(Boolean, nullable=False, default=True)

    product = relationship("Product", back_populates="variants")


class FrameVariant(Base):
    """A sellable frame: one colour in one format.

    Priced per size on purpose. An A1 frame needs roughly twice the moulding of
    an A4, and that interaction between two options is exactly what a single
    flat surcharge on the frame could not express.
    """
    __tablename__ = "frame_variants"
    __table_args__ = (
        UniqueConstraint("frame_option_id", "size", name="uq_frame_variant_size"),
        {"schema": "catalog_schema"},
    )
    id = Column(Integer, primary_key=True)
    frame_option_id = Column(
        Integer,
        ForeignKey("catalog_schema.frame_options.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku = Column(String, unique=True, nullable=False, index=True)
    size = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    active = Column(Boolean, nullable=False, default=True)

    frame = relationship("FrameOption", back_populates="variants")


# ============== Schemas ==============

class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    price: Decimal
    category: str = "General"
    image_url: Optional[str] = None
    active: bool = True
    listed: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    active: Optional[bool] = None
    listed: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    sku: str
    name: str
    description: Optional[str]
    price: Decimal
    category: str
    image_url: Optional[str]
    active: bool
    listed: bool = True
    # Cheapest sellable variant, for the "from X" price on a catalogue card.
    price_from: Optional[Decimal] = None
    variants: list["VariantOut"] = []
    # Stock info (optional, populated from inventory). For a family this is true
    # when ANY of its variants has stock.
    in_stock: Optional[bool] = None
    available: Optional[int] = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    size: str
    price: Decimal
    active: bool
    in_stock: Optional[bool] = None
    available: Optional[int] = None


class SizeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int


class FrameVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    size: str
    price: Decimal
    active: bool
    frame_name: Optional[str] = None
    in_stock: Optional[bool] = None
    available: Optional[int] = None


class FrameOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku_prefix: str
    variants: list[FrameVariantOut] = []


class PriceQuery(BaseModel):
    """SKUs whose authoritative price the caller needs."""
    skus: list[str]


class ResolvedPrice(BaseModel):
    sku: str
    name: str
    price: Decimal


class PriceQueryResult(BaseModel):
    items: list[ResolvedPrice]
    unknown: list[str]


class VariantCreate(BaseModel):
    """A new sellable format for a family.

    `sku` is derived from the family and the format when omitted, which is how
    the seed builds it and how inventory expects to find it — hand-typing it is
    the easiest way to break the link to stock.
    """
    size: str
    price: Decimal
    sku: Optional[str] = None
    active: bool = True


class VariantUpdate(BaseModel):
    price: Optional[Decimal] = None
    active: Optional[bool] = None


class InternalVariantCreate(BaseModel):
    size: str
    price: Decimal


class InternalProductCreate(BaseModel):
    """One-shot family creation for another service (designs' Print-this):
    family + variants in one transaction."""
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    category: str = "Custom"
    image_url: Optional[str] = None
    listed: bool = False
    active: bool = True
    variants: list[InternalVariantCreate] = Field(min_length=1)


class SizeCreate(BaseModel):
    name: str
    sort_order: int = 0


class SizeUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class FrameOptionCreate(BaseModel):
    name: str
    sku_prefix: str


class FrameOptionUpdate(BaseModel):
    name: Optional[str] = None
    sku_prefix: Optional[str] = None


class FrameVariantCreate(BaseModel):
    """A colour priced for one format. Two formats of the same colour are two
    rows precisely because they cost different amounts."""
    size: str
    price: Decimal
    sku: Optional[str] = None
    active: bool = True


# ============== Inventory Integration ==============

async def get_stock_levels(skus: list[str]) -> dict[str, dict]:
    """Fetch stock levels from inventory service."""
    if not skus:
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=internal_headers()) as client:
            response = await client.post(
                f"{INVENTORY_SERVICE_URL}/stock/check",
                json={"skus": skus}
            )
            if response.status_code == 200:
                data = response.json()
                return {item["sku"]: item for item in data.get("items", [])}
    except Exception as e:
        logger.error("Failed to fetch stock levels", error=str(e), skus=skus)
    
    return {}


def _family_payload(product: Product, stock_levels: dict) -> "ProductOut":
    """Render a family with its variants, folding in per-variant stock.

    `price_from` is the cheapest active variant, which is what a catalogue card
    should show; `products.price` is the motif's reference price and is never
    what gets charged.
    """
    out = ProductOut.model_validate(product)
    prices = [v.price for v in product.variants if v.active]
    out.price_from = min(prices) if prices else product.price

    total = 0
    for variant in out.variants:
        info = stock_levels.get(variant.sku, {})
        variant.available = info.get("available", 0)
        variant.in_stock = variant.available > 0
        total += variant.available
    out.available = total
    out.in_stock = total > 0
    return out


# ============== Product Endpoints ==============

@app.get("/products", response_model=list[ProductOut])
async def list_products(
    category: Optional[str] = None,
    active_only: bool = True,
    include_stock: bool = True,
    listed_only: bool = True,
    db: Session = Depends(get_db)
):
    """List all products, optionally filtered by category.

    listed_only=false is for the admin table (shows custom AI motifs).
    """
    query = select(Product)
    
    if category:
        query = query.where(Product.category == category)
    if active_only:
        query = query.where(Product.active == True)
    if listed_only:
        query = query.where(Product.listed == True)
    
    products = db.execute(query.order_by(Product.id)).scalars().all()

    # Stock lives on the variant, not the family: a motif is orderable when at
    # least one of its formats is in stock.
    stock_levels = {}
    if include_stock and products:
        stock_levels = await get_stock_levels(
            [v.sku for p in products for v in p.variants if v.active]
        )

    return [_family_payload(p, stock_levels) for p in products]


@app.get("/products/{sku}", response_model=ProductOut)
async def get_product(sku: str, include_stock: bool = True, db: Session = Depends(get_db)):
    """Get a single product by SKU."""
    product = db.execute(
        select(Product).where(Product.sku == sku)
    ).scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    
    stock_levels = {}
    if include_stock:
        stock_levels = await get_stock_levels(
            [v.sku for v in product.variants if v.active]
        )

    return _family_payload(product, stock_levels)


@app.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Create a new product."""
    existing = db.execute(
        select(Product).where(Product.sku == payload.sku)
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Product with SKU '{payload.sku}' already exists")
    
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    
    return ProductOut.model_validate(product)


@app.patch("/products/{sku}", response_model=ProductOut)
def update_product(sku: str, payload: ProductUpdate, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Update a product."""
    product = db.execute(
        select(Product).where(Product.sku == sku)
    ).scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
    
    db.commit()
    db.refresh(product)
    
    return ProductOut.model_validate(product)


@app.delete("/products/{sku}", status_code=204)
def delete_product(sku: str, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Delete a product (or deactivate)."""
    product = db.execute(
        select(Product).where(Product.sku == sku)
    ).scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    
    # Soft delete by deactivating
    product.active = False
    db.commit()
    
    return None


@app.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """List all unique categories (of listed families — otherwise "Custom"
    would show up as an empty tab)."""
    products = db.execute(
        select(Product.category).distinct().where(Product.active == True, Product.listed == True)
    ).scalars().all()
    
    return ["All"] + sorted(set(products))


# ============== Size & Frame Endpoints ==============

@app.get("/sizes", response_model=list[SizeOut])
def list_sizes(db: Session = Depends(get_db)):
    """List the available formats, smallest first."""
    sizes = db.execute(select(Size).order_by(Size.sort_order)).scalars().all()
    return [SizeOut.model_validate(s) for s in sizes]


@app.get("/frames", response_model=list[FrameOptionOut])
async def list_frames(
    size: Optional[str] = None,
    include_stock: bool = True,
    db: Session = Depends(get_db),
):
    """List frame colours with their per-format variants.

    Pass `size` and each colour carries only that format's variant, priced for
    it — which is what the product page needs once a format has been chosen.
    """
    frames = db.execute(select(FrameOption).order_by(FrameOption.id)).scalars().all()

    out = []
    for frame in frames:
        item = FrameOptionOut.model_validate(frame)
        if size:
            item.variants = [v for v in item.variants if v.size == size]
        for variant in item.variants:
            variant.frame_name = frame.name
        out.append(item)

    if include_stock:
        stock_levels = await get_stock_levels(
            [v.sku for f in out for v in f.variants]
        )
        for frame in out:
            for variant in frame.variants:
                info = stock_levels.get(variant.sku, {})
                variant.available = info.get("available", 0)
                variant.in_stock = variant.available > 0

    return out


@app.post("/internal/resolve-prices", response_model=PriceQueryResult)
def resolve_prices(
    payload: PriceQuery,
    db: Session = Depends(get_db),
    _: dict = Depends(require_service_or_owner),
):
    """Return the authoritative price for each SKU, poster or frame.

    Orders calls this before persisting an order. A price that arrives in a
    request body is a proposal, not a fact — this endpoint is the fact.
    """
    wanted = list(dict.fromkeys(payload.skus))
    if not wanted:
        return PriceQueryResult(items=[], unknown=[])

    found: dict[str, ResolvedPrice] = {}

    for variant, product in db.execute(
        select(ProductVariant, Product)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(ProductVariant.sku.in_(wanted), ProductVariant.active == True)
    ).all():
        found[variant.sku] = ResolvedPrice(
            sku=variant.sku,
            name=f"{product.name} ({variant.size})",
            price=variant.price,
        )

    for variant, frame in db.execute(
        select(FrameVariant, FrameOption)
        .join(FrameOption, FrameVariant.frame_option_id == FrameOption.id)
        .where(FrameVariant.sku.in_(wanted), FrameVariant.active == True)
    ).all():
        found[variant.sku] = ResolvedPrice(
            sku=variant.sku,
            name=f"{frame.name} ({variant.size})",
            price=variant.price,
        )

    return PriceQueryResult(
        items=[found[sku] for sku in wanted if sku in found],
        unknown=[sku for sku in wanted if sku not in found],
    )


@app.post("/internal/products", response_model=ProductOut, status_code=201)
def create_internal_product(
    payload: InternalProductCreate,
    response: Response,
    db: Session = Depends(get_db),
    _: dict = Depends(require_service_or_owner),
):
    """Idempotent family create for services (designs' Print-this).

    An existing sku answers 200 with the family as it is; otherwise the family
    and every variant are written in ONE transaction so a crash cannot leave a
    motif without formats. `products.price` is the motif's reference price and
    is never charged; the cheapest variant is a sensible reference.
    """
    existing = db.execute(select(Product).where(Product.sku == payload.sku)).scalar_one_or_none()
    if existing:
        response.status_code = 200
        return _family_payload(existing, {})

    if len({v.size for v in payload.variants}) != len(payload.variants):
        raise HTTPException(status_code=400, detail="Duplicate format in variants")
    sizes = [_known_size(db, v.size) for v in payload.variants]  # 400 before anything is written

    product = Product(
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        price=min(v.price for v in payload.variants),
        category=payload.category,
        image_url=payload.image_url,
        active=payload.active,
        listed=payload.listed,
    )
    for v, size in zip(payload.variants, sizes):
        product.variants.append(
            ProductVariant(sku=f"{product.sku}-{size.name}", size=size.name, price=v.price, active=True)
        )
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info("Internal product family created", sku=product.sku,
                variants=len(payload.variants), listed=product.listed)
    return _family_payload(product, {})


# ============== Owner: variants, formats and frames ==============

def _known_size(db: Session, name: str) -> Size:
    """A variant may only use a format the vocabulary actually defines.

    The three-way drift between the size table, a per-product size string and
    the stock SKUs is exactly what this check exists to prevent recurring.
    """
    size = db.execute(select(Size).where(Size.name == name)).scalar_one_or_none()
    if not size:
        known = [s.name for s in db.execute(select(Size).order_by(Size.sort_order)).scalars()]
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{name}'. Defined formats: {', '.join(known) or 'none'}",
        )
    return size


@app.post("/products/{sku}/variants", response_model=VariantOut, status_code=201)
def create_variant(
    sku: str,
    payload: VariantCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Add a format to a family, with its own price and its own SKU."""
    product = db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")

    _known_size(db, payload.size)

    if any(v.size == payload.size for v in product.variants):
        raise HTTPException(
            status_code=409, detail=f"{sku} already has a {payload.size} variant"
        )

    variant_sku = payload.sku or f"{product.sku}-{payload.size}"
    if db.execute(
        select(ProductVariant).where(ProductVariant.sku == variant_sku)
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"SKU '{variant_sku}' already exists")

    variant = ProductVariant(
        product_id=product.id,
        sku=variant_sku,
        size=payload.size,
        price=payload.price,
        active=payload.active,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    logger.info("Variant created", sku=variant.sku, price=str(variant.price))
    return VariantOut.model_validate(variant)


@app.patch("/variants/{sku}", response_model=VariantOut)
def update_variant(
    sku: str,
    payload: VariantUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Change a format's price, or take it off sale."""
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Variant '{sku}' not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    return VariantOut.model_validate(variant)


@app.delete("/variants/{sku}", status_code=204)
def delete_variant(sku: str, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Take a format off sale.

    Deactivates rather than deletes, as products do: orders keep their own copy
    of the SKU, name and price, so past orders stay readable either way, but the
    row is worth keeping for its history.
    """
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Variant '{sku}' not found")
    variant.active = False
    db.commit()
    return None


@app.post("/sizes", response_model=SizeOut, status_code=201)
def create_size(
    payload: SizeCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Add a format to the vocabulary. Variants for it are added per product."""
    if db.execute(select(Size).where(Size.name == payload.name)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Format '{payload.name}' already exists")
    size = Size(name=payload.name, sort_order=payload.sort_order)
    db.add(size)
    db.commit()
    db.refresh(size)
    return SizeOut.model_validate(size)


@app.patch("/sizes/{size_id}", response_model=SizeOut)
def update_size(
    size_id: int,
    payload: SizeUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    size = db.get(Size, size_id)
    if not size:
        raise HTTPException(status_code=404, detail="Format not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(size, field, value)
    db.commit()
    db.refresh(size)
    return SizeOut.model_validate(size)


@app.delete("/sizes/{size_id}", status_code=204)
def delete_size(
    size_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Remove a format from the vocabulary.

    Refuses while variants still use it, because removing it would leave rows
    priced for a format nothing defines. `force` deletes those variants too.
    """
    size = db.get(Size, size_id)
    if not size:
        raise HTTPException(status_code=404, detail="Format not found")

    users = db.execute(
        select(ProductVariant).where(ProductVariant.size == size.name)
    ).scalars().all()
    frame_users = db.execute(
        select(FrameVariant).where(FrameVariant.size == size.name)
    ).scalars().all()

    if (users or frame_users) and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Format '{size.name}' is used by {len(users)} product "
                f"and {len(frame_users)} frame variants. "
                "Delete them first, or repeat with force=true."
            ),
        )
    for variant in [*users, *frame_users]:
        db.delete(variant)
    db.delete(size)
    db.commit()
    return None


@app.post("/frames", response_model=FrameOptionOut, status_code=201)
def create_frame(
    payload: FrameOptionCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Add a frame colour. Its per-format prices are added separately."""
    clash = db.execute(
        select(FrameOption).where(
            (FrameOption.name == payload.name) | (FrameOption.sku_prefix == payload.sku_prefix)
        )
    ).scalar_one_or_none()
    if clash:
        raise HTTPException(status_code=409, detail="Frame name or SKU prefix already in use")
    frame = FrameOption(name=payload.name, sku_prefix=payload.sku_prefix)
    db.add(frame)
    db.commit()
    db.refresh(frame)
    return FrameOptionOut.model_validate(frame)


@app.patch("/frames/{frame_id}", response_model=FrameOptionOut)
def update_frame(
    frame_id: int,
    payload: FrameOptionUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    frame = db.get(FrameOption, frame_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(frame, field, value)
    db.commit()
    db.refresh(frame)
    return FrameOptionOut.model_validate(frame)


@app.delete("/frames/{frame_id}", status_code=204)
def delete_frame(
    frame_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Remove a frame colour. `force` also removes its per-format prices."""
    frame = db.get(FrameOption, frame_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    if frame.variants and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{frame.name}' is priced for {len(frame.variants)} formats. "
                "Delete those first, or repeat with force=true."
            ),
        )
    db.delete(frame)          # cascades to its variants
    db.commit()
    return None


@app.post("/frames/{frame_id}/variants", response_model=FrameVariantOut, status_code=201)
def create_frame_variant(
    frame_id: int,
    payload: FrameVariantCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Price a colour for one format."""
    frame = db.get(FrameOption, frame_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")

    _known_size(db, payload.size)

    if any(v.size == payload.size for v in frame.variants):
        raise HTTPException(
            status_code=409, detail=f"{frame.name} already has a {payload.size} price"
        )

    variant_sku = payload.sku or f"{frame.sku_prefix}-{payload.size}"
    if db.execute(
        select(FrameVariant).where(FrameVariant.sku == variant_sku)
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"SKU '{variant_sku}' already exists")

    variant = FrameVariant(
        frame_option_id=frame.id,
        sku=variant_sku,
        size=payload.size,
        price=payload.price,
        active=payload.active,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    out = FrameVariantOut.model_validate(variant)
    out.frame_name = frame.name
    return out


@app.patch("/frame-variants/{sku}", response_model=FrameVariantOut)
def update_frame_variant(
    sku: str,
    payload: VariantUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    variant = db.execute(
        select(FrameVariant).where(FrameVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Frame variant '{sku}' not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    out = FrameVariantOut.model_validate(variant)
    out.frame_name = variant.frame.name
    return out


@app.delete("/frame-variants/{sku}", status_code=204)
def delete_frame_variant(
    sku: str, db: Session = Depends(get_db), _: dict = Depends(require_owner)
):
    """Take one colour-and-format combination off sale."""
    variant = db.execute(
        select(FrameVariant).where(FrameVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Frame variant '{sku}' not found")
    variant.active = False
    db.commit()
    return None


# ============== Seed Data ==============

@app.post("/seed")
def seed_catalog(
    force: bool = False,
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner),
):
    """Seed the catalogue: eight motifs in four formats, plus four frame colours.

    Every sellable unit is its own row with its own price, so a framed A1 costs
    what an A1 frame costs rather than a flat surcharge borrowed from A4.

    `force` wipes and rebuilds; it exists so the local stack can be reseeded
    after a model change without dropping the database volume.
    """
    existing = db.execute(select(Product)).first()
    if existing and not force:
        return {"message": "Catalog already seeded", "seeded": False}
    if existing:
        db.execute(text(
            "TRUNCATE catalog_schema.products, catalog_schema.sizes, "
            "catalog_schema.frame_options RESTART IDENTITY CASCADE"
        ))
        db.commit()
    
    # Sample products matching the frontend mock data
    products = [
        Product(
            sku="POSTER-SUNSET",
            name="Golden Sunset",
            description="A breathtaking view of the sun setting over the ocean, painting the sky in shades of orange, pink, and purple.",
            price=Decimal("24.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1507400492013-162706c8c05e?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-MOUNTAIN",
            name="Mountain Majesty",
            description="Snow-capped peaks rising above the clouds, capturing the raw beauty and power of nature.",
            price=Decimal("29.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-CITYNIGHT",
            name="City Lights",
            description="The vibrant energy of a metropolis at night, with countless lights creating a galaxy on earth.",
            price=Decimal("27.99"),
            category="Urban",
            image_url="https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-FOREST",
            name="Enchanted Forest",
            description="Sunlight filtering through ancient trees, creating a magical atmosphere in this mystical woodland.",
            price=Decimal("24.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-OCEAN",
            name="Deep Blue",
            description="The mesmerizing depths of the ocean, where light dances through crystal clear water.",
            price=Decimal("26.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-ABSTRACT",
            name="Color Flow",
            description="An explosion of colors blending seamlessly, perfect for adding a modern touch to any space.",
            price=Decimal("22.99"),
            category="Abstract",
            image_url="https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-MINIMAL",
            name="Serene Minimalism",
            description="Clean lines and subtle tones create a sense of calm and sophistication.",
            price=Decimal("21.99"),
            category="Minimal",
            image_url="https://images.unsplash.com/photo-1494438639946-1ebd1d20bf85?w=600&h=800&fit=crop"
        ),
        Product(
            sku="POSTER-BOTANICAL",
            name="Botanical Garden",
            description="Lush greenery and delicate flowers captured in stunning detail.",
            price=Decimal("25.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1459411552884-841db9b3cc2a?w=600&h=800&fit=crop"
        ),
    ]
    
    # The size vocabulary. Ordering is by area, smallest first, so the picker
    # can render A4 → A1 without the client knowing anything about paper sizes.
    sizes = [
        Size(name="A4", sort_order=1),
        Size(name="A3", sort_order=2),
        Size(name="A2", sort_order=3),
        Size(name="A1", sort_order=4),
    ]

    # "No frame" is not a stocked item — it is simply the absence of a frame
    # line on the order, so it is not a row here.
    frames = [
        FrameOption(name="Black Frame", sku_prefix="FRAME-BLACK"),
        FrameOption(name="White Frame", sku_prefix="FRAME-WHITE"),
        FrameOption(name="Natural Wood", sku_prefix="FRAME-NATURAL"),
        FrameOption(name="Dark Wood", sku_prefix="FRAME-DARK"),
    ]

    db.add_all(products)
    db.add_all(sizes)
    db.add_all(frames)
    db.flush()   # assign ids without ending the transaction

    # A poster variant's price is the motif's base price adjusted for format.
    # The adjustment is applied once, here, and then stored on the variant — the
    # variant is what gets charged, so nothing recomputes it later.
    poster_uplift = {
        "A4": Decimal("-5.00"),
        "A3": Decimal("0.00"),
        "A2": Decimal("10.00"),
        "A1": Decimal("25.00"),
    }
    variants = [
        ProductVariant(
            product_id=p.id,
            sku=f"{p.sku}-{size.name}",
            size=size.name,
            price=p.price + poster_uplift[size.name],
        )
        for p in products
        for size in sizes
    ]

    # Frame prices are per (colour, format) rather than a flat surcharge. The
    # numbers follow the A-series: each step up doubles the area, so the
    # perimeter — and with it the moulding a frame needs — grows by about √2.
    frame_prices = {
        "FRAME-BLACK":   {"A4": "12.00", "A3": "17.00", "A2": "24.00", "A1": "34.00"},
        "FRAME-WHITE":   {"A4": "12.00", "A3": "17.00", "A2": "24.00", "A1": "34.00"},
        "FRAME-NATURAL": {"A4": "18.00", "A3": "25.00", "A2": "36.00", "A1": "51.00"},
        "FRAME-DARK":    {"A4": "18.00", "A3": "25.00", "A2": "36.00", "A1": "51.00"},
    }
    frame_variants = [
        FrameVariant(
            frame_option_id=f.id,
            sku=f"{f.sku_prefix}-{size.name}",
            size=size.name,
            price=Decimal(frame_prices[f.sku_prefix][size.name]),
        )
        for f in frames
        for size in sizes
    ]

    db.add_all(variants)
    db.add_all(frame_variants)
    db.commit()

    return {
        "message": "Catalog seeded",
        "seeded": True,
        "products": len(products),
        "sizes": len(sizes),
        "frames": len(frames),
        "product_variants": len(variants),
        "frame_variants": len(frame_variants),
    }


# Keep old endpoint for backwards compatibility
@app.get("/items")
async def list_items(db: Session = Depends(get_db)):
    """Legacy endpoint - returns products."""
    products = await list_products(active_only=True, include_stock=True, db=db)
    return [
        {
            "id": p.id,
            "sku": p.sku,
            "title": p.name,
            "image_url": p.image_url,
            "base_price": str(p.price),
            "in_stock": p.in_stock,
            "available": p.available,
        }
        for p in products
    ]
