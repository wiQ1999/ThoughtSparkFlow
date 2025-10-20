from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

import requests
from requests.auth import HTTPBasicAuth
from requests import Response

from thoughtsparkflow.domain.helpers import ensure_positive_int, normalize_category_name, normalize_email, safe_int
from thoughtsparkflow.domain.ports import (
    WPPort,
    EditorResult,
    CategoryResult,
    TopicsRequest,
    DraftCreationRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
)
from pydantic import ValidationError

from thoughtsparkflow.infrastructure.cms.errors import WordPressAPIError


log = logging.getLogger(__name__)


@dataclass
class WordPressAdapterConfig:
    base_url: str
    user: str
    password: str
    timeout: float = 15.0
    verify_ssl: bool = True


class WordPressAdapter(WPPort):
    """
    WordPress REST adapter implementing WPPort using the /wp-json/wp/v2 endpoints.
    """

    def __init__(self, cfg: WordPressAdapterConfig):
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(cfg.user, cfg.password)
        self.session.headers.update({"Accept": "application/json"})


    def get_all_editors(self) -> Iterable[EditorResult]:
        """
        Fetch all WordPress users with the 'editor' role.

        Returns:
            Iterable[EditorResult]: A collection of editor records (id, email).
        """
        params = {
            "per_page": 100,
            "context":"edit",
            "roles": [ "editor" ],
            "_fields": "id,email"
        }
        results: List[EditorResult] = []
        for item in self._paginate("/wp-json/wp/v2/users", params=params):
            user_id = safe_int(item.get("id"))
            email = normalize_email(item.get("email"))
            if not user_id or not email:
                log.debug("Skipping user payload without id/email: %s", item)
                continue
            try:
                results.append(EditorResult(id=user_id, email=email))
            except ValidationError as exc:
                log.warning("Skipping WordPress user id=%s: %s", user_id, exc)
        return results

    def get_all_categories(self) -> Iterable[CategoryResult]:
        """
        Fetch all categories.

        Returns:
            Iterable[CategoryResult]: A list of category objects (id, name).
        """
        results: List[CategoryResult] = []
        for item in self._paginate("/wp-json/wp/v2/categories", params={"per_page": 100, "hide_empty": False}):
            category_id = safe_int(item.get("id"))
            name = normalize_category_name(item.get("name"))
            if not category_id or not name:
                log.debug("Skipping category payload without id/name: %s", item)
                continue
            try:
                results.append(CategoryResult(id=category_id, name=name))
            except ValidationError as exc:
                log.warning("Skipping WordPress category id=%s: %s", category_id, exc)
        return results

    def get_last_topics(self, request: TopicsRequest) -> Iterable[str]:
        """
        Fetch last published titles and draft titles.

        Args:
            request (TopicsRequest): published_num (count of published titles to fetch),
                                     draft_num (count of draft titles to fetch).

        Returns:
            Iterable[str]: Titles of posts (published + drafts), newest-first within each group.
        """
        published = self._fetch_post_titles(status="publish", limit=request.published_num)
        drafts = self._fetch_post_titles(status="draft", limit=request.draft_num)
        return published + drafts

    def create_draft_post(self, request: DraftCreationRequest) -> int:
        """
        Create a draft post.

        Args:
            request (DraftCreationRequest): topic (title), 
                                            content (HTML), 
                                            category_id (WP id), 
                                            editor_id (WP id).

        Returns:
            int: Created post ID.
        """
        author_id = ensure_positive_int(request.editor_id, "DraftCreationRequest.editor_id")
        category_id = ensure_positive_int(request.category_id, "DraftCreationRequest.category_id")
        payload = {
            "title": request.topic,
            "content": request.content,
            "status": "draft",
            "author": author_id,
            "categories": [category_id],
        }
        resp = self._post("/wp-json/wp/v2/posts", json=payload)
        data = self._json_or_error(resp)
        pid = data.get("id")
        if not isinstance(pid, int):
            raise WordPressAPIError(resp.status_code, resp.url, "Missing 'id' in post create response", data)
        log.debug("Created draft post id=%s for title=%r", pid, request.topic)
        return pid

    def upload_media(self, request: MediaUploadRequest) -> int:
        """
        Upload media and attach it to a post.

        Args:
            request (MediaUploadRequest): data (bytes), 
                                          topic (title/caption/alt), 
                                          post_id (WP id).

        Returns:
            int: Created media ID.
        """
        filename = f"{self._slugify(request.topic) or 'image'}.webp"
        ctype = mimetypes.guess_type(filename)[0] or "image/webp"
        post_id = ensure_positive_int(request.post_id, "MediaUploadRequest.post_id")

        files = {
            "file": (filename, request.data, ctype),
        }
        form = {
            "title": request.topic,
            "caption": request.topic,
            "alt_text": request.topic,
            "post": post_id,
        }
        resp = self._post("/wp-json/wp/v2/media", files=files, data=form)
        data = self._json_or_error(resp)
        mid = data.get("id")
        if not isinstance(mid, int):
            raise WordPressAPIError(resp.status_code, resp.url, "Missing 'id' in media upload response", data)
        log.debug("Uploaded media id=%s for post_id=%s", mid, request.post_id)
        return mid

    def update_post_with_media(self, request: PostMediaUpdateRequest) -> bool:
        """
        Set the post's featured image.

        Args:
            request (PostMediaUpdateRequest): post_id (WP id), 
                                              media_id (WP id).

        Returns:
            bool: True if update succeeded.
        """
        post_id = ensure_positive_int(request.post_id, "PostMediaUpdateRequest.post_id")
        media_id = ensure_positive_int(request.media_id, "PostMediaUpdateRequest.media_id")
        path = f"/wp-json/wp/v2/posts/{post_id}"
        resp = self._post(path, json={"featured_media": media_id}, method="POST")
        if resp.status_code in (200, 201):
            log.debug("Set featured_media=%s for post_id=%s", media_id, post_id)
            return True
        return False


    def _fetch_post_titles(self, *, status: str, limit: int) -> List[str]:
        titles: List[str] = []
        params = {
            "status": status,
            "per_page": min(100, max(1, limit)),
            "orderby": "date" if status == "publish" else "modified",
            "order": "desc",
            "_fields": "id,title",
        }
        for page_obj in self._paginate("/wp-json/wp/v2/posts", params=params):
            t = page_obj.get("title", {}).get("rendered") or ""
            t = self._strip_html(t).strip()
            if t:
                titles.append(t)
            if len(titles) >= limit:
                break
        return titles[:limit]


    def _paginate(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        page = 1
        params = dict(params or {})
        while True:
            params.update({"page": page})
            resp = self._get(path, params=params)
            data = self._json_or_error(resp)
            if not isinstance(data, list):
                raise WordPressAPIError(resp.status_code, resp.url, "Expected list response for pagination", data)
            for item in data:
                yield item
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or "1")
            if page >= total_pages:
                break
            page += 1

    def _get(self, path: str, params: Optional[dict] = None) -> Response:
        url = self.base + path
        resp = self.session.get(url, params=params, timeout=self.cfg.timeout, verify=self.cfg.verify_ssl)
        if resp.status_code >= 400:
            self._raise_for_error(resp)
        return resp

    def _post(
        self,
        path: str,
        *,
        json: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
        headers: Optional[dict] = None,
        method: str = "POST",
    ) -> Response:
        url = self.base + path
        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)
        request = self.session.request
        resp = request(
            method.upper(),
            url,
            json=json,
            data=data,
            files=files,
            headers=h,
            timeout=self.cfg.timeout,
            verify=self.cfg.verify_ssl,
        )
        if resp.status_code >= 400:
            self._raise_for_error(resp)
        return resp

    @staticmethod
    def _json_or_error(resp: Response) -> dict:
        try:
            return resp.json()
        except ValueError:
            raise WordPressAPIError(resp.status_code, resp.url, "Invalid JSON in response", {"text": resp.text[:500]})

    @staticmethod
    def _raise_for_error(resp: Response) -> None:
        try:
            payload = resp.json()
            msg = payload.get("message") or payload.get("error") or resp.text
        except ValueError:
            payload = {}
            msg = resp.text
        raise WordPressAPIError(resp.status_code, resp.url, msg.strip()[:500], payload)

    @staticmethod
    def _strip_html(s: str) -> str:
        return re.sub(r"<[^>]*>", "", s)

    @staticmethod
    def _slugify(text: str) -> str:
        s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
        s = re.sub(r"[\s_-]+", "-", s).strip("-")
        return s.lower()
