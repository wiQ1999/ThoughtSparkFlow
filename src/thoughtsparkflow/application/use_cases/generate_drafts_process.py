from __future__ import annotations

import logging
from typing import Iterable, Optional

from thoughtsparkflow.config.loader import load_config
from thoughtsparkflow.config.schemas import Author
from thoughtsparkflow.config.validators import (
    check_authors_non_empty,
    check_unique_author_emails,
    run_validations,
)
from thoughtsparkflow.domain.errors import AuthorCategoryDomainError
from thoughtsparkflow.domain.helpers import ensure_positive_int
from thoughtsparkflow.domain.models import (
    AuthorCategoryEntry,
    AuthorCategoryMap,
    ConfigAuthorInput,
    DraftsAggregator,
    GenerateDraftsResult,
    WordPressCategoryInput,
    WordPressEditorInput,
)
from thoughtsparkflow.domain.ports import (
    CategoryResult,
    ContentGenRequest,
    DraftCreationRequest,
    EditorResult,
    ImageGenPort,
    ImageRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
    TextGenPort,
    TopicsGenRequest,
    TopicsRequest,
    WPPort,
)
from .errors import ProcessAbort

PUBLISHED_ARTICLES_NUM = 70
DRAFT_ARTICLES_NUM = 100000
TOPICS_PROMPT_ID = "pmpt_68b6076a7fe48194be6ef945bc4b490f01af3bcd933d19d2"
CONTENT_PROMPT_ID = "pmpt_68b9beaa5f10819387a1b9d3ee4c6fc20f21f9b48cca33f2"
IMAGE_PROMPT_ID = "pmpt_68c6d934bb4c819482dbb040b855f27304ceda00feb03700"


logger = logging.getLogger(__name__)


def _ensure_non_empty(name: str, coll: Iterable) -> None:
    if not list(coll):
        raise ProcessAbort(f"{name}: empty response")


def _ensure_unique_topics(topics: Iterable[str]) -> None:
    seen: set[str] = set()
    for topic in topics:
        normalized = topic.strip().lower()
        if normalized in seen:
            raise ProcessAbort("generate_topics: no unique topics produced.")
        seen.add(normalized)


def _ensure_author_map_coverage(author_map: AuthorCategoryMap, cfg_authors: Iterable[Author]) -> None:
    missing_categories: list[str] = []
    missing_editors: list[str] = []
    missing_styles: list[str] = []

    for author in cfg_authors:
        entry = author_map.find_by_category_name(author.category)
        if entry is None:
            missing_categories.append(author.category)
            continue
        if entry.category_id is None:
            missing_categories.append(author.category)
        if entry.author_id is None or entry.author_email is None:
            missing_editors.append(str(author.email))
        if entry.author_style_description is None:
            missing_styles.append(str(author.email))

    messages: list[str] = []
    if missing_categories:
        unique_categories = ", ".join(sorted(set(missing_categories)))
        messages.append(f"categories missing WordPress mapping: {unique_categories}")
    if missing_editors:
        unique_editors = ", ".join(sorted(set(missing_editors)))
        messages.append(f"authors missing WordPress editor: {unique_editors}")
    if missing_styles:
        unique_styles = ", ".join(sorted(set(missing_styles)))
        messages.append(f"authors missing style description: {unique_styles}")

    if messages:
        raise ProcessAbort(" | ".join(messages))


def _require_link(author_map: AuthorCategoryMap, category_name: str) -> AuthorCategoryEntry:
    entry = author_map.find_by_category_name(category_name)
    if entry is None:
        raise ProcessAbort(f"Category {category_name!r} missing from configuration.")

    missing_fields: list[str] = []
    if entry.category_id is None:
        missing_fields.append("category_id")
    if entry.author_id is None:
        missing_fields.append("author_id")
    if entry.author_email is None:
        missing_fields.append("author_email")
    if entry.author_style_description is None:
        missing_fields.append("author_style_description")

    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ProcessAbort(f"Category {category_name!r} missing fields: {missing}")

    return entry


class GenerateDraftsProcess:
    def __init__(
        self,
        wp: WPPort,
        text: TextGenPort,
        img: ImageGenPort,
        log: Optional[logging.Logger] = None,
    ):
        self.wp = wp
        self.text = text
        self.img = img
        self.log = log or logger
        self.cfg = None

    def invoke(self) -> GenerateDraftsResult:
        drafts = DraftsAggregator()
        author_map = AuthorCategoryMap()

        try:
            self.log.info("Fetching editors (WordPress)...")
            editors: list[EditorResult] = list(self.wp.get_all_editors())
            _ensure_non_empty("get_all_editors", editors)
            self.log.debug("Editors fetched: %d", len(editors))
            author_map.add_editors_from_wordpress(
                WordPressEditorInput(
                    author_id=str(editor.id),
                    author_email=str(editor.email),
                )
                for editor in editors
            )

            self.log.info("Fetching categories (WordPress)...")
            categories: list[CategoryResult] = list(self.wp.get_all_categories())
            _ensure_non_empty("get_all_categories", categories)
            self.log.debug("Categories fetched: %d", len(categories))
            author_map.add_categories_from_wordpress(
                WordPressCategoryInput(
                    category_id=str(category.id),
                    category_name=category.name,
                )
                for category in categories
            )

            self.log.info("Loading file config (System)...")
            self.cfg = load_config()
            self.log.debug("Local config loaded: %d authors", len(self.cfg.file.authors))

            self.log.info("Validating config (System)...")
            if not self.cfg.env:
                raise ProcessAbort("Environment file missing.")
            if not self.cfg.file:
                raise ProcessAbort("Config file missing.")
            run_validations(self.cfg.file, checks=[check_authors_non_empty, check_unique_author_emails])
            author_map.add_authors_from_config(
                ConfigAuthorInput(
                    author_email=str(author.email),
                    category_name=author.category,
                    author_style_description=author.style_description,
                )
                for author in self.cfg.file.authors
            )
            _ensure_author_map_coverage(author_map, self.cfg.file.authors)
            self.log.debug("Author/category map prepared: %d entries", len(author_map.entries_snapshot()))

            self.log.info("Fetching last topics (WordPress)...")
            last_topics = list(
                self.wp.get_last_topics(
                    TopicsRequest(
                        published_num=PUBLISHED_ARTICLES_NUM,
                        draft_num=DRAFT_ARTICLES_NUM,
                    )
                )
            )
            self.log.debug("Last topics fetched: %d", len(last_topics))

            category_names = [category.name for category in categories]

            self.log.info("Generating new topics (OpenAI)...")
            topic_with_category_results = list(
                self.text.generate_topics(
                    TopicsGenRequest(
                        last_topics=last_topics,
                        categories=category_names,
                        propmpt_id=TOPICS_PROMPT_ID,
                    )
                )
            )
            _ensure_non_empty("generate_topics", topic_with_category_results)
            topics_only = [tc.topic for tc in topic_with_category_results]
            _ensure_unique_topics(topics_only)
            self.log.debug("Topics generated: %d", len(topic_with_category_results))

            for item in topic_with_category_results:
                draft = drafts.start(subject=item.topic, category_name=item.category)
                try:
                    entry = _require_link(author_map, item.category)
                    category_id = ensure_positive_int(entry.category_id, "category_id")
                    editor_id = ensure_positive_int(entry.author_id, "author_id")
                    draft.category_id = category_id
                    drafts.set_author(subject=item.topic, author_id=editor_id, author_email=entry.author_email)

                    self.log.debug("Generating content for topic=%r category=%r", item.topic, item.category)
                    content = self.text.generate_content(
                        ContentGenRequest(
                            topic=item.topic,
                            style_descritpion=entry.author_style_description,
                            category=item.category,
                            propmpt_id=CONTENT_PROMPT_ID,
                        )
                    )
                    drafts.set_content(subject=item.topic, content=content)

                    self.log.debug("Creating draft post for topic=%r", item.topic)
                    post_id = self.wp.create_draft_post(
                        DraftCreationRequest(
                            topic=item.topic,
                            content=content,
                            category_id=category_id,
                            editor_id=editor_id,
                        )
                    )
                    drafts.set_post_id(subject=item.topic, post_id=post_id)

                    self.log.debug("Generating image for topic=%r", item.topic)
                    image_bytes = self.img.generate_image(
                        ImageRequest(
                            topic=item.topic,
                            propmpt_id=IMAGE_PROMPT_ID,
                        )
                    )

                    self.log.debug("Uploading media for post_id=%d topic=%r", post_id, item.topic)
                    media_id = self.wp.upload_media(
                        MediaUploadRequest(
                            data=image_bytes,
                            topic=item.topic,
                            post_id=post_id,
                        )
                    )
                    drafts.set_media_id(subject=item.topic, media_id=media_id)

                    self.log.debug("Updating post_id=%d with media_id=%d", post_id, media_id)
                    ok = self.wp.update_post_with_media(
                        PostMediaUpdateRequest(
                            post_id=post_id,
                            media_id=media_id,
                        )
                    )
                    if not ok:
                        raise ProcessAbort(f"Failed to set featured media for post {post_id}")

                except (ProcessAbort, AuthorCategoryDomainError):
                    raise
                except Exception as exc:
                    self.log.error(
                        "Skipping article topic=%r category=%r: %s",
                        item.topic,
                        item.category,
                        exc,
                    )
                    continue

            drafts_snapshot = drafts.all()
            created_count = sum(
                1 for draft in drafts_snapshot if draft.post_id is not None and draft.media_id is not None
            )
            skipped_count = len(drafts_snapshot) - created_count
            topics = [draft.subject for draft in drafts_snapshot]

            return GenerateDraftsResult(
                created_count=created_count,
                skipped_count=skipped_count,
                topics=topics,
            )

        except AuthorCategoryDomainError as exc:
            self.log.error("Author/category mapping error: %s", exc)
            raise ProcessAbort(str(exc)) from exc
        except ProcessAbort as exc:
            self.log.error("Process aborted: %s", exc)
            raise
        except Exception as exc:
            self.log.exception("Unexpected error during drafts generation")
            raise ProcessAbort(f"Unexpected error: {exc}") from exc
