from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class Author(BaseModel):
    email: EmailStr
    category: str
    style_description: str = Field(min_length=1)

    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

class FileConfig(BaseModel):
    authors: list[Author]
