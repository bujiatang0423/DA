from alembic import context
from sqlalchemy import create_engine, pool
from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.persistence.models import Base

# Import every ORM module so Alembic compares the complete DA schema.
from backend.app.infrastructure.persistence import (  # noqa: F401
    legacy_rows,
    pit_rows,
    portfolio_rows,
    strict_pit_rows,
)
from backend.app.features.candidates import repository as candidate_rows  # noqa: F401
from backend.app.features.holdings import repository as holding_rows  # noqa: F401

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(Settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
