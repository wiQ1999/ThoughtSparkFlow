from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional

from pydantic import BaseModel, EmailStr

from .exceptions import AuthorCategoryDomainError
from .helpers import (
    build_context,
    normalize_category_name,
    normalize_email,
    normalize_plain_text,
)


@dataclass(frozen=True)
class ConfigAuthorInput:
    author_email: Optional[str]
    category_name: Optional[str]
    author_style_description: Optional[str]


@dataclass(frozen=True)
class WordPressEditorInput:
    author_id: Optional[str]
    author_email: Optional[str]


@dataclass(frozen=True)
class WordPressCategoryInput:
    category_id: Optional[str]
    category_name: Optional[str]


@dataclass
class AuthorCategoryEntry:
    author_id: Optional[str] = None
    author_email: Optional[str] = None
    author_style_description: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None


class AuthorCategoryMap:
    """Aggregate that keeps AuthorCategoryEntry items consistent and unique."""

    def __init__(self) -> None:
        self._entries: list[AuthorCategoryEntry] = []
        self._unique_author_ids: set[str] = set()
        self._unique_author_emails: set[str] = set()
        self._unique_category_ids: set[str] = set()
        self._unique_category_names: set[str] = set()

    def add_authors_from_config(self, items: Iterable[ConfigAuthorInput]) -> None:
        for item in items:
            self._add_author_from_config(item)

    def add_editors_from_wordpress(self, items: Iterable[WordPressEditorInput]) -> None:
        for item in items:
            self._add_editor_from_wordpress(item)

    def add_categories_from_wordpress(self, items: Iterable[WordPressCategoryInput]) -> None:
        for item in items:
            self._add_category_from_wordpress(item)

    def entries_snapshot(self) -> tuple[AuthorCategoryEntry, ...]:
        return tuple(replace(entry) for entry in self._entries)

    def find_by_category_name(self, category_name: str) -> Optional[AuthorCategoryEntry]:
        normalized_name = normalize_category_name(category_name)
        if normalized_name is None:
            return None
        for entry in self._entries:
            if entry.category_name == normalized_name:
                return replace(entry)
        return None

    def _add_author_from_config(self, item: ConfigAuthorInput) -> None:
        email = normalize_email(item.author_email)
        category_name = normalize_category_name(item.category_name)
        style = normalize_plain_text(item.author_style_description)
        candidate = self._find_candidate_for_config(email, category_name)
        context = build_context(author_email=email, category_name=category_name)
        if candidate is None:
            new_entry = AuthorCategoryEntry(
                author_email=email,
                author_style_description=style,
                category_name=category_name,
            )
            self._persist_new_entry(new_entry)
            return

        updated_entry = replace(
            candidate,
            author_email=_merge_field("author_email", candidate.author_email, email, context),
            author_style_description=_merge_field(
                "author_style_description", candidate.author_style_description, style, context
            ),
            category_name=_merge_field("category_name", candidate.category_name, category_name, context),
        )
        self._persist_updated_entry(candidate, updated_entry)

    def _add_editor_from_wordpress(self, item: WordPressEditorInput) -> None:
        author_id = normalize_plain_text(item.author_id)
        email = normalize_email(item.author_email)
        candidate = self._find_candidate_for_editor(author_id, email)
        context = build_context(author_id=author_id, author_email=email)
        if candidate is None:
            new_entry = AuthorCategoryEntry(author_id=author_id, author_email=email)
            self._persist_new_entry(new_entry)
            return

        updated_entry = replace(
            candidate,
            author_id=_merge_field("author_id", candidate.author_id, author_id, context),
            author_email=_merge_field("author_email", candidate.author_email, email, context),
        )
        self._persist_updated_entry(candidate, updated_entry)

    def _add_category_from_wordpress(self, item: WordPressCategoryInput) -> None:
        category_id = normalize_plain_text(item.category_id)
        category_name = normalize_category_name(item.category_name)
        candidate = self._find_candidate_for_category(category_id, category_name)
        context = build_context(category_id=category_id, category_name=category_name)
        if candidate is None:
            new_entry = AuthorCategoryEntry(category_id=category_id, category_name=category_name)
            self._persist_new_entry(new_entry)
            return

        updated_entry = replace(
            candidate,
            category_id=_merge_field("category_id", candidate.category_id, category_id, context),
            category_name=_merge_field("category_name", candidate.category_name, category_name, context),
        )
        self._persist_updated_entry(candidate, updated_entry)

    def _persist_new_entry(self, new_entry: AuthorCategoryEntry) -> None:
        self._record_entry_uniques(new_entry)
        self._entries.append(new_entry)

    def _persist_updated_entry(self, target: AuthorCategoryEntry, updated_entry: AuthorCategoryEntry) -> None:
        index = self._index_of(target)
        self._remove_entry_uniques(target)
        try:
            self._record_entry_uniques(updated_entry)
        except AuthorCategoryDomainError:
            self._record_entry_uniques(target)
            raise
        self._entries[index] = updated_entry

    def _record_entry_uniques(self, entry: AuthorCategoryEntry) -> None:
        self._add_unique(self._unique_author_ids, entry.author_id, "author_id")
        self._add_unique(self._unique_author_emails, entry.author_email, "author_email")
        self._add_unique(self._unique_category_ids, entry.category_id, "category_id")
        self._add_unique(self._unique_category_names, entry.category_name, "category_name")

    def _remove_entry_uniques(self, entry: AuthorCategoryEntry) -> None:
        self._discard_value(self._unique_author_ids, entry.author_id)
        self._discard_value(self._unique_author_emails, entry.author_email)
        self._discard_value(self._unique_category_ids, entry.category_id)
        self._discard_value(self._unique_category_names, entry.category_name)

    def _add_unique(self, container: set[str], value: Optional[str], field_name: str) -> None:
        if value is None:
            return
        if value in container:
            raise AuthorCategoryDomainError(f"Duplicate {field_name}: {value}")
        container.add(value)

    def _discard_value(self, container: set[str], value: Optional[str]) -> None:
        if value is None:
            return
        container.discard(value)

    def _index_of(self, entry: AuthorCategoryEntry) -> int:
        for idx, current in enumerate(self._entries):
            if current is entry:
                return idx
        raise ValueError("Target entry not managed by this aggregate.")

    def _find_candidate_for_config(
        self, author_email: Optional[str], category_name: Optional[str]
    ) -> Optional[AuthorCategoryEntry]:
        if author_email is not None:
            found = self._find_by_author_email(author_email)
            if found is not None:
                return found
        if category_name is not None:
            return self._find_by_category_name_internal(category_name)
        return None

    def _find_candidate_for_editor(
        self, author_id: Optional[str], author_email: Optional[str]
    ) -> Optional[AuthorCategoryEntry]:
        if author_id is not None:
            found = self._find_by_author_id(author_id)
            if found is not None:
                return found
        if author_email is not None:
            return self._find_by_author_email(author_email)
        return None

    def _find_candidate_for_category(
        self, category_id: Optional[str], category_name: Optional[str]
    ) -> Optional[AuthorCategoryEntry]:
        if category_id is not None:
            found = self._find_by_category_id(category_id)
            if found is not None:
                return found
        if category_name is not None:
            return self._find_by_category_name_internal(category_name)
        return None

    def _find_by_author_email(self, author_email: str) -> Optional[AuthorCategoryEntry]:
        for entry in self._entries:
            if entry.author_email == author_email:
                return entry
        return None

    def _find_by_author_id(self, author_id: str) -> Optional[AuthorCategoryEntry]:
        for entry in self._entries:
            if entry.author_id == author_id:
                return entry
        return None

    def _find_by_category_id(self, category_id: str) -> Optional[AuthorCategoryEntry]:
        for entry in self._entries:
            if entry.category_id == category_id:
                return entry
        return None

    def _find_by_category_name_internal(self, category_name: str) -> Optional[AuthorCategoryEntry]:
        for entry in self._entries:
            if entry.category_name == category_name:
                return entry
        return None


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
    message = f"Field mismatch for {field_name}: existing={existing_value}, incoming={incoming_value}"
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
