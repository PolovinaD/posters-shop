"""Pydantic request/response schemas for the designs API.

GenerationOut mirrors the Generation row (from_attributes) plus two derived fields
the route fills in: `image_url` (from image_key, never stored — the public prefix is
deployment-specific) and `product_url` (from catalog_product_sku once "Print this"
has run). OutboxEventPayload is the orders outbox envelope, verbatim from
notifications, for the ORDER_PAID subscription (09-05).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GenerationCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    personalise: bool = False


class GenerationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt: str
    effective_prompt: str
    personalise: bool = False
    provider: str
    status: str
    failure_reason: Optional[str] = None
    image_url: Optional[str] = None          # filled by the route from image_key (never stored)
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    purchased_at: Optional[datetime] = None
    catalog_product_sku: Optional[str] = None
    product_url: Optional[str] = None        # filled by the route: /shop/product/{catalog_product_sku}


class SavedPromptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=3, max_length=2000)


class SavedPromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    prompt: str
    created_at: datetime


class QuotaOut(BaseModel):
    limit: int
    used: int
    remaining: Optional[int]
    resets_at: datetime
    exempt: bool


class OutboxEventPayload(BaseModel):
    """Incoming event from the orders outbox worker (verbatim from notifications)."""
    event_id: int
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict
    created_at: str | None = None
