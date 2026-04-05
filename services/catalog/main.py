import os
import httpx
from decimal import Decimal
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Column, Integer, String, Numeric, Boolean, Text, select, text
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict

from logger import get_logger, LoggingMiddleware
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
    sizes = Column(String, nullable=True)  # Comma-separated: "A4,A3,A2"
    active = Column(Boolean, default=True)


class Size(Base):
    __tablename__ = "sizes"
    __table_args__ = {"schema": "catalog_schema"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    price_delta = Column(Numeric(10, 2), nullable=False, default=0)


class FrameOption(Base):
    __tablename__ = "frame_options"
    __table_args__ = {"schema": "catalog_schema"}
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    extra_price = Column(Numeric(10, 2), nullable=False, default=0)


# ============== Schemas ==============

class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    price: Decimal
    category: str = "General"
    image_url: Optional[str] = None
    sizes: Optional[str] = "A4,A3,A2"
    active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    sizes: Optional[str] = None
    active: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    sku: str
    name: str
    description: Optional[str]
    price: Decimal
    category: str
    image_url: Optional[str]
    sizes: Optional[str]
    active: bool
    # Stock info (optional, populated from inventory)
    in_stock: Optional[bool] = None
    available: Optional[int] = None


class SizeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    price_delta: Decimal


class FrameOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    extra_price: Decimal


# ============== Inventory Integration ==============

async def get_stock_levels(skus: list[str]) -> dict[str, dict]:
    """Fetch stock levels from inventory service."""
    if not skus:
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
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


# ============== Product Endpoints ==============

@app.get("/products", response_model=list[ProductOut])
async def list_products(
    category: Optional[str] = None,
    active_only: bool = True,
    include_stock: bool = True,
    db: Session = Depends(get_db)
):
    """List all products, optionally filtered by category."""
    query = select(Product)
    
    if category:
        query = query.where(Product.category == category)
    if active_only:
        query = query.where(Product.active == True)
    
    products = db.execute(query.order_by(Product.id)).scalars().all()
    
    # Fetch stock info from inventory
    result = []
    if include_stock and products:
        skus = [p.sku for p in products]
        stock_levels = await get_stock_levels(skus)
        
        for p in products:
            product_dict = ProductOut.model_validate(p).model_dump()
            stock_info = stock_levels.get(p.sku, {})
            product_dict["available"] = stock_info.get("available", 0)
            product_dict["in_stock"] = stock_info.get("available", 0) > 0
            result.append(ProductOut(**product_dict))
    else:
        result = [ProductOut.model_validate(p) for p in products]
    
    return result


@app.get("/products/{sku}", response_model=ProductOut)
async def get_product(sku: str, include_stock: bool = True, db: Session = Depends(get_db)):
    """Get a single product by SKU."""
    product = db.execute(
        select(Product).where(Product.sku == sku)
    ).scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    
    result = ProductOut.model_validate(product)
    
    if include_stock:
        stock_levels = await get_stock_levels([sku])
        stock_info = stock_levels.get(sku, {})
        result.available = stock_info.get("available", 0)
        result.in_stock = result.available > 0
    
    return result


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
    """List all unique categories."""
    products = db.execute(
        select(Product.category).distinct().where(Product.active == True)
    ).scalars().all()
    
    return ["All"] + sorted(set(products))


# ============== Size & Frame Endpoints ==============

@app.get("/sizes", response_model=list[SizeOut])
def list_sizes(db: Session = Depends(get_db)):
    """List all available sizes."""
    sizes = db.execute(select(Size).order_by(Size.name)).scalars().all()
    return [SizeOut.model_validate(s) for s in sizes]


@app.get("/frames", response_model=list[FrameOptionOut])
def list_frames(db: Session = Depends(get_db)):
    """List all frame options."""
    frames = db.execute(select(FrameOption).order_by(FrameOption.id)).scalars().all()
    return [FrameOptionOut.model_validate(f) for f in frames]


# ============== Seed Data ==============

@app.post("/seed")
def seed_catalog(db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Seed catalog with sample products."""
    # Check if data already exists
    existing = db.execute(select(Product)).first()
    if existing:
        return {"message": "Catalog already seeded", "seeded": False}
    
    # Sample products matching the frontend mock data
    products = [
        Product(
            sku="POSTER-SUNSET-A3",
            name="Golden Sunset",
            description="A breathtaking view of the sun setting over the ocean, painting the sky in shades of orange, pink, and purple.",
            price=Decimal("24.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1507400492013-162706c8c05e?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-MOUNTAIN-A3",
            name="Mountain Majesty",
            description="Snow-capped peaks rising above the clouds, capturing the raw beauty and power of nature.",
            price=Decimal("29.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-CITYNIGHT-A3",
            name="City Lights",
            description="The vibrant energy of a metropolis at night, with countless lights creating a galaxy on earth.",
            price=Decimal("27.99"),
            category="Urban",
            image_url="https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-FOREST-A3",
            name="Enchanted Forest",
            description="Sunlight filtering through ancient trees, creating a magical atmosphere in this mystical woodland.",
            price=Decimal("24.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-OCEAN-A3",
            name="Deep Blue",
            description="The mesmerizing depths of the ocean, where light dances through crystal clear water.",
            price=Decimal("26.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-ABSTRACT-A3",
            name="Color Flow",
            description="An explosion of colors blending seamlessly, perfect for adding a modern touch to any space.",
            price=Decimal("22.99"),
            category="Abstract",
            image_url="https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-MINIMAL-A3",
            name="Serene Minimalism",
            description="Clean lines and subtle tones create a sense of calm and sophistication.",
            price=Decimal("21.99"),
            category="Minimal",
            image_url="https://images.unsplash.com/photo-1494438639946-1ebd1d20bf85?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
        Product(
            sku="POSTER-BOTANICAL-A3",
            name="Botanical Garden",
            description="Lush greenery and delicate flowers captured in stunning detail.",
            price=Decimal("25.99"),
            category="Nature",
            image_url="https://images.unsplash.com/photo-1459411552884-841db9b3cc2a?w=600&h=800&fit=crop",
            sizes="A4,A3,A2"
        ),
    ]
    
    # Sizes with price deltas
    sizes = [
        Size(name="A4", price_delta=Decimal("-5.00")),
        Size(name="A3", price_delta=Decimal("0.00")),
        Size(name="A2", price_delta=Decimal("10.00")),
        Size(name="A1", price_delta=Decimal("25.00")),
    ]
    
    # Frame options
    frames = [
        FrameOption(name="No Frame", extra_price=Decimal("0.00")),
        FrameOption(name="Black Frame", extra_price=Decimal("15.00")),
        FrameOption(name="White Frame", extra_price=Decimal("15.00")),
        FrameOption(name="Natural Wood", extra_price=Decimal("22.00")),
        FrameOption(name="Dark Wood", extra_price=Decimal("22.00")),
    ]
    
    db.add_all(products)
    db.add_all(sizes)
    db.add_all(frames)
    db.commit()
    
    return {
        "message": "Catalog seeded",
        "seeded": True,
        "products": len(products),
        "sizes": len(sizes),
        "frames": len(frames)
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
