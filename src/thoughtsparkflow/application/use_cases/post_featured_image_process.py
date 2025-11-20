from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from thoughtsparkflow.domain.helpers import (
    ensure_non_empty_text,
    ensure_positive_int,
    safe_int,
)
from thoughtsparkflow.domain.ports import (
    ImageGenPort,
    ImageRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
    WPPort,
)

from .errors import ProcessAbort


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostFeaturedImageInput:
    """The identifier of the WordPress post along with the subject, 
    based on which the post image is to be generated."""

    post_id: int
    topic: str


@dataclass(frozen=True)
class PostFeaturedImageResult:
    """Summarizes what happened while producing a featured image for a single post."""

    post_id: int
    topic: str
    media_id: Optional[int]
    image_generated: bool
    media_uploaded: bool
    post_updated: bool
    error: Optional[str] = None


class PostFeaturedImageProcess:
    """Business process responsible for generating and 
    attaching featured images to WordPress posts."""

    def __init__(
        self,
        *,
        wp: WPPort,
        img: ImageGenPort,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.wp = wp
        self.img = img
        self.log = log or logger

    def invoke(
        self,
        *,
        posts: Iterable[PostFeaturedImageInput],
        prompt_id: str,
    ) -> list[PostFeaturedImageResult]:
        """Generate and attach featured images for the provided posts."""

        prompt = ensure_non_empty_text(prompt_id, "prompt_id")
        results: list[PostFeaturedImageResult] = []
        for raw_post in posts:
            result = self._process_post(raw_post, prompt)
            results.append(result)
        return results

    def _process_post(
        self,
        post: PostFeaturedImageInput,
        prompt_id: str,
    ) -> PostFeaturedImageResult:
        raw_post_id = getattr(post, "post_id", None)
        raw_topic = getattr(post, "topic", "")
        post_id_value = safe_int(raw_post_id) or 0
        topic_value = raw_topic if isinstance(raw_topic, str) else str(raw_topic)

        image_generated = False
        media_uploaded = False
        post_updated = False
        media_id: Optional[int] = None
        error_message: Optional[str] = None

        try:
            topic = ensure_non_empty_text(topic_value, "topic")
            post_id = ensure_positive_int(post_id_value, "post_id")

            self.log.debug("Generating image for topic=%r post_id=%d", topic, post_id)
            image_bytes = self.img.generate_image(
                ImageRequest(
                    topic=topic,
                    propmpt_id=prompt_id,
                )
            )
            image_generated = True

            self.log.debug("Uploading media for post_id=%d topic=%r", post_id, topic)
            media_id = ensure_positive_int(
                self.wp.upload_media(
                    MediaUploadRequest(
                        data=image_bytes,
                        topic=topic,
                        post_id=post_id,
                    )
                ),
                "media_id",
            )
            media_uploaded = True

            self.log.debug("Updating post_id=%d with media_id=%d", post_id, media_id)
            ok = self.wp.update_post_with_media(
                PostMediaUpdateRequest(
                    post_id=post_id,
                    media_id=media_id,
                )
            )
            if not ok:
                raise ProcessAbort(f"Failed to set featured media for post {post_id}")
            post_updated = True
            topic_value = topic
            post_id_value = post_id
        except Exception as exc:
            error_message = str(exc)
            self.log.error(
                "Featured image processing failed for post_id=%s topic=%r: %s",
                raw_post_id if raw_post_id is not None else "unknown",
                raw_topic,
                exc,
            )

        return PostFeaturedImageResult(
            post_id=post_id_value,
            topic=topic_value,
            media_id=media_id,
            image_generated=image_generated,
            media_uploaded=media_uploaded,
            post_updated=post_updated,
            error=error_message,
        )
