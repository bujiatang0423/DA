from pathlib import Path
from backend.app.bootstrap.settings import Settings


def test_defaults_are_local_and_do_not_reference_la() -> None:
    settings = Settings(_env_file=None)
    assert settings.bind_host == "127.0.0.1"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.artifact_root == Path("data/artifacts")
    assert "/workspace/LA" not in settings.model_dump_json()
