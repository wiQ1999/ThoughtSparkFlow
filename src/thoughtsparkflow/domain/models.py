from __future__ import annotations

from typing import Dict, Iterable, Iterator, Optional

from pydantic import BaseModel, EmailStr

from .ports import EditorResult, CategoryResult
from thoughtsparkflow.config.schemas import FileConfig


class AuthorCategoryEntry(BaseModel):
    """Represents a single mapping between an editor (author) and a category.

    Fields are intentionally denormalized for easy lookups and logging.
    """

    author_id: int
    author_email: EmailStr
    category_id: int
    category_name: str
    style_description: str


class AuthorCategoryMap:
    """A map that ties WordPress editors to categories with style metadata.

    - Enforces uniqueness of: author_id, author_email, category_id, category_name
      (category_name is matched case-insensitively).
    - Supports adding entries incrementally and reading by category (name or id).
    """

    def __init__(self) -> None:
        self._by_cat_name: Dict[str, AuthorCategoryEntry] = {}
        self._by_cat_id: Dict[int, AuthorCategoryEntry] = {}
        self._author_ids: set[int] = set()
        self._author_emails_norm: set[str] = set()
        self._category_ids: set[int] = set()
        self._category_names_norm: set[str] = set()

    @staticmethod
    def _norm_email(email: str | EmailStr) -> str:
        return str(email).strip().lower()

    @staticmethod
    def _norm_name(name: str) -> str:
        return name.strip().lower()

    def add(self, *, editor: EditorResult, category: CategoryResult, style_description: str) -> AuthorCategoryEntry:
        """Add a new mapping. Enforces uniqueness across key fields.

        Raises ValueError if any uniqueness constraint is violated.
        """
        email_norm = self._norm_email(editor.email)
        name_norm = self._norm_name(category.name)

        if editor.id in self._author_ids:
            raise ValueError(f"Duplicate author_id: {editor.id}")
        if email_norm in self._author_emails_norm:
            raise ValueError(f"Duplicate author_email: {editor.email}")
        if category.id in self._category_ids:
            raise ValueError(f"Duplicate category_id: {category.id}")
        if name_norm in self._category_names_norm:
            raise ValueError(f"Duplicate category_name: {category.name!r}")

        entry = AuthorCategoryEntry(
            author_id=int(editor.id),
            author_email=EmailStr(str(editor.email)),
            category_id=int(category.id),
            category_name=str(category.name),
            style_description=str(style_description or "").strip(),
        )

        self._by_cat_name[name_norm] = entry
        self._by_cat_id[entry.category_id] = entry
        self._author_ids.add(entry.author_id)
        self._author_emails_norm.add(email_norm)
        self._category_ids.add(entry.category_id)
        self._category_names_norm.add(name_norm)
        return entry

    def get_by_category_name(self, name: str) -> Optional[AuthorCategoryEntry]:
        """Return entry by category name (case-insensitive)."""
        return self._by_cat_name.get(self._norm_name(name))

    def get_by_category_id(self, cid: int) -> Optional[AuthorCategoryEntry]:
        """Return entry by category id."""
        return self._by_cat_id.get(int(cid))

    def __len__(self) -> int:
        return len(self._by_cat_id)

    def __iter__(self) -> Iterator[AuthorCategoryEntry]:
        return iter(self._by_cat_id.values())

    @classmethod
    def from_sources(
        cls,
        *,
        cfg: FileConfig,
        editors: Iterable[EditorResult],
        categories: Iterable[CategoryResult],
    ) -> "AuthorCategoryMap":
        """Build map by matching config authors to WP editors and categories.

        Matching rules:
        - Author.email (config) -> EditorResult.email (WP) [case-insensitive]
        - Author.category (config) -> CategoryResult.name (WP) [case-insensitive]
        """
        map_ = cls()

        editors_by_email = {cls._norm_email(e.email): e for e in editors}
        categories_by_name = {cls._norm_name(c.name): c for c in categories}

        for a in cfg.authors:
            e = editors_by_email.get(cls._norm_email(a.email))
            if not e:
                raise ValueError(f"No matching editor for email: {a.email}")
            c = categories_by_name.get(cls._norm_name(a.category))
            if not c:
                raise ValueError(f"No matching category for name: {a.category!r}")
            map_.add(editor=e, category=c, style_description=a.style_description)

        return map_


class ArticleDraft(BaseModel):
    """A mutable container that aggregates draft data as it is produced."""

    subject: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    author_id: Optional[int] = None
    author_email: Optional[EmailStr] = None
    content: Optional[str] = None
    post_id: Optional[int] = None
    media_id: Optional[int] = None


class DraftsAggregator:
    """Aggregates multiple article drafts and lets you add data step-by-step."""

    def __init__(self) -> None:
        self._items: Dict[str, ArticleDraft] = {}

    def start(self, *, subject: str, category_id: Optional[int] = None, category_name: Optional[str] = None) -> ArticleDraft:
        key = subject.strip()
        if key in self._items:
            return self._items[key]
        item = ArticleDraft(subject=key, category_id=category_id, category_name=category_name)
        self._items[key] = item
        return item

    def set_author(self, *, subject: str, author_id: int, author_email: EmailStr) -> ArticleDraft:
        d = self._require(subject)
        d.author_id = int(author_id)
        d.author_email = EmailStr(str(author_email))
        return d

    def set_content(self, *, subject: str, content: str) -> ArticleDraft:
        d = self._require(subject)
        d.content = str(content)
        return d

    def set_post_id(self, *, subject: str, post_id: int) -> ArticleDraft:
        d = self._require(subject)
        d.post_id = int(post_id)
        return d

    def set_media_id(self, *, subject: str, media_id: int) -> ArticleDraft:
        d = self._require(subject)
        d.media_id = int(media_id)
        return d

    def get(self, subject: str) -> Optional[ArticleDraft]:  # pragma: no cover - trivial
        return self._items.get(subject.strip())

    def all(self) -> list[ArticleDraft]:  # pragma: no cover - trivial
        return list(self._items.values())

    def _require(self, subject: str) -> ArticleDraft:
        key = subject.strip()
        if key not in self._items:
            raise KeyError(f"Draft for subject {subject!r} not found. Call start() first.")
        return self._items[key]


class GenerateDraftsResult(BaseModel):
    """Summary of the GenerateDrafts business process."""

    created_count: int
    skipped_count: int
    topics: list[str]
