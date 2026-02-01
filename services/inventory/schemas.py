from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class StockCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    available: int = Field(default=0, ge=0)


class StockUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    available: Optional[int] = Field(None, ge=0)


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    available: int
    reserved: int
    created_at: datetime
    updated_at: datetime


class ReserveRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    ttl_minutes: int = Field(default=15, ge=1, le=60)


class ReserveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reservation_id: int
    order_id: int
    sku: str
    quantity: int
    status: str
    expires_at: datetime


class ReleaseRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    sku: Optional[str] = None  # If None, release all reservations for order


class ReleaseResponse(BaseModel):
    released_count: int
    released_quantity: int


class CommitRequest(BaseModel):
    """Commit reservation - deduct from stock permanently (after payment success)."""
    order_id: int = Field(..., gt=0)
    sku: Optional[str] = None


class CommitResponse(BaseModel):
    committed_count: int
    committed_quantity: int


class StockCheckResponse(BaseModel):
    sku: str
    available: int
    reserved: int
    can_reserve: int  # available - reserved from other orders


class BulkStockCheck(BaseModel):
    skus: list[str]


class BulkStockResponse(BaseModel):
    items: list[StockCheckResponse]

