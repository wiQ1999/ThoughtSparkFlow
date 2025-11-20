from __future__ import annotations

import logging
from typing import Iterable, Optional

from thoughtsparkflow.config.loader import load_config
from thoughtsparkflow.config.validators import (
    check_authors_non_empty,
    check_unique_author_emails,
    run_validations,
)
from thoughtsparkflow.domain.errors import AuthorCategoryDomainError
from thoughtsparkflow.domain.helpers import (
    ensure_positive_int, 
    ensure_non_empty_text
)
from thoughtsparkflow.domain.models import (
    AuthorCategoryEntry,
    AuthorCategoryMap,
    ConfigAuthor,
    DraftsAggregator,
    GenerateDraftsResult,
    WordPressCategory,
    WordPressEditor,
)
from thoughtsparkflow.domain.ports import (
    ContentGenRequest,
    DraftCreationRequest,
    ImageGenPort,
    TextGenPort,
    TopicsGenRequest,
    TopicsRequest,
    WPPort,
)

from .post_featured_image_process import (
    PostFeaturedImageInput,
    PostFeaturedImageProcess,
)
from .errors import ProcessAbort


PUBLISHED_ARTICLES_NUM = 70
DRAFT_ARTICLES_NUM = 100000
TOPICS_PROMPT_ID = "pmpt_68b6076a7fe48194be6ef945bc4b490f01af3bcd933d19d2"
CONTENT_PROMPT_ID = "pmpt_68b9beaa5f10819387a1b9d3ee4c6fc20f21f9b48cca33f2"


logger = logging.getLogger(__name__)


def _ensure_non_empty(name: str, coll: Iterable) -> None:
    if not list(coll) or len(list(coll)) == 0:
        raise ProcessAbort(f"{name}: empty response")


def _ensure_unique_topics(topics: Iterable[str]) -> None:
    seen: set[str] = set()
    for topic in topics:
        normalized = topic.strip().lower()
        if normalized in seen:
            raise ProcessAbort("generate_topics: no unique topics produced.")
        seen.add(normalized)


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
        self.log = log or logger
        self.cfg = None
        self.image_process = PostFeaturedImageProcess(
            wp=wp,
            img=img,
            log=self.log,
        )

    def invoke(self) -> GenerateDraftsResult:
        drafts = DraftsAggregator()
        author_map = AuthorCategoryMap()
        posts_requiring_images: list[PostFeaturedImageInput] = []

        try:
            self.log.info("Fetching editors (WordPress)...")
            wp_editors = list(self.wp.get_all_editors())
            _ensure_non_empty("get_all_editors", wp_editors)
            author_map.add_editors_from_wordpress(
                WordPressEditor(
                    id=editor.id,
                    email=str(editor.email),
                )
                for editor in wp_editors
            )
            self.log.debug("Editors fetched: %d", len(wp_editors))

            self.log.info("Fetching categories (WordPress)...")
            wp_categories = list(self.wp.get_all_categories())
            _ensure_non_empty("get_all_categories", wp_categories)
            author_map.add_categories_from_wordpress(
                WordPressCategory(
                    id=category.id,
                    name=category.name,
                )
                for category in wp_categories
            )
            self.log.debug("Categories fetched: %d", len(wp_categories))

            self.log.info("Loading file config (System)...")
            self.cfg = load_config()
            if not self.cfg.env:
                raise ProcessAbort("Environment file missing.")
            if not self.cfg.file:
                raise ProcessAbort("Config file missing.")
            run_validations(self.cfg.file, checks=[check_authors_non_empty, check_unique_author_emails])
            cfg_authors = [
                ConfigAuthor(
                    author_email=str(author.email),
                    category_name=author.category,
                    author_style_description=author.style_description,
                )
                for author in self.cfg.file.authors
            ]
            author_map.add_authors_from_config(cfg_authors)
            self.log.debug("Local config loaded: %d authors", len(self.cfg.file.authors))

            self.log.info("Validating author/category map (System)...")
            author_map.ensure_data_from_config_complete(cfg_authors)
            categories = author_map.get_categories()
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

            self.log.info("Generating new topics (OpenAI)...")
            topic_with_category_results = list(
                self.text.generate_topics(
                    TopicsGenRequest(
                        last_topics=last_topics,
                        categories=categories,
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
                    author_email = ensure_non_empty_text(entry.author_email, "author_email")
                    author_style = ensure_non_empty_text(entry.author_style_description, "author_style_description")
                    draft.category_id = category_id
                    drafts.set_author(
                        subject=item.topic, 
                        author_id=editor_id, 
                        author_email=author_email
                    )

                    self.log.debug("Generating content for topic=%r category=%r", item.topic, item.category)
                    content = self.text.generate_content(
                        ContentGenRequest(
                            topic=item.topic,
                            style_descritpion=author_style,
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

                    posts_requiring_images.append(
                        PostFeaturedImageInput(
                            post_id=post_id,
                            topic=item.topic,
                        )
                    )

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

            image_assignments = self.image_process.invoke(
                posts=posts_requiring_images,
            )
            for assignment in image_assignments:
                if assignment.post_updated and assignment.media_id is not None:
                    try:
                        drafts.set_media_id(
                            subject=assignment.topic,
                            media_id=assignment.media_id,
                        )
                    except KeyError:
                        self.log.warning(
                            "Missing draft for topic=%r when assigning media_id=%d",
                            assignment.topic,
                            assignment.media_id,
                        )

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
