from __future__ import annotations

import json
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
        input_data = {
            "id": _TOPICS_PROMPT_ID,
            "version": "8",
            "variables": {
                "categories": ", ".join(request.categories),
                "last_topics": ", ".join(f'"{x}"' for x in request.last_topics),
            }
        }
        response = self.client.run_prompt(input_data)
        raw_output = self.client.extract_text(response)
        topics = self._parse_topics(raw_output)
        log.debug("OpenAI generated %d topic candidates", len(topics))
        return topics

    def generate_content(self, request: ContentGenRequest) -> str:
        input_data = {
            "id": _CONTENT_PROMPT_ID,
            "version": "12",
            "variables": {
                "topic": request.topic,
                "category": request.category,
                "style_description": request.style_descritpion,
            }
        }
        response = self.client.run_prompt(input_data)
        content = self.client.extract_text(response)
        if not content:
            raise OpenAIWebAPIError(200, "OpenAI content prompt returned empty text", response)
        log.debug("OpenAI content generated for topic=%r (%d chars)", request.topic, len(content))
        return content

    @staticmethod
    def _parse_topics(raw_output: str) -> List[TopicWithCategoryResult]:
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise OpenAIWebAPIError(200, "OpenAI topics prompt returned invalid JSON", {"text": raw_output}) from exc

        if not isinstance(data, list):
            raise OpenAIWebAPIError(200, "OpenAI topics prompt must return a JSON array", data)

        results: list[TopicWithCategoryResult] = []
        for idx, entry in enumerate(data):
            if not isinstance(entry, dict):
                log.debug("Skipping topic entry index=%d because it is not an object: %r", idx, entry)
                continue
            payload = {
                "topic": entry.get("topic") or entry.get("title"),
                "category": entry.get("category") or entry.get("tag"),
            }
            try:
                results.append(TopicWithCategoryResult(**payload))
            except ValidationError as exc:
                log.warning("Invalid topic entry at index=%d from OpenAI: %s -- payload=%s", idx, exc, entry)

        if not results:
            raise OpenAIWebAPIError(200, "OpenAI topics prompt produced no valid topics", data)
        return results
