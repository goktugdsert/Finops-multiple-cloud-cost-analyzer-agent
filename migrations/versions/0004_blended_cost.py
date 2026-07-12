"""blended cost: capture AWS BlendedCost as a FOCUS x_ extension column

Adds focus_costs.x_blended_cost (nullable NUMERIC). FOCUS defines no blended measure, so
AWS BlendedCost is captured here as a custom x_ extension for visibility/comparison only —
billed_cost remains the unblended invoiced amount. Nullable because only AWS reports it.

Revision ID: 0004_blended_cost
Revises: 0003_line_reconciliation
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_blended_cost"
down_revision: str | None = "0003_line_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: 0001's metadata.create_all builds the current schema (which already has
    # this column) on a fresh DB, so guard with IF NOT EXISTS. On an older DB it's added.
    op.execute("ALTER TABLE focus_costs ADD COLUMN IF NOT EXISTS x_blended_cost NUMERIC(20, 10)")


def downgrade() -> None:
    op.execute("ALTER TABLE focus_costs DROP COLUMN IF EXISTS x_blended_cost")
