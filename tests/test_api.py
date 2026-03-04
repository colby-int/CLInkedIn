import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_api_jobs_returns_newest_first(tmp_path: Path):
    jobs_file = tmp_path / "linkedin_jobs.json"
    jobs_file.write_text(
        json.dumps(
            [
                {
                    "title": "A",
                    "company": "X",
                    "location": "Remote",
                    "job_link": "https://example.com/a",
                    "posted_date": "2 weeks ago",
                },
                {
                    "title": "B",
                    "company": "Y",
                    "location": "Remote",
                    "job_link": "https://example.com/b",
                    "posted_date": "2 days ago",
                },
                {
                    "title": "C",
                    "company": "Z",
                    "location": "Remote",
                    "job_link": "https://example.com/c",
                    "posted_date": "N/A",
                },
            ]
        ),
        encoding="utf-8",
    )

    app = create_app(jobs_json_path=jobs_file, start_scheduler=False)
    client = TestClient(app)

    response = client.get("/api/jobs?include_older=true")
    assert response.status_code == 200

    payload = response.json()
    assert [job["title"] for job in payload["jobs"]] == ["B", "A", "C"]
    assert payload["count"] == 3
