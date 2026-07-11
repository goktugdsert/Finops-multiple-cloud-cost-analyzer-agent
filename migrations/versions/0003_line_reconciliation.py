"""line reconciliation: estimate flag + natural-identity upsert key

Adds two columns to focus_costs:
  - is_estimated: whether the source reported the line as an estimate (later restated).
  - line_key:     stable hash of the line's natural billing identity (NOT its amounts),
                  UNIQUE so re-ingesting a period upserts in place instead of duplicating.

Existing rows predate the key, so we backfill each with a unique value (md5 of its id)
to satisfy the NOT NULL + UNIQUE constraint. Those synthetic rows won't match future
ingests by identity, but v1 data is disposable/re-seedable, and every freshly ingested
line computes its real key via FocusRecord.natural_key(). Fresh installs get the final
shape directly from metadata.create_all.

Revision ID: 0003_line_reconciliation
Revises: 0002_budgets
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_line_reconciliation"
down_revision: str | None = "0002_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "focus_costs",
        sa.Column(
            "is_estimated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    # Add nullable, backfill existing rows with a unique placeholder, then enforce NOT NULL.
    op.add_column("focus_costs", sa.Column("line_key", sa.Text(), nullable=True))
    op.execute("UPDATE focus_costs SET line_key = md5(id::text) WHERE line_key IS NULL")
    op.alter_column("focus_costs", "line_key", nullable=False)
    op.create_unique_constraint("uq_focus_costs_line_key", "focus_costs", ["line_key"])


def downgrade() -> None:
    op.drop_constraint("uq_focus_costs_line_key", "focus_costs", type_="unique")
    op.drop_column("focus_costs", "line_key")
    op.drop_column("focus_costs", "is_estimated")
