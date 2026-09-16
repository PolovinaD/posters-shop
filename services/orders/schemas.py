from pydantic import BaseModel, Field, EmailStr, ConfigDict, model_validator
from decimal import Decimal
from datetime import datetime
from typing import Literal, Optional

from escrow_rules import WALLET_RE


class OrderItemCreate(BaseModel):
    """What a client may state about a line: which SKU, and how many.

    `name` and `unit_price` are accepted for backwards compatibility but are
    ignored — both are resolved from the catalog when the order is written.
    """
    sku: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1)
    name: Optional[str] = None
    unit_price: Optional[Decimal] = Field(default=None, ge=0)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal


class ShippingAddress(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    recipient_name: str = Field(..., min_length=2, max_length=120)
    street: str = Field(..., min_length=3, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    postal_code: str = Field(..., min_length=3, max_length=12, pattern=r"^[A-Za-z0-9][A-Za-z0-9 \-]{1,11}$")
    country: str = Field(..., min_length=2, max_length=56)
    phone: str = Field(..., min_length=6, max_length=20, pattern=r"^\+?[0-9][0-9 \-()]{4,19}$")


class OrderCreate(BaseModel):
    customer_email: EmailStr
    shipping_address: ShippingAddress
    items: list[OrderItemCreate] = Field(..., min_length=1)
    payment_method: Literal["stripe", "escrow"] = "stripe"
    customer_wallet: Optional[str] = Field(default=None, pattern=WALLET_RE)

    @model_validator(mode="after")
    def _wallet_required_for_escrow(self):
        if self.payment_method == "escrow" and not self.customer_wallet:
            raise ValueError("customer_wallet is required when payment_method is 'escrow'")
        return self


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_email: str
    status: str
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    shipping_address: Optional[ShippingAddress] = None
    items: list[OrderItemOut]
    payment_method: str = "stripe"
    customer_wallet: Optional[str] = None
    courier_wallet: Optional[str] = None
    escrow_contract_address: Optional[str] = None
    escrow_deploy_tx: Optional[str] = None
    escrow_amount_wei: Optional[str] = None
    escrow_status: Optional[str] = None


class OrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_email: str
    status: str
    total_amount: Decimal
    created_at: datetime
    item_count: int
    payment_method: str = "stripe"
    escrow_status: Optional[str] = None


class StatusTransition(BaseModel):
    new_status: str


class CancelOrderResponse(BaseModel):
    order_id: int
    status: str
    released_stock: bool
    message: str

