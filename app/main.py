from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Literal

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.date_utils import posted_date_to_minutes, sort_jobs_by_date
from app.keyword_refiner import GroqKeywordRefiner
from app.logo_matcher import LogoMatcher
from app.storage import read_json, write_json
from job_scanner import ExclusionRules, ScanTarget, apply_exclusions, run_parallel_scans

RECENT_WINDOW_DAYS = 3
RECENT_WINDOW_MINUTES = RECENT_WINDOW_DAYS * 24 * 60


class StarPayload(BaseModel):
    job_link: str
    starred: bool


class ExclusionPayload(BaseModel):
    mode: Literal["job", "company"]
    value: str


class ScanTargetPayload(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    keywords: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    max_jobs: int = Field(default=100, ge=1, le=500)
    enabled: bool = True


class ScanConfigPayload(BaseModel):
    scan_targets: list[ScanTargetPayload]
    max_parallel_scans: int = Field(default=2, ge=1, le=10)
    groq_refinement_enabled: bool = True
    groq_expansions_per_target: int = Field(default=3, ge=0, le=8)


@dataclass(frozen=True)
class AppSettings:
    default_keywords: str
    default_location: str
    default_max_jobs: int
    jobs_json_path: Path
    state_json_path: Path
    config_json_path: Path
    scan_interval_minutes: int
    scan_on_startup: bool
    logo_external_search_enabled: bool
    groq_api_key: str
    groq_model: str


class ScanRuntimeState:
    def __init__(self) -> None:
        self.lock = Lock()
        self.is_running = False
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_run_error: str | None = None
        self.last_job_count: int | None = None
        self.last_scan_count: int | None = None


def _normalize_company(company: str) -> str:
    return " ".join(company.lower().strip().split())


def _default_state_payload() -> dict[str, list[str]]:
    return {
        "starred_job_links": [],
        "excluded_job_links": [],
        "excluded_companies": [],
    }


def _default_config_payload(settings: AppSettings) -> dict[str, Any]:
    return {
        "scan_targets": [
            {
                "id": "default",
                "keywords": settings.default_keywords,
                "location": settings.default_location,
                "max_jobs": settings.default_max_jobs,
                "enabled": True,
            }
        ],
        "max_parallel_scans": 2,
        "groq_refinement_enabled": True,
        "groq_expansions_per_target": 3,
    }


def _read_jobs_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, list):
        return data
    return []


def _resolve_settings(
    jobs_json_path: Path | None = None,
    state_json_path: Path | None = None,
    config_json_path: Path | None = None,
) -> AppSettings:
    return AppSettings(
        default_keywords=os.getenv("SCAN_KEYWORDS", "music"),
        default_location=os.getenv("SCAN_LOCATION", "Australia"),
        default_max_jobs=int(os.getenv("SCAN_MAX_JOBS", "100")),
        jobs_json_path=jobs_json_path or Path(os.getenv("JOBS_JSON_PATH", "data/linkedin_jobs.json")),
        state_json_path=state_json_path or Path(os.getenv("STATE_JSON_PATH", "data/app_state.json")),
        config_json_path=config_json_path or Path(os.getenv("SCAN_CONFIG_PATH", "data/scan_config.json")),
        scan_interval_minutes=int(os.getenv("SCAN_INTERVAL_MINUTES", "60")),
        scan_on_startup=os.getenv("SCAN_ON_STARTUP", "true").lower() == "true",
        logo_external_search_enabled=os.getenv("LOGO_EXTERNAL_SEARCH_ENABLED", "true").lower() == "true",
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
    )


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _load_state(settings: AppSettings) -> dict[str, list[str]]:
    payload = read_json(settings.state_json_path, _default_state_payload())
    if not isinstance(payload, dict):
        return _default_state_payload()

    return {
        "starred_job_links": [str(item) for item in payload.get("starred_job_links", []) if str(item).strip()],
        "excluded_job_links": [str(item) for item in payload.get("excluded_job_links", []) if str(item).strip()],
        "excluded_companies": [str(item) for item in payload.get("excluded_companies", []) if str(item).strip()],
    }


def _save_state(settings: AppSettings, payload: dict[str, list[str]]) -> None:
    write_json(settings.state_json_path, payload)


def _load_config(settings: AppSettings) -> dict[str, Any]:
    payload = read_json(settings.config_json_path, _default_config_payload(settings))
    if not isinstance(payload, dict):
        payload = _default_config_payload(settings)

    try:
        parsed = ScanConfigPayload.model_validate(payload)
    except Exception:
        parsed = ScanConfigPayload.model_validate(_default_config_payload(settings))

    clean_payload = parsed.model_dump()
    if not clean_payload["scan_targets"]:
        clean_payload["scan_targets"] = _default_config_payload(settings)["scan_targets"]
    return clean_payload


def _save_config(settings: AppSettings, payload: dict[str, Any]) -> None:
    write_json(settings.config_json_path, payload)


def _build_exclusion_rules(state_payload: dict[str, list[str]]) -> ExclusionRules:
    return ExclusionRules(
        excluded_job_links={item.strip() for item in state_payload["excluded_job_links"] if item.strip()},
        excluded_companies={
            _normalize_company(item) for item in state_payload["excluded_companies"] if _normalize_company(item)
        },
    )


def _build_scan_targets(config_payload: dict[str, Any]) -> list[ScanTarget]:
    targets: list[ScanTarget] = []

    for row in config_payload["scan_targets"]:
        target = ScanTarget(
            id=str(row["id"]),
            keywords=str(row["keywords"]),
            location=str(row["location"]),
            max_jobs=int(row["max_jobs"]),
            enabled=bool(row.get("enabled", True)),
        )
        targets.append(target)

    return targets


class ScannerService:
    def __init__(self, settings: AppSettings, runtime_state: ScanRuntimeState, storage_lock: Lock) -> None:
        self.settings = settings
        self.runtime_state = runtime_state
        self.storage_lock = storage_lock

    def _scan_with_existing_lock(self) -> None:
        self.runtime_state.is_running = True
        self.runtime_state.last_run_started_at = datetime.now(timezone.utc)
        self.runtime_state.last_run_error = None

        try:
            with self.storage_lock:
                config_payload = _load_config(self.settings)
                state_payload = _load_state(self.settings)

            exclusions = _build_exclusion_rules(state_payload)
            targets = _build_scan_targets(config_payload)

            keyword_refiner = None
            if config_payload.get("groq_refinement_enabled") and self.settings.groq_api_key:
                keyword_refiner = GroqKeywordRefiner(
                    api_key=self.settings.groq_api_key,
                    model=self.settings.groq_model,
                )

            summary = run_parallel_scans(
                targets=targets,
                exclusions=exclusions,
                output_path=self.settings.jobs_json_path,
                max_parallel_scans=int(config_payload["max_parallel_scans"]),
                keyword_refiner=keyword_refiner,
                groq_expansions_per_target=int(config_payload["groq_expansions_per_target"]),
            )

            self.runtime_state.last_job_count = int(summary["job_count"])
            self.runtime_state.last_scan_count = int(summary["scan_count"])
            if summary["errors"]:
                self.runtime_state.last_run_error = " | ".join(summary["errors"])
        except Exception as exc:  # noqa: BLE001
            self.runtime_state.last_run_error = str(exc)
        finally:
            self.runtime_state.last_run_finished_at = datetime.now(timezone.utc)
            self.runtime_state.is_running = False
            self.runtime_state.lock.release()

    def scan(self) -> bool:
        if not self.runtime_state.lock.acquire(blocking=False):
            return False
        self._scan_with_existing_lock()
        return True

    def scan_async(self) -> bool:
        if not self.runtime_state.lock.acquire(blocking=False):
            return False
        Thread(target=self._scan_with_existing_lock, daemon=True).start()
        return True


def _hydrate_job(
    job: dict,
    starred_links: set[str],
    logo_matcher: LogoMatcher,
) -> dict:
    job_link = str(job.get("job_link", "")).strip()
    company_name = str(job.get("company", ""))

    return {
        **job,
        "posted_age_minutes": posted_date_to_minutes(str(job.get("posted_date", ""))),
        "is_starred": job_link in starred_links,
        "logo": logo_matcher.match_company(company_name),
    }


def create_app(
    jobs_json_path: Path | None = None,
    state_json_path: Path | None = None,
    config_json_path: Path | None = None,
    start_scheduler: bool = True,
) -> FastAPI:
    settings = _resolve_settings(
        jobs_json_path=jobs_json_path,
        state_json_path=state_json_path,
        config_json_path=config_json_path,
    )

    runtime_state = ScanRuntimeState()
    storage_lock = Lock()
    scanner = ScannerService(settings=settings, runtime_state=runtime_state, storage_lock=storage_lock)

    static_dir = Path(__file__).resolve().parent.parent / "static"
    logo_matcher = LogoMatcher(allow_external_lookup=settings.logo_external_search_enabled)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler: BackgroundScheduler | None = None
        if start_scheduler:
            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                scanner.scan,
                trigger="interval",
                minutes=settings.scan_interval_minutes,
                id="hourly-job-scan",
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now(timezone.utc) if settings.scan_on_startup else None,
            )
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)

    app = FastAPI(title="CLInked in", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def read_index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/jobs")
    def get_jobs(
        include_older: bool = Query(False),
        starred_only: bool = Query(False),
        search: str = Query(""),
    ) -> dict[str, Any]:
        with storage_lock:
            state_payload = _load_state(settings)

        starred_links = set(state_payload["starred_job_links"])

        jobs = _read_jobs_file(settings.jobs_json_path)
        jobs = apply_exclusions(jobs, exclusions=_build_exclusion_rules(state_payload))
        jobs = sort_jobs_by_date(jobs)

        hydrated_jobs = [_hydrate_job(job, starred_links=starred_links, logo_matcher=logo_matcher) for job in jobs]

        if not include_older:
            hydrated_jobs = [job for job in hydrated_jobs if job["posted_age_minutes"] <= RECENT_WINDOW_MINUTES]

        if starred_only:
            hydrated_jobs = [job for job in hydrated_jobs if job["is_starred"]]

        search_term = search.strip().lower()
        if search_term:
            hydrated_jobs = [
                job
                for job in hydrated_jobs
                if search_term in f"{job.get('title', '')} {job.get('company', '')} {job.get('location', '')}".lower()
            ]

        updated_at: str | None = None
        if settings.jobs_json_path.exists():
            updated_at = datetime.fromtimestamp(settings.jobs_json_path.stat().st_mtime, tz=timezone.utc).isoformat()

        return {
            "jobs": hydrated_jobs,
            "count": len(hydrated_jobs),
            "updated_at": updated_at,
            "default_recent_window_days": RECENT_WINDOW_DAYS,
            "is_scan_running": runtime_state.is_running,
        }

    @app.get("/api/status")
    def get_status() -> dict[str, Any]:
        next_run_at = None
        if runtime_state.last_run_started_at:
            next_run_at = runtime_state.last_run_started_at + timedelta(minutes=settings.scan_interval_minutes)

        return {
            "is_running": runtime_state.is_running,
            "last_run_started_at": _serialize_datetime(runtime_state.last_run_started_at),
            "last_run_finished_at": _serialize_datetime(runtime_state.last_run_finished_at),
            "last_run_error": runtime_state.last_run_error,
            "last_job_count": runtime_state.last_job_count,
            "last_scan_count": runtime_state.last_scan_count,
            "next_run_at": _serialize_datetime(next_run_at),
            "scan_interval_minutes": settings.scan_interval_minutes,
            "groq_enabled": bool(settings.groq_api_key),
        }

    @app.post("/api/scan")
    def trigger_scan() -> dict[str, Any]:
        started = scanner.scan_async()
        if not started:
            raise HTTPException(status_code=409, detail="A scan is already in progress")
        return {"message": "Scan started"}

    @app.get("/api/state")
    def get_state() -> dict[str, list[str]]:
        with storage_lock:
            return _load_state(settings)

    @app.post("/api/state/star")
    def update_star(payload: StarPayload) -> dict[str, list[str]]:
        with storage_lock:
            state_payload = _load_state(settings)

            starred = set(state_payload["starred_job_links"])
            if payload.starred:
                starred.add(payload.job_link)
            else:
                starred.discard(payload.job_link)

            state_payload["starred_job_links"] = sorted(starred)
            _save_state(settings, state_payload)
            return state_payload

    @app.post("/api/state/exclude")
    def add_exclusion(payload: ExclusionPayload) -> dict[str, list[str]]:
        value = payload.value.strip()
        if not value:
            raise HTTPException(status_code=400, detail="Value cannot be empty")

        with storage_lock:
            state_payload = _load_state(settings)

            if payload.mode == "job":
                entries = set(state_payload["excluded_job_links"])
                entries.add(value)
                state_payload["excluded_job_links"] = sorted(entries)
            else:
                existing = state_payload["excluded_companies"]
                normalized_existing = {_normalize_company(item): item for item in existing}
                normalized_value = _normalize_company(value)
                if normalized_value not in normalized_existing:
                    existing.append(value)
                state_payload["excluded_companies"] = sorted(existing, key=str.lower)

            _save_state(settings, state_payload)
            return state_payload

    @app.post("/api/state/unexclude")
    def remove_exclusion(payload: ExclusionPayload) -> dict[str, list[str]]:
        value = payload.value.strip()

        with storage_lock:
            state_payload = _load_state(settings)
            if payload.mode == "job":
                state_payload["excluded_job_links"] = [
                    item for item in state_payload["excluded_job_links"] if item != value
                ]
            else:
                normalized_target = _normalize_company(value)
                state_payload["excluded_companies"] = [
                    item
                    for item in state_payload["excluded_companies"]
                    if _normalize_company(item) != normalized_target
                ]

            _save_state(settings, state_payload)
            return state_payload

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        with storage_lock:
            config_payload = _load_config(settings)
        return config_payload

    @app.put("/api/config")
    def update_config(payload: ScanConfigPayload) -> dict[str, Any]:
        if not payload.scan_targets:
            raise HTTPException(status_code=400, detail="At least one scan target is required")

        unique_ids = {target.id for target in payload.scan_targets}
        if len(unique_ids) != len(payload.scan_targets):
            raise HTTPException(status_code=400, detail="Scan target ids must be unique")

        config_payload = payload.model_dump()

        with storage_lock:
            _save_config(settings, config_payload)

        return config_payload

    return app


app = create_app()
