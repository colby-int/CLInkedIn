from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class ApiError(RuntimeError):
    pass


@dataclass
class JobScannerApiClient:
    base_url: str
    timeout_seconds: int = 12

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_payload,
            timeout=self.timeout_seconds,
        )

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code < 200 or response.status_code >= 300:
            detail = "Request failed"
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("message") or detail)
            elif response.text:
                detail = response.text.strip()
            raise ApiError(detail)

        return payload

    def get_jobs(self, *, include_older: bool, starred_only: bool, search: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/jobs",
            params={
                "include_older": "true" if include_older else "false",
                "starred_only": "true" if starred_only else "false",
                "search": search,
            },
        )

    def get_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def get_state(self) -> dict[str, Any]:
        return self._request("GET", "/api/state")

    def get_config(self) -> dict[str, Any]:
        return self._request("GET", "/api/config")

    def start_scan(self) -> dict[str, Any]:
        return self._request("POST", "/api/scan")

    def set_star(self, job_link: str, starred: bool) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/state/star",
            json_payload={"job_link": job_link, "starred": starred},
        )

    def add_exclusion(self, mode: str, value: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/state/exclude",
            json_payload={"mode": mode, "value": value},
        )

    def remove_exclusion(self, mode: str, value: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/state/unexclude",
            json_payload={"mode": mode, "value": value},
        )

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", "/api/config", json_payload=payload)
