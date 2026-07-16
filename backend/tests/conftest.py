import os
from collections.abc import Iterator
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(
        os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://da:da@127.0.0.1:55433/da_test")
    )
    with engine.begin() as c:
        c.execute(text("SELECT 1"))
    yield engine
    engine.dispose()
