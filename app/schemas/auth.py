from pydantic import BaseModel, EmailStr, Field


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
    token_type: str = Field(default="bearer", examples=["bearer"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0ZjU3ZDBmMiIsInNjaG9vbF9pZCI6ImY5OGIzYTQ5Iiwicm9sZSI6InRlYWNoZXIiLCJleHAiOjE3ODkzMzg1MDB9.signature",
                    "token_type": "bearer",
                }
            ]
        }
    }


class TokenPayload(BaseModel):
    sub: str = Field(..., description="User ID (UUID)", examples=["4f57d0f2-8952-41e4-bbd9-e5ba13c5a5e6"])
    school_id: str = Field(..., description="School ID — all queries are scoped to this", examples=["f98b3a49-b4dd-4f5a-a44b-474a0fc757df"])
    role: str = Field(..., description="`teacher` or `student`", examples=["teacher"])
