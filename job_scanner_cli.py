from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from app.cli_client import ApiError, JobScannerApiClient
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static, TextArea


class ConfigEditorScreen(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    ConfigEditorScreen {
      align: center middle;
      background: $background 65%;
    }
    #config-modal {
      width: 88%;
      height: 88%;
      border: wide $primary;
      background: $surface;
      padding: 1;
    }
    #config-title {
      color: $accent;
      margin-bottom: 1;
    }
    #config-error {
      color: $error;
      height: 2;
      margin-top: 1;
    }
    """

    def __init__(self, config_payload: dict) -> None:
        super().__init__()
        self._config_payload = config_payload

    def compose(self) -> ComposeResult:
        pretty = json.dumps(self._config_payload, indent=2, ensure_ascii=False)
        with Vertical(id="config-modal"):
            yield Static("Config Editor (Ctrl+S save, Esc cancel)", id="config-title")
            yield TextArea.code_editor(pretty, language="json", id="config-text")
            yield Static("", id="config-error")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        editor = self.query_one("#config-text", TextArea)
        error = self.query_one("#config-error", Static)

        try:
            payload = json.loads(editor.text)
            if not isinstance(payload, dict):
                raise ValueError("Config root must be a JSON object")
        except Exception as exc:  # noqa: BLE001
            error.update(str(exc))
            return

        self.dismiss(payload)


class JobScannerCLI(App):
    TITLE = "CLInked in CLI"

    CSS = """
    Screen {
      layout: vertical;
      background: #111827;
      color: #e2e8f0;
    }
    #status-line {
      height: 2;
      color: #93c5fd;
      background: #1f2937;
      padding: 0 1;
    }
    #search-input {
      margin: 0 1;
      background: #0f172a;
      color: #f8fafc;
    }
    #jobs-table {
      height: 1fr;
      margin: 0 1 1 1;
      background: #0b1220;
      color: #e5e7eb;
      border: round #334155;
    }
    #help-line {
      height: 2;
      background: #1e293b;
      color: #cbd5e1;
      padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("u", "refresh", "Refresh"),
        Binding("r", "run_scan", "Scan"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("s", "toggle_star", "Star"),
        Binding("x", "exclude_job", "Exclude Job"),
        Binding("c", "exclude_company", "Exclude Company"),
        Binding("g", "edit_config", "Config"),
        Binding("/", "focus_search", "Search"),
    ]

    def __init__(self, api_base_url: str, refresh_seconds: int = 7) -> None:
        super().__init__()
        self.client = JobScannerApiClient(api_base_url)
        self.refresh_seconds = max(3, refresh_seconds)

        self.filter_mode = "recent"  # recent | all | starred
        self.search = ""
        self.jobs: list[dict] = []
        self.jobs_signature = ""

        self.status_payload: dict = {}
        self.updated_at: str | None = None
        self.error_message = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Starting...", id="status-line")
        yield Input(placeholder="Search title, company, location", id="search-input")

        table = DataTable(id="jobs-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("★", "Posted", "Title", "Company", "Location", "Source")
        yield table

        yield Static(
            "Keys: r scan | f filter | s star | x exclude job | c exclude company | g config | / search | u refresh | q quit",
            id="help-line",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(1, self._tick_clock)
        self.set_interval(self.refresh_seconds, self._refresh_background)
        await self._refresh_all(force_table=True)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search-input":
            return
        self.search = event.value.strip()
        await self._refresh_jobs(force_table=True)

    @work(exclusive=True)
    async def _refresh_background(self) -> None:
        await self._refresh_all(force_table=False)

    async def _tick_clock(self) -> None:
        self._render_status_line()

    async def _refresh_all(self, *, force_table: bool) -> None:
        await self._refresh_status()
        await self._refresh_jobs(force_table=force_table)

    async def _refresh_status(self) -> None:
        try:
            self.status_payload = self.client.get_status() or {}
            self.error_message = self.status_payload.get("last_run_error") or ""
        except ApiError as exc:
            self.error_message = str(exc)
        self._render_status_line()

    async def _refresh_jobs(self, *, force_table: bool) -> None:
        params = {
            "include_older": self.filter_mode == "all",
            "starred_only": self.filter_mode == "starred",
            "search": self.search,
        }

        try:
            payload = self.client.get_jobs(**params) or {}
            jobs = payload.get("jobs") or []
            self.updated_at = payload.get("updated_at")
        except ApiError as exc:
            self.error_message = str(exc)
            self._render_status_line()
            return

        signature = "|".join(
            f"{job.get('job_link','')}:{job.get('is_starred', False)}:{job.get('posted_date','')}"
            for job in jobs
        )

        self.jobs = jobs
        if force_table or signature != self.jobs_signature:
            self.jobs_signature = signature
            self._render_table()

        self._render_status_line()

    def _render_table(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        prev_cursor = table.cursor_row

        table.clear()
        if not self.jobs:
            table.add_row("", "", "No jobs found", "", "", "")
            table.cursor_coordinate = (0, 0)
            return

        for job in self.jobs:
            star = "★" if job.get("is_starred") else "·"
            posted = str(job.get("posted_date", "-"))
            title = str(job.get("title", "Untitled"))
            company = str(job.get("company", "-"))
            location = str(job.get("location", "-"))
            source = str(job.get("scan_target_id", "default"))
            table.add_row(star, posted, title, company, location, source)

        row = min(prev_cursor, len(self.jobs) - 1)
        table.cursor_coordinate = (max(row, 0), 0)

    def _selected_job(self) -> dict | None:
        table = self.query_one("#jobs-table", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self.jobs):
            return None
        return self.jobs[row]

    def _status_text(self) -> str:
        running = bool(self.status_payload.get("is_running"))
        next_run_at = self.status_payload.get("next_run_at")
        jobs_count = len(self.jobs)

        next_run = "--"
        if next_run_at:
            try:
                dt = datetime.fromisoformat(next_run_at)
                remain = int((dt - datetime.now(timezone.utc)).total_seconds())
                if remain <= 0:
                    next_run = "soon"
                else:
                    mins, secs = divmod(remain, 60)
                    next_run = f"{mins}m {secs:02d}s"
            except Exception:  # noqa: BLE001
                next_run = "--"

        updated_label = self.updated_at or "--"
        scan_state = "RUNNING" if running else "IDLE"
        return (
            f"[{scan_state}] Filter={self.filter_mode} Jobs={jobs_count} "
            f"Next={next_run} Updated={updated_label}"
        )

    def _render_status_line(self) -> None:
        line = self.query_one("#status-line", Static)
        text = self._status_text()
        if self.error_message:
            text = f"{text}  Error: {self.error_message}"
        line.update(text)

    async def action_refresh(self) -> None:
        await self._refresh_all(force_table=True)

    async def action_run_scan(self) -> None:
        try:
            self.client.start_scan()
            self.error_message = ""
        except ApiError as exc:
            self.error_message = str(exc)
        await self._refresh_status()

    async def action_cycle_filter(self) -> None:
        order = ["recent", "all", "starred"]
        idx = order.index(self.filter_mode)
        self.filter_mode = order[(idx + 1) % len(order)]
        await self._refresh_jobs(force_table=True)

    async def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    async def action_toggle_star(self) -> None:
        job = self._selected_job()
        if not job:
            return

        link = str(job.get("job_link", "")).strip()
        if not link:
            return

        target_state = not bool(job.get("is_starred"))
        try:
            self.client.set_star(link, target_state)
            self.error_message = ""
        except ApiError as exc:
            self.error_message = str(exc)

        await self._refresh_jobs(force_table=True)

    async def action_exclude_job(self) -> None:
        job = self._selected_job()
        if not job:
            return

        link = str(job.get("job_link", "")).strip()
        if not link:
            return

        try:
            self.client.add_exclusion("job", link)
            self.error_message = ""
        except ApiError as exc:
            self.error_message = str(exc)

        await self._refresh_jobs(force_table=True)

    async def action_exclude_company(self) -> None:
        job = self._selected_job()
        if not job:
            return

        company = str(job.get("company", "")).strip()
        if not company:
            return

        try:
            self.client.add_exclusion("company", company)
            self.error_message = ""
        except ApiError as exc:
            self.error_message = str(exc)

        await self._refresh_jobs(force_table=True)

    async def action_edit_config(self) -> None:
        try:
            config = self.client.get_config()
        except ApiError as exc:
            self.error_message = str(exc)
            self._render_status_line()
            return

        payload = await self.push_screen_wait(ConfigEditorScreen(config))
        if payload is None:
            return

        try:
            self.client.save_config(payload)
            self.error_message = ""
        except ApiError as exc:
            self.error_message = str(exc)

        await self._refresh_all(force_table=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI dashboard for the CLInked in web API")
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("CLI_API_BASE_URL", "http://127.0.0.1:8765"),
        help="Base URL for the running web API",
    )
    parser.add_argument(
        "--refresh-seconds",
        default=int(os.getenv("CLI_REFRESH_SECONDS", "7")),
        type=int,
        help="Background refresh interval for jobs/status",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    app = JobScannerCLI(api_base_url=args.api_base_url, refresh_seconds=args.refresh_seconds)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
