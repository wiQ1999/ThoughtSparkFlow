from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from thoughtsparkflow.domain.helpers import (
    ensure_non_empty_text,
    ensure_positive_int,
)
from thoughtsparkflow.domain.ports import (
    ImageGenPort,
    ImageRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
    WPPort,
)


IMAGE_PROMPT_ID = "pmpt_68c6d934bb4c819482dbb040b855f27304ceda00feb03700"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostFeaturedImageInput:
    """The identifier of the WordPress post along with the subject, 
    based on which the post image is to be generated."""

    post_id: int
    topic: str

    def __post_init__(self) -> None:
        post_id = ensure_positive_int(self.post_id, "post_id")
        topic = ensure_non_empty_text(self.topic, "topic")
        object.__setattr__(self, "post_id", post_id)
        object.__setattr__(self, "topic", topic)


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
    ) -> list[PostFeaturedImageResult]:
        results: list[PostFeaturedImageResult] = []
        for raw_post in posts:
            result = self._process_post(raw_post)
            results.append(result)
        return results

    def _process_post(
        self,
        post: PostFeaturedImageInput,
    ) -> PostFeaturedImageResult:
        image_generated = False
        media_uploaded = False
        post_updated = False
        media_id: Optional[int] = None
        error_message: Optional[str] = None

        try:
            self.log.debug("Checking existence for post_id=%d in WordPress",
                post.post_id
            )
            if not self.wp.post_exists(post.post_id):
                error_message = f"WordPress post {post.post_id} does not exist"
                self.log.error(
                    "Skipping featured image generation because post_id=%d topic=%r does not exist",
                    post.post_id,
                    post.topic,
                )
                return PostFeaturedImageResult(
                    post_id=post.post_id,
                    topic=post.topic,
                    media_id=None,
                    image_generated=image_generated,
                    media_uploaded=media_uploaded,
                    post_updated=post_updated,
                    error=error_message,
                )

            self.log.debug("Generating image for post_id=%d topic=%r", 
                post.post_id, post.topic
            )
            image_bytes = self.img.generate_image(
                ImageRequest(
                    topic=post.topic,
                    propmpt_id=IMAGE_PROMPT_ID,
                )
            )
            image_generated = True

            self.log.debug("Uploading media for post_id=%d topic=%r", 
                post.post_id, post.topic
            )
            media_id = ensure_positive_int(
                self.wp.upload_media(
                    MediaUploadRequest(
                        data=image_bytes,
                        topic=post.topic,
                        post_id=post.post_id,
                    )
                ),
                "media_id",
            )
            media_uploaded = True

            self.log.debug("Updating post_id=%d with media_id=%d", 
                post.post_id, media_id
            )
            post_updated = self.wp.update_post_with_media(
                PostMediaUpdateRequest(
                    post_id=post.post_id,
                    media_id=media_id,
                )
            )

            if not post_updated:
                self.log.error("Failed to set featured media for post %d", 
                    post.post_id
                )
            
        except Exception as exc:
            error_message = str(exc)
            self.log.error(
                "Featured image processing failed for post_id=%d topic=%r: %s",
                post.post_id, post.topic, exc
            )

        return PostFeaturedImageResult(
            post_id=post.post_id,
            topic=post.topic,
            media_id=media_id,
            image_generated=image_generated,
            media_uploaded=media_uploaded,
            post_updated=post_updated,
            error=error_message,
        )
