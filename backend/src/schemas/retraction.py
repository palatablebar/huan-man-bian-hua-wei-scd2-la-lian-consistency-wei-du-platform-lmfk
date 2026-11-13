from pydantic import BaseModel, Field


class RetractionCreateRequest(BaseModel):
    business_key: str = Field(min_length=1, max_length=32)
    notes: str = Field(default="", max_length=255)
