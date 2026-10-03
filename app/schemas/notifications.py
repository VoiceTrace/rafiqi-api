import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category: str
    template_key: str
    template_data: dict[str, str]
    created_at: datetime
    read_at: datetime | None
    target_type: str
    target_id: str


class InboxOut(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None
    cutoff: datetime


class CountOut(BaseModel):
    count: int


class ReadAll(BaseModel):
    cutoff: datetime


class InstallationIn(BaseModel):
    fid: str = Field(pattern=r"^[A-Za-z0-9_-]{22}$")
    locale: Literal["en", "ar"] = "en"


class ResultOut(BaseModel):
    ok: bool = True


class DestinationOut(BaseModel):
    path: str
