"""${message}"""
from alembic import op
import sqlalchemy as sa
revision = '${up_revision}'
down_revision = ${repr(down_revision)}
def upgrade() -> None: pass
def downgrade() -> None: pass
