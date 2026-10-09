from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., examples=["teacher@alnoor.edu.sa"])
    password: str = Field(..., min_length=1, examples=["teacher123"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Teacher login",
                    "value": {"email": "teacher@alnoor.edu.sa", "password": "teacher123"},
                },
                {
                    "summary": "Student login",
                    "value": {"email": "student@alnoor.edu.sa", "password": "student123"},
                },
            ]
        }
    }


class TokenResponse(BaseModel):
    access_token: str = Field(
        ...,
        description="Signed JWT. Include in every protected request as: "
                    "`Authorization: Bearer <access_token>`",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    refresh_token: str = Field(
        ...,
        description="Opaque token used to obtain a new access token via `POST /auth/refresh`. "
                    "Store it securely — it is not a JWT and cannot be decoded.",
        examples=["k3s9F1x...long-random-string"],
    )
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(
        default=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        gt=0,
        description="Access-token lifetime in seconds.",
        examples=[1800],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0ZjU3ZDBmMiIsInNjaG9vbF9pZCI6ImY5OGIzYTQ5Iiwicm9sZSI6InRlYWNoZXIiLCJleHAiOjE3ODkzMzg1MDB9.signature",
                    "refresh_token": "k3s9F1x...long-random-string",
                    "token_type": "bearer",
                    "expires_in": 1800,
                }
            ]
        }
    }


class TokenPayload(BaseModel):
    sub: str = Field(..., description="User ID (UUID)", examples=["4f57d0f2-8952-41e4-bbd9-e5ba13c5a5e6"])
    school_id: str = Field(..., description="School ID — all queries are scoped to this", examples=["f98b3a49-b4dd-4f5a-a44b-474a0fc757df"])
    role: str = Field(..., description="`teacher` or `student`", examples=["teacher"])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., examples=["k3s9F1x...long-random-string"])


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., examples=["k3s9F1x...long-random-string"])
