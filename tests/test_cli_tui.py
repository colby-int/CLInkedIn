import asyncio

from job_scanner_cli import ConfigEditorScreen, JobScannerCLI
from textual.widgets import Input, Static, TextArea


class _FakeClient:
    def __init__(self) -> None:
        self.saved_payloads: list[dict] = []

    def get_status(self) -> dict:
        return {"is_running": False, "next_run_at": None, "last_run_error": ""}

    def get_jobs(self, **_: object) -> dict:
        return {"jobs": [], "updated_at": "2026-03-04T00:00:00+00:00"}

    def get_config(self) -> dict:
        return {"scan_keywords": "music", "scan_location": "Australia"}

    def save_config(self, payload: dict) -> dict:
        self.saved_payloads.append(payload)
        return {}


def test_cli_escape_moves_focus_from_search_to_table():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765")
        app.client = _FakeClient()

        async with app.run_test() as pilot:
            search_input = app.query_one("#search-input", Input)
            search_input.focus()
            assert search_input.has_focus

            await pilot.press("escape")
            await pilot.pause(0.1)

            assert not search_input.has_focus

    asyncio.run(run())


def test_cli_config_editor_open_and_cancel_without_crash():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765")
        app.client = _FakeClient()

        async with app.run_test() as pilot:
            base_screen = app.screen
            await app.action_edit_config()
            await pilot.pause(0.2)

            assert isinstance(app.screen, ConfigEditorScreen)
            app.screen.action_cancel()
            await pilot.pause(0.2)

            assert app.screen is base_screen

    asyncio.run(run())


def test_cli_config_editor_escape_closes_modal_without_nomatches():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765")
        app.client = _FakeClient()

        async with app.run_test() as pilot:
            base_screen = app.screen
            await app.action_edit_config()
            await pilot.pause(0.2)

            assert isinstance(app.screen, ConfigEditorScreen)
            await pilot.press("escape")
            await pilot.pause(0.2)

            assert app.screen is base_screen

    asyncio.run(run())


def test_cli_config_editor_stays_stable_during_background_ticks():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765", refresh_seconds=3)
        app.client = _FakeClient()

        async with app.run_test() as pilot:
            await app.action_edit_config()
            await pilot.pause(1.2)
            assert isinstance(app.screen, ConfigEditorScreen)

    asyncio.run(run())


def test_cli_config_editor_save_persists_payload():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765")
        fake_client = _FakeClient()
        app.client = fake_client

        async with app.run_test() as pilot:
            await app.action_edit_config()
            await pilot.pause(0.2)
            assert isinstance(app.screen, ConfigEditorScreen)

            editor = app.screen.query_one("#config-text", TextArea)
            editor.text = '{"scan_keywords": "python"}'
            app.screen.action_save()
            await pilot.pause(0.2)

            assert fake_client.saved_payloads == [{"scan_keywords": "python"}]

    asyncio.run(run())


def test_cli_config_editor_invalid_json_shows_error_and_stays_open():
    async def run() -> None:
        app = JobScannerCLI(api_base_url="http://localhost:8765")
        fake_client = _FakeClient()
        app.client = fake_client

        async with app.run_test() as pilot:
            await app.action_edit_config()
            await pilot.pause(0.2)
            assert isinstance(app.screen, ConfigEditorScreen)

            editor = app.screen.query_one("#config-text", TextArea)
            editor.text = "{"
            app.screen.action_save()
            await pilot.pause(0.2)

            error = app.screen.query_one("#config-error", Static)
            assert str(error.renderable)
            assert isinstance(app.screen, ConfigEditorScreen)
            assert fake_client.saved_payloads == []

    asyncio.run(run())
