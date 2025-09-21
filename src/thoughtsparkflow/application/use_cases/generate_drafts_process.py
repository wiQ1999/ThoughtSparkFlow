from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Counter, Iterable, Optional

from thoughtsparkflow.config.loader import load_config
from thoughtsparkflow.config.schemas import Author
from thoughtsparkflow.config.validators import (
    check_authors_non_empty, 
    check_unique_author_emails, 
    run_validations
)
from thoughtsparkflow.domain.ports import (
    EditorResult,
    TopicsRequest,
    DraftCreationRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
    WPPort,
    TopicsGenRequest,
    ContentGenRequest,
    TextGenPort,
    ImageRequest,
    ImageGenPort
)

PUBLISHED_ARTICLES_NUM = 70
DRAFT_ARTICLES_NUM = 100000
TOPICS_PROMPT_ID = "pmpt_68b6076a7fe48194be6ef945bc4b490f01af3bcd933d19d2"
CONTENT_PROMPT_ID = "pmpt_68b9beaa5f10819387a1b9d3ee4c6fc20f21f9b48cca33f2"
IMAGE_PROMPT_ID = "pmpt_68c6d934bb4c819482dbb040b855f27304ceda00feb03700"


logger = logging.getLogger(__name__)


@dataclass
class ArticleOutcome:
    topic: str
    category: str
    editor_id: Optional[int] = None
    post_id: Optional[int] = None
    media_id: Optional[int] = None
    skipped: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class ProcessSummary:
    generated: int
    attempted: int
    outcomes: list[ArticleOutcome]
    aborted: bool
    abort_reason: Optional[str] = None


class ProcessAbort(Exception):
    """The business process error.

    Args:
        Exception (Exception): The original exception.
    """


def _ensure_str_lists_mached(
    collection1: list[str],
    collection2: list[str],
    error_message: str
) -> None:
    errors: list[str] = [error_message]
    l1, l2 = len(collection1), len(collection2)
    if l1 != l2:
        errors.append(f"Count {l1} and {l2}.")
        raise ProcessAbort(" | ".join(errors))
    counter1, counter2 = Counter(collection1), Counter(collection2)
    if counter1 == counter2:
        return
    missing1 = counter2 - counter1
    missing2 = counter1 - counter2 
    if missing1:
        errors.append(f"In first missing: " + ", ".join(f"{e}×{cnt}" for e, cnt in missing1.items()))
    if missing2:
        errors.append(f"In secound missing: " + ", ".join(f"{e}×{cnt}" for e, cnt in missing2.items()))
    raise ProcessAbort(" | ".join(errors))


def _normalize(v: str) -> str:
    return v.strip().lower()


def _ensure_users_mached(
    wp_editors: list[EditorResult],
    cfg_authors: list[Author]
) -> None:
    wp = [_normalize(str(e.email)) for e in wp_editors]
    cfg = [_normalize(str(a.email)) for a in cfg_authors]
    _ensure_str_lists_mached(wp, cfg, "Users missmached")


def _ensure_categories_mached(
    wp_categories: list[str],
    cfg_authors: list[Author]
) -> None:
    wp = [c.lower() for c in wp_categories]
    cfg = [_normalize(a.category) for a in cfg_authors]
    _ensure_str_lists_mached(wp, cfg, "Categories missmached")


def _build_users_map(
    cfg_authors: list[Author],
    wp_editors: list[EditorResult]
) -> dict[str, tuple[Author, EditorResult]]:
    editors_by_email: dict[str, EditorResult] = {
        _normalize(e.email) for e in wp_editors
    }
    map: dict[str, tuple[Author, EditorResult]] = {}
    for a in cfg_authors:
        key = _normalize(str(a.email))
        editor = editors_by_email.get(key)
        map[key] = (a, editor)
    return map


def _ensure_non_empty(name: str, coll: Iterable) -> None:
    if not list(coll):
        raise ProcessAbort(f"{name}: empty response")
    
def _ensure_unique_topics(topics: list[str]) -> None:
    seen = set()
    for topic in topics:
        normalize_topic = topic.strip().lower()
        if normalize_topic not in seen:
            seen.add(normalize_topic)
        else:
            raise ProcessAbort("generate_topics: no unique topics produced.")


def _pick_author_for_category(
    map: dict[str, tuple[Author, EditorResult]], 
    category: str
) -> tuple[Author, EditorResult]:
    for value in map.values():
        map_category = value[0].category
        if  map_category == category:
            return value


class GenerateDraftsProcess:
    def __init__(self,
                 wp: WPPort, 
                 text: TextGenPort, 
                 img: ImageGenPort, 
                 log: Optional[logging.Logger] = None):
        self.wp = wp
        self.text = text
        self.img = img
        self.log = log or logger

    def invoke(self) -> ProcessSummary:
        outcomes: list[ArticleOutcome] = []
        aborted = False
        abort_reason: Optional[str] = None

        try:
            self.log.info("Fetching editors (WordPress)...")
            editors = list(self.wp.get_all_editors())
            _ensure_non_empty("get_all_editors", editors)
            self.log.debug("Editors fetched: %d", len(editors))

            self.log.info("Fetching categories (WordPress)...")
            categories = list(self.wp.get_all_categories())
            _ensure_non_empty("get_all_categories", categories)
            self.log.debug("Categories fetched: %d", len(categories))

            self.log.info("Loading file config (System)...")
            self.cfg = load_config()
            self.log.debug("Local config loaded: %d authors", len(self.cfg.file.e_cfg.authors))

            self.log.info("Validating config (System)...")
            if not self.cfg.env:
                raise ProcessAbort("Environment file missing.")
            if not self.cfg.file:
                raise ProcessAbort("Config file missing.")
            run_validations(self.cfg.file, checks=[check_authors_non_empty, check_unique_author_emails])
            _ensure_users_mached(editors, self.cfg.file.authors)
            _ensure_categories_mached(categories, self.cfg.file.authors)
            users_map = _build_users_map(editors, categories)
            self.log.debug("Config validation passed.")

            self.log.info("Fetching last topics (WordPress)...")
            last_topics = list(
                self.wp.get_last_topics(
                    TopicsRequest(
                        published_num=PUBLISHED_ARTICLES_NUM, 
                        draft_num=DRAFT_ARTICLES_NUM
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
                        propmpt_id=TOPICS_PROMPT_ID
                    )
                )
            )
            _ensure_non_empty("generate_topics", topic_with_category_results)
            topics_only = [tc.topic for tc in topic_with_category_results]
            _ensure_unique_topics(topics_only)
            categories_only = [tc.category for tc in topic_with_category_results]
            _ensure_categories_mached(categories_only, self.cfg.file.authors)
            self.log.debug("Topics generated: %d", len(topic_with_category_results))

            self.log.info("Posts creating loop (System)...")
            attempted = 0
            generated = 0
            for item in topic_with_category_results:
                attempted += 1
                outcome = ArticleOutcome(topic=item.topic, category=item.category)

                try:
                    self.log.info("Setting parameters (System)...")
                    map_value = _pick_author_for_category(users_map, item.category)
                    outcome.editor_id = map_value[1].id
                    self.log.debug("Parameters set")

                    self.log.info("Generating content (OpenAI)...")
                    content = self.text.generate_content(
                        ContentGenRequest(
                            topic=item.topic,
                            style_descritpion=map_value[0].style_description,
                            category=item.category,
                            propmpt_id=CONTENT_PROMPT_ID,
                        )
                    )
                    self.log.debug("Cotent generated %d (length)", len(topic_with_category_results))

                    self.log.info("Creating draft post (WoordPress)...")
                    outcome.post_id = self.wp.create_draft_post(
                        DraftCreationRequest(
                            topic=item.topic,
                            content=content,
                            category=item.category,
                            editor_id=outcome.editor_id,
                        )
                    )
                    self.log.debug("Draft post created %d (id)", outcome.post_id)

                    self.log.info("Generating image (OpenAI)...")
                    image_bytes = self.img.generate_image(
                        ImageRequest(
                            topic=item.topic, 
                            propmpt_id=IMAGE_PROMPT_ID,
                        )
                    )
                    self.log.debug("Image generated")

                    self.log.info("Uploading image (WordPress)...")
                    outcome.media_id = self.wp.upload_media(
                        MediaUploadRequest(
                            data=image_bytes, 
                            topic=item.topic, 
                            post_id=outcome.post_id,
                        )
                    )
                    self.log.debug("Media uploaded %d (id)", outcome.media_id)

                    self.log.info("Updating post (WordPress)...")
                    ok = self.wp.update_post_with_media(
                        PostMediaUpdateRequest(
                            post_id=outcome.post_id, 
                            media_id=outcome.media_id,
                        )
                    )
                    if not ok:
                        raise ValueError("Failed to set featured media for post")
                    generated += 1
                    self.log.info("Draft created OK | post_id=%s media_id=%s topic=%r", 
                        outcome.post_id, outcome.media_id, item.topic
                    )

                except Exception as e:
                    outcome.skipped = True
                    msg = f"topic={item.topic!r} category={item.category!r}: {e}"
                    outcome.errors.append(str(e))
                    self.log.error("Skipping article: %s", msg)

                outcomes.append(outcome)

            return ProcessSummary(
                generated=generated,
                attempted=attempted,
                outcomes=outcomes,
                aborted=False,
            )

        except ProcessAbort as e:
            aborted = True
            abort_reason = str(e)
            self.log.error("Process aborted: %s", abort_reason)
        except Exception as e:
            aborted = True
            abort_reason = f"Unexpected error: {e}"
            self.log.exception("Process aborted due to unexpected error")

        return ProcessSummary(
            generated=generated,
            attempted=attempted,
            outcomes=outcomes,
            aborted=aborted,
            abort_reason=abort_reason,
        )
