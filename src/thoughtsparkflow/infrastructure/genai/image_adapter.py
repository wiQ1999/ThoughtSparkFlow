from __future__ import annotations

import logging

from thoughtsparkflow.domain.ports import ImageGenPort, ImageRequest
from thoughtsparkflow.infrastructure.genai.client import (
    OpenAIWebAPIClient,
    OpenAIWebAPIConfig,
)

__all__ = ["OpenAIImageGenerator"]

log = logging.getLogger(__name__)

_IMAGE_PROMPT_ID = "pmpt_68c6d934bb4c819482dbb040b855f27304ceda00feb03700"


class OpenAIImageGenerator(ImageGenPort):
    """OpenAI-backed implementation of the ImageGenPort."""

    def __init__(self, cfg: OpenAIWebAPIConfig):
        self.client = OpenAIWebAPIClient(cfg)

    def generate_image(self, request: ImageRequest) -> bytes:
        
        response = self.client.run_prompt(
            prompt={
                "id": _IMAGE_PROMPT_ID,
                "version": "10",
                "variables": {
                    "topic": request.topic,
                }
            },
            stream=False,
            tools=[{"type": "image_generation", "partial_images": 0}]
        )
        image_bytes = self.client.extract_image_bytes(response)
        log.debug("OpenAI image generated for topic=%r (%d bytes)", request.topic, len(image_bytes))
        return image_bytes
