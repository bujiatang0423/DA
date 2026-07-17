import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.postgres
def test_postgres_connection(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
