from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib import parse, request


@dataclass(slots=True)
class DeviceCodeAuthProvider:
    tenant_id: str
    client_id: str
    scopes: list[str]
    redirect_uri: str
    timeout_seconds: int = 30

    def get_access_token(self) -> str:
        device_code = self._request_device_code()
        interval = int(device_code.get("interval", 5))
        expires_in = int(device_code["expires_in"])
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            response = self._request_token(device_code["device_code"])
            if "access_token" in response:
                return str(response["access_token"])
            if response.get("error") not in {"authorization_pending", "slow_down"}:
                raise RuntimeError(f"Delegated token request failed: {response}")
            time.sleep(interval + (5 if response.get("error") == "slow_down" else 0))
        raise TimeoutError("Timed out waiting for delegated Microsoft Graph authentication")

    def _request_device_code(self) -> dict[str, str]:
        payload = parse.urlencode(
            {"client_id": self.client_id, "scope": " ".join(self.scopes)}
        ).encode("utf-8")
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/devicecode"
        response = request.urlopen(
            request.Request(url, data=payload, method="POST"), timeout=self.timeout_seconds
        )
        return json.loads(response.read().decode("utf-8"))

    def _request_token(self, device_code: str) -> dict[str, str]:
        payload = parse.urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": device_code,
            }
        ).encode("utf-8")
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        response = request.urlopen(
            request.Request(url, data=payload, method="POST"), timeout=self.timeout_seconds
        )
        return json.loads(response.read().decode("utf-8"))
