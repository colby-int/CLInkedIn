import json

import pytest

from app.cli_client import ApiError, JobScannerApiClient


class DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload



def test_get_jobs_sends_expected_query_params(monkeypatch):
    captured = {}

    def fake_request(method, url, params=None, json=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        return DummyResponse(200, {"jobs": []})

    client = JobScannerApiClient("http://localhost:8765")
    monkeypatch.setattr(client.session, "request", fake_request)

    payload = client.get_jobs(include_older=True, starred_only=True, search="music")

    assert payload == {"jobs": []}
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/api/jobs")
    assert captured["params"] == {
        "include_older": "true",
        "starred_only": "true",
        "search": "music",
    }



def test_save_config_uses_put(monkeypatch):
    captured = {}

    def fake_request(method, url, params=None, json=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = json
        return DummyResponse(200, {"ok": True})

    client = JobScannerApiClient("http://localhost:8765")
    monkeypatch.setattr(client.session, "request", fake_request)

    payload = {"scan_targets": [{"id": "default", "keywords": "music", "location": "AU", "max_jobs": 10, "enabled": True}], "max_parallel_scans": 2, "groq_refinement_enabled": True, "groq_expansions_per_target": 2}
    out = client.save_config(payload)

    assert out == {"ok": True}
    assert captured["method"] == "PUT"
    assert captured["url"].endswith("/api/config")
    assert captured["json"] == payload



def test_request_raises_api_error_for_non_2xx(monkeypatch):
    def fake_request(method, url, params=None, json=None, timeout=None):
        return DummyResponse(409, {"detail": "A scan is already in progress"})

    client = JobScannerApiClient("http://localhost:8765")
    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ApiError) as exc:
        client.start_scan()

    assert "already in progress" in str(exc.value)
