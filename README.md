# CLInked in

<p align="center">
  <img src="./logo-full.png" alt="CLInked in logo" width="720" />
</p>

CLInked in is a self-hosted LinkedIn jobs scanner with two frontends backed by the same API:
- a web dashboard,
- a colorful terminal dashboard (TUI/CLI).

It is designed for home-server deployment with Docker Compose, hourly auto-scanning, and a unified feed from parallel keyword/location targets.

## Features

### Feed and UX
- Unified jobs feed sorted by freshest posting age.
- Default filter shows only jobs posted in the last 3 days.
- Quick toggles for all jobs and starred-only view.
- Fast full-text search by title, company, location.
- One-click "Open on LinkedIn" action per row.

### Job workflow
- Star/unstar jobs and highlight starred rows.
- Persisted job exclusions and company exclusions.
- Exclusions are applied to future scans and feed rendering.

### Scanning and automation
- Hourly scheduler in the web service.
- Manual scan trigger from web and CLI.
- Parallel scanners for multiple keyword/location targets.
- Unified deduped feed across all enabled scan targets.

### Intelligence and enrichment
- Optional Groq-powered keyword expansion/refinement.
- Web logo matching/search pipeline with scoring by source, filename, filetype, and domain/name similarity.

### Interfaces
- **Web UI**: browser dashboard for feed + config + exclusions.
- **CLI/TUI**: non-flicker terminal UI with keyboard navigation, auto-refresh, and inline config editing.

## Credits

- Scraper baseline/reference: [luminati-io/LinkedIn-Scraper](https://github.com/luminati-io/LinkedIn-Scraper)

## Quick Start (Docker Compose)

```bash
docker compose up -d --build
```

Open web UI:
- `http://<your-server-ip>:8765`

## Run CLI Alongside Web

### Local

```bash
./.venv/bin/python job_scanner_cli.py --api-base-url http://127.0.0.1:8765
```

### Docker Compose profile

```bash
docker compose --profile cli run --rm linkedin-job-cli
```

CLI keys:
- `r` run scan
- `f` cycle feed filter (`recent` / `all` / `starred`)
- `s` star/unstar selected row
- `x` exclude selected job
- `c` exclude selected company
- `g` open JSON config editor
- `/` focus search
- `u` refresh now
- `q` quit

## Development

### Prereqs
- Python 3.12+ (project also works in current local `.venv`)
- Docker + Docker Compose (for containerized run)

### Local setup

```bash
./.venv/bin/pip install -r requirements-dev.txt
```

### Run API + web locally

```bash
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
```

### Run tests

```bash
./.venv/bin/python -m pytest -q
```

## Configuration

Primary runtime files (persisted in `./data`):
- `data/linkedin_jobs.json`
- `data/app_state.json`
- `data/scan_config.json`

Main env vars:
- `APP_PORT` (default `8765`)
- `SCAN_INTERVAL_MINUTES` (default `60`)
- `SCAN_ON_STARTUP` (default `true`)
- `SCAN_KEYWORDS`, `SCAN_LOCATION`, `SCAN_MAX_JOBS`
- `STATE_JSON_PATH`, `SCAN_CONFIG_PATH`, `JOBS_JSON_PATH`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `LOGO_EXTERNAL_SEARCH_ENABLED` (default `true`)

## Public Repo Hygiene

- Secrets are excluded by `.gitignore` (`.env`, `.env.*`).
- Use `.env.example` as your local template.
- Runtime JSON state and job data are excluded from git.
