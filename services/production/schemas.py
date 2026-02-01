from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class JobItemIn(BaseModel):
    sku: str
    name: str
    quantity: int


class JobCreate(BaseModel):
    order_id: int = Field(..., gt=0)
    items: list[JobItemIn] = Field(default=[])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    status: str
    items_json: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    processing_time_ms: Optional[int]


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    status: str
    created_at: datetime


class ProcessResult(BaseModel):
    job_id: int
    status: str
    processing_time_ms: int
    message: str

