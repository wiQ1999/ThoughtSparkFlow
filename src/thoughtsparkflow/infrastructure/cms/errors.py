from typing import Optional


class WordPressAPIError(RuntimeError):
    def __init__(self, status: int, url: str, message: str, payload: Optional[dict] = None):
        super().__init__(f"[{status}] {url} -> {message}")
        self.status = status
        self.url = url
        self.payload = payload or {}