"""initial FOCUS schema

Creates the FOCUS warehouse tables (incl. the reserved x_* attribution columns with the
'unattributed' fallback). To keep schema.py as the single source of truth for this v1
baseline, we create/drop directly from the SQLAlchemy metadata. Later, incremental
migrations will use explicit op.* operations.

Revision ID: 0001_focus_schema
Revises:
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mcca.warehouse.schema import metadata

# revision identifiers, used by Alembic.
revision: str = "0001_focus_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
