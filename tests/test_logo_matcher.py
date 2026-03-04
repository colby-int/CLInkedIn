from app.logo_matcher import LogoMatcher


def test_logo_matcher_selects_best_external_candidate(monkeypatch):
    matcher = LogoMatcher(allow_external_lookup=True)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "name": "Discord",
                    "domain": "discord.com",
                    "logo": "https://cdn.example.com/discord.svg",
                },
                {
                    "name": "Adobe",
                    "domain": "adobe.com",
                    "logo": "https://cdn.example.com/adobe-icon.svg",
                },
            ]

    def _fake_get(url: str, params=None, timeout=None):
        assert "clearbit" in url
        assert params["query"] == "Adobe Systems"
        return _FakeResponse()

    monkeypatch.setattr(matcher._session, "get", _fake_get)

    match = matcher.match_company("Adobe Systems")

    assert match is not None
    assert match["domain"] == "adobe.com"
    assert match["filename"] == "adobe-icon.svg"


def test_logo_matcher_uses_external_search(monkeypatch):
    matcher = LogoMatcher(allow_external_lookup=True)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "name": "OpenAI",
                    "domain": "openai.com",
                    "logo": "https://logo.clearbit.com/openai.com",
                }
            ]

    def _fake_get(url: str, params=None, timeout=None):
        assert "clearbit" in url
        assert params["query"] == "OpenAI"
        return _FakeResponse()

    monkeypatch.setattr(matcher._session, "get", _fake_get)

    match = matcher.match_company("OpenAI")

    assert match is not None
    assert match["source"] == "clearbit"
    assert match["domain"] == "openai.com"


def test_external_match_includes_source_filetype_and_filename(monkeypatch):
    matcher = LogoMatcher(allow_external_lookup=True)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "name": "Example Audio",
                    "domain": "exampleaudio.com",
                    "logo": "https://cdn.example.com/brand/example-audio-logo.svg",
                }
            ]

    monkeypatch.setattr(matcher._session, "get", lambda *_args, **_kwargs: _FakeResponse())

    match = matcher.match_company("Example Audio")

    assert match is not None
    assert match["source"] == "clearbit"
    assert match["filetype"] == "svg"
    assert match["filename"] == "example-audio-logo.svg"


def test_logo_matcher_can_disable_external_lookup(monkeypatch):
    matcher = LogoMatcher(allow_external_lookup=False)

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("External lookup should not be called when disabled")

    monkeypatch.setattr(matcher._session, "get", _fail_if_called)

    assert matcher.match_company("Adobe") is None
