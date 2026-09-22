from app.config import merge_vocabulary_hints


def test_merge_unions_client_and_default_hints():
    result = merge_vocabulary_hints(["Big Mac"], ["combo", "no pickles"])
    assert result == ["Big Mac", "combo", "no pickles"]


def test_merge_dedupes_case_insensitively_keeping_first_occurrence():
    result = merge_vocabulary_hints(["No Onions"], ["combo", "no onions"])
    assert result == ["No Onions", "combo"]


def test_merge_with_empty_client_hints_returns_defaults():
    assert merge_vocabulary_hints([], ["combo", "upsize"]) == ["combo", "upsize"]


def test_merge_with_empty_default_hints_returns_client_hints():
    assert merge_vocabulary_hints(["Big Mac"], []) == ["Big Mac"]


def test_merge_strips_whitespace_and_drops_blank_entries():
    result = merge_vocabulary_hints([" Big Mac ", "  ", ""], ["combo"])
    assert result == ["Big Mac", "combo"]


def test_default_vocabulary_hints_env_override(monkeypatch):
    import importlib

    monkeypatch.setenv("DEFAULT_VOCABULARY_HINTS", "Whopper, no mayo")
    import app.config as config_module

    importlib.reload(config_module)
    try:
        assert config_module.settings.default_vocabulary_hints == ["Whopper", "no mayo"]
    finally:
        monkeypatch.delenv("DEFAULT_VOCABULARY_HINTS", raising=False)
        importlib.reload(config_module)  # restore process-wide settings for other tests
