from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from app.date_utils import posted_date_to_minutes, sort_jobs_by_date
from app.keyword_refiner import GroqKeywordRefiner
from jobs_scraper import LinkedInJobsScraper


@dataclass(frozen=True)
class ScanTarget:
    id: str
    keywords: str
    location: str
    max_jobs: int
    enabled: bool = True


@dataclass(frozen=True)
class ExclusionRules:
    excluded_job_links: set[str]
    excluded_companies: set[str]


def _normalize_company(company: str) -> str:
    return " ".join(company.lower().strip().split())


def _write_jobs_atomic(output_path: Path, jobs: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", dir=output_path.parent, delete=False, encoding="utf-8") as tmp:
        json.dump(jobs, tmp, indent=2, ensure_ascii=False)
        temp_path = Path(tmp.name)

    temp_path.replace(output_path)


def apply_exclusions(jobs: Iterable[dict], exclusions: ExclusionRules) -> list[dict]:
    filtered: list[dict] = []
    for job in jobs:
        job_link = str(job.get("job_link", "")).strip()
        company = _normalize_company(str(job.get("company", "")))

        if job_link and job_link in exclusions.excluded_job_links:
            continue
        if company and company in exclusions.excluded_companies:
            continue

        filtered.append(job)
    return filtered


def _scrape_query(target: ScanTarget, query_keywords: str) -> list[dict]:
    scraper = LinkedInJobsScraper()
    scraped_jobs = scraper.scrape_jobs(
        keywords=query_keywords,
        location=target.location,
        max_jobs=target.max_jobs,
    )

    payload: list[dict] = []
    for job in scraped_jobs:
        item = vars(job)
        item["scan_target_id"] = target.id
        item["scan_keywords"] = target.keywords
        item["query_keywords"] = query_keywords
        payload.append(item)
    return payload


def _dedupe_jobs(jobs: list[dict]) -> list[dict]:
    by_link: dict[str, dict] = {}

    for job in jobs:
        job_link = str(job.get("job_link", "")).strip()
        if not job_link:
            continue

        current = by_link.get(job_link)
        if not current:
            by_link[job_link] = job
            continue

        current_minutes = posted_date_to_minutes(str(current.get("posted_date", "")))
        next_minutes = posted_date_to_minutes(str(job.get("posted_date", "")))
        if next_minutes < current_minutes:
            by_link[job_link] = job

    return list(by_link.values())


def _expand_keywords(
    target: ScanTarget,
    refiner: GroqKeywordRefiner | None,
    expansion_limit: int,
) -> list[str]:
    queries = [target.keywords]
    if refiner and expansion_limit > 0:
        queries.extend(refiner.refine(target.keywords, expansion_limit=expansion_limit))

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(query.strip())
    return deduped


def run_parallel_scans(
    targets: list[ScanTarget],
    exclusions: ExclusionRules,
    output_path: Path,
    max_parallel_scans: int,
    keyword_refiner: GroqKeywordRefiner | None = None,
    groq_expansions_per_target: int = 3,
) -> dict:
    active_targets = [target for target in targets if target.enabled]
    if not active_targets:
        _write_jobs_atomic(output_path=output_path, jobs=[])
        return {"job_count": 0, "scan_count": 0, "errors": []}

    jobs: list[dict] = []
    errors: list[str] = []
    scan_tasks: list[tuple[ScanTarget, str]] = []

    for target in active_targets:
        queries = _expand_keywords(
            target=target,
            refiner=keyword_refiner,
            expansion_limit=groq_expansions_per_target,
        )
        scan_tasks.extend((target, query) for query in queries)

    with ThreadPoolExecutor(max_workers=max(1, max_parallel_scans)) as pool:
        futures = {
            pool.submit(_scrape_query, target, query): (target, query)
            for target, query in scan_tasks
        }

        for future in as_completed(futures):
            target, query = futures[future]
            try:
                jobs.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{target.id}:{query} => {exc}")

    jobs = apply_exclusions(jobs, exclusions=exclusions)
    deduped_jobs = _dedupe_jobs(jobs)
    sorted_jobs = sort_jobs_by_date(deduped_jobs)
    _write_jobs_atomic(output_path=output_path, jobs=sorted_jobs)

    return {
        "job_count": len(sorted_jobs),
        "scan_count": len(scan_tasks),
        "errors": errors,
    }


def run_scan(
    keywords: str,
    location: str,
    max_jobs: int,
    output_path: Path,
) -> int:
    summary = run_parallel_scans(
        targets=[
            ScanTarget(
                id="single",
                keywords=keywords,
                location=location,
                max_jobs=max_jobs,
                enabled=True,
            )
        ],
        exclusions=ExclusionRules(excluded_job_links=set(), excluded_companies=set()),
        output_path=output_path,
        max_parallel_scans=1,
    )
    return int(summary["job_count"])


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan LinkedIn jobs and update the jobs JSON file.")
    parser.add_argument("--keywords", default=os.getenv("SCAN_KEYWORDS", "music"))
    parser.add_argument("--location", default=os.getenv("SCAN_LOCATION", "Australia"))
    parser.add_argument("--max-jobs", type=int, default=int(os.getenv("SCAN_MAX_JOBS", "100")))
    parser.add_argument(
        "--output",
        default=os.getenv("JOBS_JSON_PATH", "data/linkedin_jobs.json"),
        help="Path for JSON output file.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    output_path = Path(args.output)
    count = run_scan(
        keywords=args.keywords,
        location=args.location,
        max_jobs=args.max_jobs,
        output_path=output_path,
    )
    print(f"Updated {output_path} with {count} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
