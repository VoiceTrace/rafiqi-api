import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    school_id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr = Field(..., examples=["student@alnoor.edu.sa"])
    full_name: str = Field(..., min_length=1, max_length=255, examples=["Sara Al-Otaibi"])
    role: Literal["teacher", "student"] = Field(..., examples=["student"])
    password: str = Field(..., min_length=8, examples=["securepass123"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Create student",
                    "value": {
                        "email": "new.student@alnoor.edu.sa",
                        "full_name": "Khalid Al-Zahrani",
                        "role": "student",
                        "password": "securepass123",
                    },
                }
            ]
        }
    }


class UserUpdate(BaseModel):
    """Teacher updating another user — name or active status only."""
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class UserSelfUpdate(BaseModel):
    """Any user updating their own record — name or password."""
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8)
