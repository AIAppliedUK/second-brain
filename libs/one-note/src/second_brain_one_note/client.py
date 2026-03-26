from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib import request
from urllib.error import HTTPError


class GraphTransport(Protocol):
    def request_json(self, url: str, headers: dict[str, str]) -> dict: ...

    def request_text(self, url: str, headers: dict[str, str]) -> str: ...


class UrlLibTransport:
    def request_json(self, url: str, headers: dict[str, str]) -> dict:
        req = request.Request(url, headers=headers, method="GET")
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def request_text(self, url: str, headers: dict[str, str]) -> str:
        req = request.Request(url, headers=headers, method="GET")
        with request.urlopen(req) as response:
            return response.read().decode("utf-8")


@dataclass(slots=True)
class RetryTransport:
    base_transport: GraphTransport
    retries: int = 3
    backoff_seconds: float = 1.0

    def request_json(self, url: str, headers: dict[str, str]) -> dict:
        for attempt in range(1, self.retries + 1):
            try:
                return self.base_transport.request_json(url, headers)
            except HTTPError as exc:
                if exc.code != 429 or attempt == self.retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else self.backoff_seconds * attempt)
        raise RuntimeError("Unreachable retry state")

    def request_text(self, url: str, headers: dict[str, str]) -> str:
        for attempt in range(1, self.retries + 1):
            try:
                return self.base_transport.request_text(url, headers)
            except HTTPError as exc:
                if exc.code != 429 or attempt == self.retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else self.backoff_seconds * attempt)
        raise RuntimeError("Unreachable retry state")


@dataclass(slots=True)
class GraphClient:
    access_token: str
    transport: GraphTransport
    user_agent: str

    def list_pages(self, since: str | None = None) -> list[dict]:
        url = "https://graph.microsoft.com/v1.0/me/onenote/pages?$top=100"
        if since:
            url += f"&$filter=lastModifiedDateTime ge {since}"
        return self._paginate(url)

    def list_sections(self) -> list[dict]:
        return self._paginate("https://graph.microsoft.com/v1.0/me/onenote/sections?$top=100")

    def list_notebooks(self) -> list[dict]:
        return self._paginate("https://graph.microsoft.com/v1.0/me/onenote/notebooks?$top=100")

    def get_page_content(self, page_id: str) -> str:
        url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
        return self.transport.request_text(url, self._headers(include_json=False))

    def _paginate(self, url: str) -> list[dict]:
        items: list[dict] = []
        next_url: str | None = url
        while next_url:
            payload = self.transport.request_json(next_url, self._headers())
            items.extend(payload.get("value", []))
            next_url = payload.get("@odata.nextLink")
        return items

    def _headers(self, include_json: bool = True) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": self.user_agent,
        }
        if include_json:
            headers["Accept"] = "application/json"
        return headers
