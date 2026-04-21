from __future__ import annotations

import json
import os
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError


TOKEN_EXPIRY_SKEW_SECONDS = 120


@dataclass(slots=True)
class DeviceCodeAuthProvider:
    tenant_id: str
    client_id: str
    scopes: list[str]
    token_cache_path: Path | None = None
    auto_open_browser: bool = True
    timeout_seconds: int = 30
    on_device_code: Callable[[dict[str, Any]], None] | None = None

    def get_access_token(self) -> str:
        cached_tokens = self._load_cached_tokens()
        if cached_tokens and self._has_valid_access_token(cached_tokens):
            return str(cached_tokens["access_token"])
        if cached_tokens and cached_tokens.get("refresh_token"):
            refreshed_tokens = self._refresh_access_token(str(cached_tokens["refresh_token"]))
            if "access_token" in refreshed_tokens:
                normalized_tokens = self._normalize_token_response(
                    refreshed_tokens,
                    fallback_refresh_token=str(cached_tokens["refresh_token"]),
                )
                self._save_cached_tokens(normalized_tokens)
                return str(normalized_tokens["access_token"])
        device_code = self._request_device_code()
        if self.auto_open_browser:
            self._open_verification_uri(device_code)
        if self.on_device_code is not None:
            self.on_device_code(device_code)
        if "message" in device_code:
            print(str(device_code["message"]))
        interval = int(device_code.get("interval", 5))
        expires_in = int(device_code["expires_in"])
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            response = self._request_token(device_code["device_code"])
            if "access_token" in response:
                normalized_tokens = self._normalize_token_response(response)
                self._save_cached_tokens(normalized_tokens)
                return str(normalized_tokens["access_token"])
            if response.get("error") not in {"authorization_pending", "slow_down"}:
                raise RuntimeError(f"Delegated token request failed: {response}")
            time.sleep(interval + (5 if response.get("error") == "slow_down" else 0))
        raise TimeoutError("Timed out waiting for delegated Microsoft Graph authentication")

    def _request_device_code(self) -> dict[str, Any]:
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/devicecode"
        response = self._post_form(
            url, {"client_id": self.client_id, "scope": " ".join(self.scopes)}
        )
        if "error" in response:
            raise RuntimeError(f"Delegated device-code request failed: {response}")
        return response

    def _request_token(self, device_code: str) -> dict[str, Any]:
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        return self._post_form(
            url,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": device_code,
            },
        )

    def _refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        response = self._post_form(
            url,
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
                "scope": " ".join(self.scopes),
            },
        )
        if response.get("error"):
            return {}
        return response

    def _open_verification_uri(self, device_code: dict[str, Any]) -> None:
        verification_uri = device_code.get("verification_uri_complete") or device_code.get(
            "verification_uri"
        )
        if not verification_uri:
            return
        try:
            webbrowser.open(str(verification_uri), new=1)
        except Exception:
            return

    def _post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        payload = parse.urlencode(data).encode("utf-8")
        req = request.Request(url, data=payload, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except HTTPError as exc:
            raw_response = exc.read()
            if not raw_response:
                raise
        return json.loads(raw_response.decode("utf-8"))

    def _load_cached_tokens(self) -> dict[str, Any] | None:
        if self.token_cache_path is None or not self.token_cache_path.exists():
            return None
        try:
            payload = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            payload.get("tenant_id") != self.tenant_id
            or payload.get("client_id") != self.client_id
            or payload.get("scopes") != self.scopes
        ):
            return None
        return payload

    def _save_cached_tokens(self, tokens: dict[str, Any]) -> None:
        if self.token_cache_path is None:
            return
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "scopes": self.scopes,
            **tokens,
        }
        self.token_cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.token_cache_path, 0o600)
        except OSError:
            pass

    def _has_valid_access_token(self, tokens: dict[str, Any]) -> bool:
        access_token = tokens.get("access_token")
        expires_at = tokens.get("expires_at")
        if not access_token or not expires_at:
            return False
        return float(expires_at) > (time.time() + TOKEN_EXPIRY_SKEW_SECONDS)

    def _normalize_token_response(
        self,
        response: dict[str, Any],
        fallback_refresh_token: str | None = None,
    ) -> dict[str, Any]:
        refresh_token = response.get("refresh_token") or fallback_refresh_token
        expires_in = int(response.get("expires_in", 3600))
        normalized = {
            "access_token": str(response["access_token"]),
            "expires_at": time.time() + expires_in,
        }
        if refresh_token:
            normalized["refresh_token"] = str(refresh_token)
        return normalized
