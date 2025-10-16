from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth
from requests import Response

from thoughtsparkflow.domain.ports import (
    WPPort,
    EditorResult,
    CategoryResult,
    TopicsRequest,
    DraftCreationRequest,
    MediaUploadRequest,
    PostMediaUpdateRequest,
)
from pydantic import EmailStr


log = logging.getLogger(__name__)


class WordPressAPIError(RuntimeError):
    def __init__(self, status: int, url: str, message: str, payload: Optional[dict] = None):
        super().__init__(f"[{status}] {url} -> {message}")
        self.status = status
        self.url = url
        self.payload = payload or {}


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
        self._category_cache_by_name: Dict[str, int] = {}


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
        users = list(self._paginate("/wp-json/wp/v2/users", params=params))
        results: List[EditorResult] = []
        for u in users:
            results.append(
                EditorResult(
                    id=int(u.get("id")), 
                    email=EmailStr(u.get("email")),
                )
            )
        return results

    def get_all_categories(self) -> Iterable[CategoryResult]:
        """
        Fetch all categories (taxonomy 'category').

        Returns:
            Iterable[CategoryResult]: A list of category objects (id, name).

        Notes:
            - Uses pagination with per_page=100.
            - Also warms up in-memory cache (name -> id) for potential lookups.
        """
        cats: List[CategoryResult] = []
        for c in self._paginate("/wp-json/wp/v2/categories", params={"per_page": 100, "hide_empty": False}):
            name = (c.get("name") or "").strip()
            cid = c.get("id")
            if name and isinstance(cid, int):
                cats.append(CategoryResult(id=cid, name=name))
                self._category_cache_by_name[name.lower()] = cid
        return cats

    def get_last_topics(self, request: TopicsRequest) -> Iterable[str]:
        """
        Fetch last published titles and draft titles.

        Args:
            request (TopicsRequest): published_num (count of published titles to fetch),
                                     draft_num (count of draft titles to fetch; large value to get "all").

        Returns:
            Iterable[str]: Titles of posts (published + drafts), newest-first within each group.

        Notes:
            - Uses /wp/v2/posts with status filters ('publish', 'draft').
            - Requires authentication to access drafts.
        """
        published = self._fetch_post_titles(status="publish", limit=request.published_num)
        drafts = self._fetch_post_titles(status="draft", limit=request.draft_num)
        return published + drafts

    def create_draft_post(self, request: DraftCreationRequest) -> int:
        """
        Create a draft post.

        Args:
            request (DraftCreationRequest): topic (title), content (HTML),
                                            category_id (int), editor_id (WP user id).

        Returns:
            int: Created post ID.

        Notes:
            - Uses provided category_id.
            - Sets 'status'='draft' and 'author' to provided editor_id.
        """
        payload = {
            "title": request.topic,
            "content": request.content,
            "status": "draft",
            "author": request.editor_id,
            "categories": [int(request.category_id)] if request.category_id else [],
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
        Upload media (image) and attach it to a post.

        Args:
            request (MediaUploadRequest): data (bytes), topic (used for filename/alt),
                                          post_id (attachment parent).

        Returns:
            int: Created media (attachment) ID.

        Notes:
            - Uses multipart/form-data with /wp/v2/media.
            - Sets title/caption/alt_text from topic and 'post' to parent post id.
            - Guesses content-type using mimetypes (defaults to 'image/webp').
        """
        filename = f"{self._slugify(request.topic) or 'image'}.webp"
        ctype = mimetypes.guess_type(filename)[0] or "image/webp"

        files = {
            "file": (filename, request.data, ctype),
        }
        form = {
            "title": request.topic,
            "caption": request.topic,
            "alt_text": request.topic,
            "post": str(request.post_id),
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
            request (PostMediaUpdateRequest): post_id (int), media_id (int).

        Returns:
            bool: True if update succeeded.

        Notes:
            - Performs POST/PUT to /wp/v2/posts/{id} with 'featured_media'.
        """
        path = f"/wp-json/wp/v2/posts/{request.post_id}"
        resp = self._post(path, json={"featured_media": request.media_id}, method="POST")  # WP allows POST to update
        if resp.status_code in (200, 201):
            log.debug("Set featured_media=%s for post_id=%s", request.media_id, request.post_id)
            return True
        # Some sites prefer PUT
        resp2 = self._post(path, json={"featured_media": request.media_id}, method="PUT")
        ok = resp2.status_code in (200, 201)
        if not ok:
            self._raise_for_error(resp2)
        return ok


    def _fetch_post_titles(self, *, status: str, limit: int) -> List[str]:
        titles: List[str] = []
        params = {
            "status": status,
            "per_page": min(100, max(1, limit)),
            "orderby": "date" if status == "publish" else "modified",
            "order": "desc",
            "_fields": "id,title",  # reduce payload
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
