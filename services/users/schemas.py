from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from commons import UserRole
from wallet import normalize_wallet

PASS_MIN_LENGTH = 8

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASS_MIN_LENGTH)
    first_name: str | None = None
    last_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    first_name: str | None = None
    last_name: str | None = None
    wallet_address: str | None = None


class WalletIn(BaseModel):
    """PUT /users/me/wallet body (ESC-04). min/max length is the fast pre-check;
    normalize_wallet carries the real 0x + 40 hex rule (ValueError -> 422)."""
    wallet_address: str = Field(..., min_length=42, max_length=42)

    @field_validator("wallet_address")
    @classmethod
    def _valid(cls, v: str) -> str:
        return normalize_wallet(v)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=PASS_MIN_LENGTH)
    new_password: str = Field(..., min_length=PASS_MIN_LENGTH)

class ChangeRoleRequest(BaseModel):
    new_role: UserRole


class AdminCreateUser(BaseModel):
    """Schema for admin to create a new user with a specific role."""
    email: EmailStr
    password: str = Field(min_length=PASS_MIN_LENGTH)
    role: UserRole = UserRole.CUSTOMER
    first_name: str | None = None
    last_name: str | None = None
