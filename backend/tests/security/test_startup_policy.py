import pytest
from pydantic import ValidationError

from backend.app.bootstrap.settings import Settings


@pytest.mark.parametrize(
    ("authentication_enabled", "expected_explanation"),
    [
        (False, "authentication is disabled"),
        (True, "remote authentication is not implemented"),
    ],
)
def test_non_loopback_bind_is_rejected_regardless_of_authentication(
    authentication_enabled: bool,
    expected_explanation: str,
) -> None:
    with pytest.raises(ValidationError, match=rf"non-loopback.*{expected_explanation}"):
        Settings(
            _env_file=None,
            bind_host="0.0.0.0",
            authentication_enabled=authentication_enabled,
        )


def test_wildcard_allowed_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        Settings(_env_file=None, allowed_origins=("*",))


@pytest.mark.parametrize("bind_host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_bind_hosts_are_allowed(bind_host: str) -> None:
    settings = Settings(_env_file=None, bind_host=bind_host)

    assert settings.bind_host == bind_host


@pytest.mark.parametrize("bind_host", ["192.168.1.20", "example.com", "invalid host"])
def test_other_hosts_are_rejected(bind_host: str) -> None:
    with pytest.raises(ValidationError, match="non-loopback"):
        Settings(_env_file=None, bind_host=bind_host)
