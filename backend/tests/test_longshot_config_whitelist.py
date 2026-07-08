"""Whitelist env-override: lets one image run per-vein paper arms (sports/crypto
tails) without code changes. Default (unset) must stay the validated temp+sports set."""
from longshot.config import LongshotConfig, _DEFAULT_WHITELIST


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("LONGSHOT_WHITELIST", raising=False)
    assert LongshotConfig().whitelist == _DEFAULT_WHITELIST
    assert any(s.startswith("KXHIGH") for s in LongshotConfig().whitelist)


def test_override_parses_and_uppercases(monkeypatch):
    monkeypatch.setenv("LONGSHOT_WHITELIST", "kxmlbgame, KXWNBAGAME ,kxatpmatch")
    assert LongshotConfig().whitelist == ("KXMLBGAME", "KXWNBAGAME", "KXATPMATCH")


def test_override_ignores_blanks(monkeypatch):
    monkeypatch.setenv("LONGSHOT_WHITELIST", "KXBTCD,, ,KXETHD,")
    assert LongshotConfig().whitelist == ("KXBTCD", "KXETHD")


def test_empty_override_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("LONGSHOT_WHITELIST", "   ")
    assert LongshotConfig().whitelist == _DEFAULT_WHITELIST
