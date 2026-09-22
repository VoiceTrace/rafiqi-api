from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

Locale = Literal["en", "ar"]


class CreateReview(BaseModel):
    lesson_id: str = Field(min_length=1, max_length=100)


class ReviewMessage(BaseModel):
    request_id: UUID
    expected_version: int = Field(ge=0)
    action: Literal["chat", "answer", "hint", "help", "next"]
    question_id: str | None = Field(default=None, max_length=100)
    text: str = Field(default="", max_length=2000)
    option_id: str | None = Field(default=None, max_length=100)
    locale: Locale = "en"

    @model_validator(mode="after")
    def validate_payload(self):
        if self.action == "chat" and not self.text.strip():
            raise ValueError("A chat message cannot be empty")
        if self.action == "answer" and not (self.text.strip() or self.option_id):
            raise ValueError("An answer is required")
        if self.action in ("answer", "hint", "next") and not self.question_id:
            raise ValueError("question_id is required")
        return self

