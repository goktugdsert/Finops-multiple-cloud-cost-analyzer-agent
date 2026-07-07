"""budgets table

Creates the `budgets` table (monthly spend targets). Uses checkfirst so it is safe
whether the table was already created via metadata.create_all (create_schema) or not.

Revision ID: 0002_budgets
Revises: 0001_focus_schema
Create Date: 2026-07-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mcca.warehouse.schema import budgets

revision: str = "0002_budgets"
down_revision: str | None = "0001_focus_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    budgets.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    budgets.drop(op.get_bind(), checkfirst=True)
