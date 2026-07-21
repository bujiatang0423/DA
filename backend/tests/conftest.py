import os
from collections.abc import Iterator
import pytest
from sqlalchemy import NullPool, create_engine, text
from sqlalchemy.engine import Engine


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(
        os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://da:da@127.0.0.1:5432/da_test"),
        poolclass=NullPool,
        connect_args={"options": "-c idle_in_transaction_session_timeout=5000"},
    )
    with engine.begin() as c:
        c.execute(text("SELECT 1"))
    yield engine
    engine.dispose()
