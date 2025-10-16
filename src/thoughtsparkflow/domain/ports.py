from typing import Protocol, Iterable

from pydantic import BaseModel, EmailStr

class EditorResult(BaseModel):
    id: int
    email: EmailStr

class CategoryResult(BaseModel):
    id: int
    name: str

class TopicsRequest(BaseModel):
    published_num: int
    draft_num: int

class DraftCreationRequest(BaseModel):
    topic: str
    content: str
    category_id: int
    editor_id: int

class MediaUploadRequest(BaseModel):
    data: bytes
    topic: str
    post_id: int

class PostMediaUpdateRequest(BaseModel):
    post_id: int
    media_id: int

class WPPort(Protocol):
    def get_all_editors(self) -> Iterable[EditorResult]: ...
    def get_all_categories(self) -> Iterable[CategoryResult]: ...
    def get_last_topics(self, request: TopicsRequest) -> Iterable[str]: ...
    def create_draft_post(self, request: DraftCreationRequest) -> int: ...
    def upload_media(self, request: MediaUploadRequest) -> int: ...
    def update_post_with_media(self, request: PostMediaUpdateRequest) -> bool: ...

class TopicsGenRequest(BaseModel):
    last_topics: list[str]
    categories: list[str]
    propmpt_id: str

class TopicWithCategoryResult(BaseModel):
    topic: str
    category: str

class ContentGenRequest(BaseModel):
    topic: str
    style_descritpion: str
    category: str
    propmpt_id: str

class TextGenPort(Protocol):
    def generate_topics(self, request: TopicsGenRequest) -> Iterable[TopicWithCategoryResult]: ...
    def generate_content(self, request: ContentGenRequest) -> str: ...

class ImageRequest(BaseModel):
    topic: str
    propmpt_id: str

class ImageGenPort(Protocol):
    def generate_image(self, request: ImageRequest) -> bytes: ...