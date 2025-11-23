from __future__ import annotations

import logging
from typing import Iterable, List

from pydantic import ValidationError

from thoughtsparkflow.domain.ports import (
    ContentGenRequest,
    TextGenPort,
    TopicWithCategoryResult,
    TopicsGenRequest,
)
from thoughtsparkflow.infrastructure.genai.client import (
    OpenAIWebAPIClient,
    OpenAIWebAPIConfig,
    OpenAIWebAPIError,
)

__all__ = ["OpenAITextGenerator"]

log = logging.getLogger(__name__)

_TOPICS_PROMPT_ID = "pmpt_68b6076a7fe48194be6ef945bc4b490f01af3bcd933d19d2"
_CONTENT_PROMPT_ID = "pmpt_68b9beaa5f10819387a1b9d3ee4c6fc20f21f9b48cca33f2"


class OpenAITextGenerator(TextGenPort):
    """OpenAI-backed implementation of the TextGenPort."""

    def __init__(self, cfg: OpenAIWebAPIConfig):
        self.client = OpenAIWebAPIClient(cfg)

    def generate_topics(self, request: TopicsGenRequest) -> Iterable[TopicWithCategoryResult]:
        prompt = {
            "id": _TOPICS_PROMPT_ID,
            "version": "12",
            "variables": {
                "categories": ", ".join(request.categories),
                "last_topics": ", ".join(f'"{x}"' for x in request.last_topics),
                "topics_num": str(request.topics_num),
            }
        }
        input = "Wygeneruj odpowiedź w formacie JSON."
        response = self.client.run_prompt(prompt, input)
        topics_payload = self.client.extract_json(response)
        topics = self._parse_topics(topics_payload)
        log.debug("OpenAI generated %d topic candidates", len(topics))
        return topics

    def generate_content(self, request: ContentGenRequest) -> str:
        prompt = {
            "id": _CONTENT_PROMPT_ID,
            "version": "12",
            "variables": {
                "topic": request.topic,
                "category": request.category,
                "style_description": request.style_descritpion,
            }
        }
        response = self.client.run_prompt(prompt)
        log.debug("Response content: %s", response)
        content = self.client.extract_text(response)
        if not content:
            raise OpenAIWebAPIError(200, "OpenAI content prompt returned empty text", response)
        log.debug("OpenAI content generated for topic=%r (%d chars)", request.topic, len(content))
        return content

    @staticmethod
    def _parse_topics(data: object) -> List[TopicWithCategoryResult]:
        if not isinstance(data, dict):
            raise OpenAIWebAPIError(200, "OpenAI topics prompt returned invalid structure", {"payload": data})

        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise OpenAIWebAPIError(
                200,
                "OpenAI topics prompt returned payload without 'items' list",
                {"payload": data},
            )

        topics: List[TopicWithCategoryResult] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                log.warning("Skipping topics item at index %d: expected object, got %s", index, type(item).__name__)
                continue
            try:
                if hasattr(TopicWithCategoryResult, "model_validate"):
                    parsed = TopicWithCategoryResult.model_validate(item)  # type: ignore[attr-defined]
                else:
                    parsed = TopicWithCategoryResult.parse_obj(item)  # type: ignore[attr-defined]
            except ValidationError as exc:
                log.warning("Skipping topics item at index %d due to validation error: %s", index, exc)
                continue
            topics.append(parsed)
        return topics
