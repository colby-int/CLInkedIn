import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import _resolve_settings, create_app


def _write_json(path: Path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_app(tmp_path: Path):
    jobs_file = tmp_path / "linkedin_jobs.json"
    state_file = tmp_path / "app_state.json"
    config_file = tmp_path / "scan_config.json"

    _write_json(
        jobs_file,
        [
            {
                "title": "Recent",
                "company": "Adobe",
                "location": "Remote",
                "job_link": "https://example.com/recent",
                "posted_date": "2 days ago",
            },
            {
                "title": "Older",
                "company": "Discord",
                "location": "Remote",
                "job_link": "https://example.com/older",
                "posted_date": "2 weeks ago",
            },
        ],
    )
    _write_json(state_file, {"starred_job_links": [], "excluded_job_links": [], "excluded_companies": []})
    _write_json(
        config_file,
        {
            "scan_targets": [
                {
                    "id": "default",
                    "keywords": "music",
                    "location": "Australia",
                    "max_jobs": 25,
                    "enabled": True,
                }
            ],
            "max_parallel_scans": 2,
            "groq_refinement_enabled": False,
            "groq_expansions_per_target": 2,
        },
    )

    app = create_app(
        jobs_json_path=jobs_file,
        state_json_path=state_file,
        config_json_path=config_file,
        start_scheduler=False,
    )
    return TestClient(app)


def test_jobs_default_to_last_three_days(tmp_path: Path):
    client = _build_app(tmp_path)

    response = client.get("/api/jobs")
    assert response.status_code == 200
    payload = response.json()

    assert [job["title"] for job in payload["jobs"]] == ["Recent"]


def test_jobs_can_show_all_results(tmp_path: Path):
    client = _build_app(tmp_path)

    response = client.get("/api/jobs?include_older=true")
    assert response.status_code == 200
    payload = response.json()

    assert [job["title"] for job in payload["jobs"]] == ["Recent", "Older"]


def test_star_and_filter_starred(tmp_path: Path):
    client = _build_app(tmp_path)

    mark = client.post("/api/state/star", json={"job_link": "https://example.com/recent", "starred": True})
    assert mark.status_code == 200

    response = client.get("/api/jobs?include_older=true&starred_only=true")
    payload = response.json()

    assert [job["title"] for job in payload["jobs"]] == ["Recent"]
    assert payload["jobs"][0]["is_starred"] is True


def test_config_can_be_updated(tmp_path: Path):
    client = _build_app(tmp_path)

    update_payload = {
        "scan_targets": [
            {
                "id": "music-au",
                "keywords": "music industry",
                "location": "Australia",
                "max_jobs": 60,
                "enabled": True,
            },
            {
                "id": "live-events",
                "keywords": "live events",
                "location": "Remote",
                "max_jobs": 30,
                "enabled": True,
            },
        ],
        "max_parallel_scans": 3,
        "groq_refinement_enabled": True,
        "groq_expansions_per_target": 3,
    }

    put_response = client.put("/api/config", json=update_payload)
    assert put_response.status_code == 200

    get_response = client.get("/api/config")
    assert get_response.status_code == 200
    config = get_response.json()

    assert len(config["scan_targets"]) == 2
    assert config["max_parallel_scans"] == 3
    assert config["groq_refinement_enabled"] is True


def test_config_route_recovers_from_invalid_config_file(tmp_path: Path):
    jobs_file = tmp_path / "linkedin_jobs.json"
    state_file = tmp_path / "app_state.json"
    config_file = tmp_path / "scan_config.json"

    _write_json(jobs_file, [])
    _write_json(state_file, {"starred_job_links": [], "excluded_job_links": [], "excluded_companies": []})
    config_file.write_text("{not-json", encoding="utf-8")

    app = create_app(
        jobs_json_path=jobs_file,
        state_json_path=state_file,
        config_json_path=config_file,
        start_scheduler=False,
    )
    client = TestClient(app)

    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()

    assert payload["scan_targets"]
    assert payload["scan_targets"][0]["id"] == "default"


def test_resolve_settings_handles_invalid_env_ints(monkeypatch):
    monkeypatch.setenv("SCAN_MAX_JOBS", "not-a-number")
    monkeypatch.setenv("SCAN_INTERVAL_MINUTES", "bad")

    settings = _resolve_settings()

    assert settings.default_max_jobs == 100
    assert settings.scan_interval_minutes == 60
