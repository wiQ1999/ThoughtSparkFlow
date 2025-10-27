from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests
from openai import OpenAI, OpenAIError

__all__ = [
    "OpenAIWebAPIConfig",
    "OpenAIWebAPIClient",
    "OpenAIWebAPIError",
]

log = logging.getLogger(__name__)


class OpenAIWebAPIError(RuntimeError):
    """Represents an error returned from the OpenAI WebAPI."""

    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}

    def __str__(self) -> str:
        return f"[OpenAI:{self.status_code}] {super().__str__()}"


@dataclass(frozen=True)
class OpenAIWebAPIConfig:
    """Configuration shared by OpenAI adapters."""

    api_key: str
    timeout: float = 30.0


class OpenAIWebAPIClient:
    """Lightweight helper over the OpenAI WebAPI client."""

    def __init__(self, cfg: OpenAIWebAPIConfig):
        self.cfg = cfg
        self.client = OpenAI(
            api_key=cfg.api_key,
            timeout=cfg.timeout,
        )
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def run_prompt(self, input_data: Dict[str, Any]) -> dict:
        """Execute a stored prompt and return the raw JSON payload."""

        log.debug("Calling OpenAI prompt with data=%s", input_data)
        try:
            response = self.client.responses.create(
                prompt=input_data
            )
        except OpenAIError as exc:
            raise OpenAIWebAPIError(
                self._status_from_error(exc), 
                str(exc), 
                self._payload_from_error(exc)
            ) from exc
        return self._to_payload(response)

    def extract_text(self, response_payload: dict) -> str:
        """Return the concatenated text content from a responses payload."""

        chunks: list[str] = []
        for content in self._iter_content_blocks(response_payload):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        result = "".join(chunks).strip()
        if not result:
            raise OpenAIWebAPIError(
                200, 
                "OpenAI response did not include text output", 
                response_payload
            )
        return result

    def extract_image_bytes(self, response_payload: dict) -> bytes:
        """Return the first image output as raw bytes."""

        for content in self._iter_content_blocks(response_payload):
            if content.get("type") == "output_image":
                inline = content.get("image_base64") or content.get("b64_json")
                if isinstance(inline, str):
                    return base64.b64decode(inline)
                image_url = self._resolve_image_url(content)
                if image_url:
                    return self._fetch_binary(image_url)
        raise OpenAIWebAPIError(
            200, 
            "OpenAI response did not include image output", 
            response_payload
        )

    def _resolve_image_url(self, content: dict) -> Optional[str]:
        url_data = content.get("image_url")
        if isinstance(url_data, dict):
            url = url_data.get("url")
            if isinstance(url, str):
                return url
        if isinstance(content.get("url"), str):
            return content["url"]
        return None

    def _fetch_binary(self, url: str) -> bytes:
        resp = self.session.get(url, timeout=self.cfg.timeout)
        if resp.status_code >= 400:
            raise OpenAIWebAPIError(resp.status_code, f"Failed to fetch OpenAI asset from {url}", {"text": resp.text})
        return resp.content

    @staticmethod
    def _iter_content_blocks(payload: dict) -> Iterable[dict]:
        for block in payload.get("output", []):
            content_items = block.get("content", [])
            if isinstance(content_items, list):
                for item in content_items:
                    if isinstance(item, dict):
                        yield item

    @staticmethod
    def _to_payload(response: Any) -> dict:
        if isinstance(response, dict):
            return response
        dump = None
        if hasattr(response, "model_dump"):
            dump = response.model_dump()
        elif hasattr(response, "dict"):
            dump = response.dict()
        elif hasattr(response, "json"):
            try:
                dump = json.loads(response.json())
            except ValueError:
                dump = None
        if isinstance(dump, dict):
            return dump
        raise OpenAIWebAPIError(500, "Unable to parse OpenAI response payload", {"type": str(type(response))})

    @staticmethod
    def _status_from_error(error: Exception) -> int:
        return int(getattr(error, "status_code", getattr(error, "status", 500)) or 500)

    @staticmethod
    def _payload_from_error(error: Exception) -> dict:
        payload = getattr(error, "response", None)
        if payload is None:
            return {}
        if hasattr(payload, "json"):
            try:
                return payload.json()
            except Exception:  # noqa: BLE001
                return {"text": getattr(payload, "text", "")[:500]}
        if isinstance(payload, dict):
            return payload
        return {"value": str(payload)}
