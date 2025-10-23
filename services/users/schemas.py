from pydantic import BaseModel, EmailStr, Field

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
    id: int
    email: EmailStr
    role: str
    first_name: str | None = None
    last_name: str | None = None

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=PASS_MIN_LENGTH)
    new_password: str = Field(..., min_length=PASS_MIN_LENGTH)
