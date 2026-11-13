from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_MIN = 10
PASSWORD_MAX = 128


def _check_password(v: str) -> str:
    if not (PASSWORD_MIN <= len(v) <= PASSWORD_MAX):
        raise ValueError(f"Password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    if v.isalpha() or v.isdigit():
        raise ValueError("Password must mix letters with numbers or symbols")
    return v


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str = Field(min_length=1, max_length=100)

    _pw = field_validator("password")(_check_password)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str

    _pw = field_validator("password")(_check_password)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str

    _pw = field_validator("new_password")(_check_password)
