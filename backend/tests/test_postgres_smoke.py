import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.postgres
def test_postgres_connection(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.postgres
def test_postgres_fixture_sets_an_idle_transaction_timeout(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        seconds = connection.execute(
            text(
                "SELECT extract(epoch FROM current_setting("
                "'idle_in_transaction_session_timeout')::interval)"
            )
        ).scalar_one()

    assert seconds == 5
