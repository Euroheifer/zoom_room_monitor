"""Thin Zoom API client for the monitoring bridge.

Server-to-Server OAuth: exchanges account credentials for a short-lived access
token, caches it until it expires, and exposes a simple GET helper.

Credentials are read from the environment (see .env.example). This module never
prints or logs secret values.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any

import requests

ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"


class ZoomAuthError(RuntimeError):
    pass


class ZoomClient:
    def __init__(
        self,
        account_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: int = 30,
    ):
        self.account_id = account_id or os.environ.get("ZOOM_ACCOUNT_ID", "")
        self.client_id = client_id or os.environ.get("ZOOM_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("ZOOM_CLIENT_SECRET", "")
        self.timeout = timeout
        self._token: str | None = None
        self._token_expiry: float = 0.0

        missing = [
            name
            for name, val in (
                ("ZOOM_ACCOUNT_ID", self.account_id),
                ("ZOOM_CLIENT_ID", self.client_id),
                ("ZOOM_CLIENT_SECRET", self.client_secret),
            )
            if not val
        ]
        if missing:
            raise ZoomAuthError(
                f"Missing Zoom credentials in environment: {', '.join(missing)}"
            )

    # -- auth ---------------------------------------------------------------
    def _fetch_token(self) -> None:
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = requests.post(
            ZOOM_OAUTH_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            },
            headers={"Authorization": f"Basic {basic}"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            # Surface Zoom's error reason without echoing secrets.
            raise ZoomAuthError(
                f"Token request failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        self._token = data["access_token"]
        # Refresh a minute before actual expiry.
        self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60

    def _token_value(self) -> str:
        if not self._token or time.time() >= self._token_expiry:
            self._fetch_token()
        assert self._token is not None
        return self._token

    # -- requests -----------------------------------------------------------
    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        """GET an API path (e.g. '/rooms'). Returns the raw Response so callers
        can inspect status codes and Zoom error bodies (useful for scope checks).
        """
        url = ZOOM_API_BASE + path
        return requests.get(
            url,
            headers={"Authorization": f"Bearer {self._token_value()}"},
            params=params or {},
            timeout=self.timeout,
        )
