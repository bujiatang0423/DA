from pathlib import Path

from pytest import MonkeyPatch

from backend.app.bootstrap.settings import Settings


def test_defaults_are_local_and_do_not_reference_la() -> None:
    settings = Settings(_env_file=None)
    assert settings.bind_host == "127.0.0.1"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.artifact_root == Path("data/artifacts")
    assert "/workspace/LA" not in settings.model_dump_json()


def test_deepseek_key_uses_the_unprefixed_local_env_name(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key == "test-key"
