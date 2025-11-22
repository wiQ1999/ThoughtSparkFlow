from __future__ import annotations

from dataclasses import dataclass, replace, fields
from typing import Iterable, Optional

from pydantic import BaseModel, EmailStr

from .errors import AuthorCategoryDomainError
from .helpers import (
    normalize_category_name,
    normalize_email,
    normalize_plain_text,
    safe_id,
)


@dataclass(frozen=True)
class ConfigAuthor:
    author_email: str
    category_name: str
    author_style_description: str


@dataclass(frozen=True)
class WordPressEditor:
    id: int
    email: str


@dataclass(frozen=True)
class WordPressCategory:
    id: int
    name: str


@dataclass
class AuthorCategoryEntry:
    author_id: Optional[str] = None
    author_email: Optional[str] = None
    author_style_description: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None


class EditorList:
    """Aggregate that keeps WordPressEditor items consistent and unique."""

    def __init__(self) -> None:
        self._entries: list[WordPressEditor] = []
        self._unique_ids: set[int] = set()
        self._unique_emails: set[str] = set()

    def add_editor(self, item: WordPressEditor) -> None:
        if item.id in self._unique_ids:
            raise AuthorCategoryDomainError(f"Duplicate editor id: {item.id}")
        if item.email in self._unique_emails:
            raise AuthorCategoryDomainError(f"Duplicate editor email: {item.email}")
        self._unique_ids.add(item.id)
        self._unique_emails.add(item.email)
        self._entries.append(item)

    def add_editors(self, items: Iterable[WordPressEditor]) -> None:
        for item in items:
            self.add_editor(item)

    def find_by_id(self, editor_id: int) -> Optional[WordPressEditor]:
        for entry in self._entries:
            if entry.id == editor_id:
                return replace(entry)
        return None
    
    def find_by_email(self, editor_email: str) -> Optional[WordPressEditor]:
        for entry in self._entries:
            if entry.email == editor_email:
                return replace(entry)
        return None

    def entries_snapshot(self) -> tuple[WordPressEditor, ...]:
        return tuple(replace(entry) for entry in self._entries)


class CategoryList:
    """Aggregate that keeps WordPressCategory items consistent and unique."""

    def __init__(self) -> None:
        self._entries: list[WordPressCategory] = []
        self._unique_ids: set[int] = set()
        self._unique_names: set[str] = set()

    def add_category(self, item: WordPressCategory) -> None:
        if item.id in self._unique_ids:
            raise AuthorCategoryDomainError(f"Duplicate category id: {item.id}")
        if item.name in self._unique_names:
            raise AuthorCategoryDomainError(f"Duplicate category name: {item.name}")
        self._unique_ids.add(item.id)
        self._unique_names.add(item.name)
        self._entries.append(item)

    def add_categories(self, items: Iterable[WordPressCategory]) -> None:
        for item in items:
            self.add_category(item)

    def find_by_id(self, category_id: int) -> Optional[WordPressCategory]:
        for entry in self._entries:
            if entry.id == category_id:
                return replace(entry)
        return None
    
    def find_by_name(self, category_name: str) -> Optional[WordPressCategory]:
        for entry in self._entries:
            if entry.name == category_name:
                return replace(entry)
        return None

    def entries_snapshot(self) -> tuple[WordPressCategory, ...]:
        return tuple(replace(entry) for entry in self._entries)


class AuthorCategoryMap:
    """Aggregate that combines WP editors, categories, and config authors."""

    def __init__(self) -> None:
        self._entries: dict[str, AuthorCategoryEntry] = {}
        self._email_to_category: dict[str, str] = {}
        self._editors = EditorList()
        self._categories = CategoryList()
        self._wp_editors_loaded = False
        self._wp_categories_loaded = False

    def add_editors_from_wordpress(self, items: Iterable[WordPressEditor]) -> None:
        for item in items:
            editor = self._sanitize_editor(item)
            self._editors.add_editor(editor)
        self._wp_editors_loaded = True

    def add_categories_from_wordpress(self, items: Iterable[WordPressCategory]) -> None:
        for item in items:
            category = self._sanitize_category(item)
            self._categories.add_category(category)
        self._wp_categories_loaded = True

    def add_authors_from_config(self, items: Iterable[ConfigAuthor]) -> None:
        self._ensure_wordpress_bootstrapped()
        self._entries.clear()
        self._email_to_category.clear()
        for item in items:
            self._assign_author(item)

    def ensure_data_from_config_complete(self, items: Iterable[ConfigAuthor]) -> None:
        self._ensure_wordpress_bootstrapped()
        errors: list[str] = []
        inspected_categories: set[str] = set()
        for index, item in enumerate(items, start=1):
            normalized_category = normalize_category_name(item.category_name)
            normalized_email = normalize_email(item.author_email)
            label = item.category_name or item.author_email or f"config entry #{index}"
            if normalized_category is None:
                errors.append(f"{label}: invalid category name.")
                continue
            if normalized_category in inspected_categories:
                continue
            inspected_categories.add(normalized_category)
            category = self._categories.find_by_name(normalized_category)
            if category is None:
                errors.append(f"{label}: category missing in WordPress data.")
                continue
            entry = self._entries.get(normalized_category)
            if entry is None:
                errors.append(f"{label}: configuration entry missing.")
                continue
            missing_fields: list[str] = []
            if entry.category_id is None:
                missing_fields.append("category_id")
            elif entry.category_id != str(category.id):
                missing_fields.append(
                    f"category_id mismatch (expected {category.id}, got {entry.category_id})"
                )
            if entry.category_name is None:
                missing_fields.append("category_name")
            elif entry.category_name != category.name:
                missing_fields.append(
                    f"category_name mismatch (expected {category.name}, got {entry.category_name})"
                )
            if entry.author_id is None:
                missing_fields.append("author_id")
            if entry.author_email is None:
                missing_fields.append("author_email")
            elif normalized_email is not None and entry.author_email != normalized_email:
                missing_fields.append(
                    f"author_email mismatch (expected {normalized_email}, got {entry.author_email})"
                )
            if entry.author_style_description is None:
                missing_fields.append("author_style_description")
            if missing_fields:
                errors.append(f"{label}: " + ", ".join(missing_fields))
        if errors:
            raise AuthorCategoryDomainError(
                "Incomplete author/category configuration: " + " | ".join(errors)
            )

    def find_by_category_name(
        self, category_name: str
    ) -> Optional[AuthorCategoryEntry]:
        normalized_name = normalize_category_name(category_name)
        if normalized_name is None:
            return None
        entry = self._entries.get(normalized_name)
        return replace(entry) if entry else None
    
    def get_categories(self) -> list[str]:
        return list(self._entries.keys())

    def entries_snapshot(self) -> tuple[AuthorCategoryEntry, ...]:
        return tuple(replace(entry) for entry in self._entries.values())

    def _sanitize_editor(self, item: WordPressEditor) -> WordPressEditor:
        email = normalize_email(item.email)
        if email is None:
            raise AuthorCategoryDomainError(
                "WordPress editor email is missing."
            )
        editor_id = safe_id(item.id)
        if editor_id is None:
            raise AuthorCategoryDomainError(
                f"Invalid WordPress editor id: {item.id!r}"
            )
        return WordPressEditor(id=editor_id, email=email)

    def _sanitize_category(self, item: WordPressCategory) -> WordPressCategory:
        category_name = normalize_category_name(item.name)
        if category_name is None:
            raise AuthorCategoryDomainError(
                "WordPress category name is missing."
            )
        return WordPressCategory(id=item.id, name=category_name)

    def _ensure_wordpress_bootstrapped(self) -> None:
        if not self._wp_editors_loaded or not self._wp_categories_loaded:
            raise AuthorCategoryDomainError(
                "WordPress data must be uploaded " \
                "before adding configuration authors."
            )

    def _assign_author(self, item: ConfigAuthor) -> None:
        email, editor = self._require_editor_by_email(item.author_email)
        category_name, entry = self._require_entry_for_category(item.category_name)
        style = normalize_plain_text(item.author_style_description)
        if entry.author_email not in (None, email):
            context = build_context(
                category_name=entry.category_name, 
                category_id=entry.category_id
            )
            raise AuthorCategoryDomainError(
                f"Category already assigned to another author ({context})."
            )
        if email != entry.author_email:
            self._guard_email_unique(email, category_name)
        context = build_context(
            author_email=email,
            category_id=entry.category_id,
            category_name=entry.category_name,
        )
        updated = replace(
            entry,
            author_id=_merge_field(
                "author_id", 
                entry.author_id, 
                str(editor.id), 
                context
            ),
            author_email=_merge_field(
                "author_email", 
                entry.author_email, 
                email, 
                context
            ),
            author_style_description=_merge_field(
                "author_style_description",
                entry.author_style_description,
                style,
                context,
            ),
        )
        self._entries[category_name] = updated
        if updated.author_email:
            self._email_to_category[updated.author_email] = category_name

    def _guard_email_unique(self, email: str, category_name: str) -> None:
        other_category = self._email_to_category.get(email)
        if other_category is not None and other_category != category_name:
            raise AuthorCategoryDomainError(
                f"Author email {email} already assigned to category {other_category}."
            )

    def _require_entry_for_category(
        self, raw_category_name: str
    ) -> tuple[str, AuthorCategoryEntry]:
        category_name = normalize_category_name(raw_category_name)
        if category_name is None:
            raise AuthorCategoryDomainError(
                "Config author is missing category name."
            )
        category = self._categories.find_by_name(category_name)
        if category is None:
            raise AuthorCategoryDomainError(
                f"Category {raw_category_name!r} missing in WordPress data."
            )
        entry = self._entries.get(category_name)
        if entry is None:
            entry = AuthorCategoryEntry()
        category_id_str = str(category.id)
        context = build_context(
            category_id=category_id_str, 
            category_name=category.name
        )
        updated = replace(
            entry,
            category_id=_merge_field(
                "category_id",
                entry.category_id,
                category_id_str,
                context,
            ),
            category_name=_merge_field(
                "category_name",
                entry.category_name,
                category.name,
                context,
            ),
        )
        self._entries[category_name] = updated
        return category_name, updated

    def _require_editor_by_email(
        self, raw_email: str
    ) -> tuple[str, WordPressEditor]:
        email = normalize_email(raw_email)
        if email is None:
            raise AuthorCategoryDomainError(
                "Config author is missing email."
            )
        editor = self._editors.find_by_email(email)
        if editor is None:
            raise AuthorCategoryDomainError(
                f"Author email {email!r} missing from WordPress editors."
            )
        return email, editor


def _merge_field(
    field_name: str,
    existing_value: Optional[str],
    incoming_value: Optional[str],
    context: str,
) -> Optional[str]:
    if incoming_value is None:
        return existing_value
    if existing_value is None:
        return incoming_value
    if existing_value == incoming_value:
        return existing_value
    message = (
        f"Field mismatch for {field_name}: "
        f"existing={existing_value}, incoming={incoming_value}"
    )
    if context:
        message = f"{message} for {context}"
    raise AuthorCategoryDomainError(message)


def build_context(
    *,
    author_id: Optional[str] = None,
    author_email: Optional[str] = None,
    category_id: Optional[str] = None,
    category_name: Optional[str] = None,
) -> str:
    parts: list[str] = []
    if author_id:
        parts.append(f"author_id={author_id}")
    if author_email:
        parts.append(f"author_email={author_email}")
    if category_id:
        parts.append(f"category_id={category_id}")
    if category_name:
        parts.append(f"category_name={category_name}")
    return ", ".join(parts)


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
        self._items: dict[str, ArticleDraft] = {}

    def start(
        self,
        *,
        subject: str,
        category_id: Optional[int] = None,
        category_name: Optional[str] = None,
    ) -> ArticleDraft:
        key = subject.strip()
        if key in self._items:
            return self._items[key]
        item = ArticleDraft(subject=key, category_id=category_id, category_name=category_name)
        self._items[key] = item
        return item

    def set_author(self, *, subject: str, author_id: int, author_email: str) -> ArticleDraft:
        d = self._require(subject)
        d.author_id = int(author_id)
        d.author_email = author_email
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

    def get(self, subject: str) -> Optional[ArticleDraft]:
        return self._items.get(subject.strip())

    def all(self) -> list[ArticleDraft]:
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
