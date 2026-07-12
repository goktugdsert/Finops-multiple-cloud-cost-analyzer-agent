"""recommendation_decisions table (the approval workflow)

Creates the `recommendation_decisions` table that persists a human's decision (approve /
dismiss / snooze) on a recommendation. Recommendations are always recomputed live from
routing + governance; only the decision is stored. Uses checkfirst so it is safe whether the
table was already created via metadata.create_all (create_schema) or not.

Revision ID: 0005_recommendation_decisions
Revises: 0004_blended_cost
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mcca.warehouse.schema import recommendation_decisions

revision: str = "0005_recommendation_decisions"
down_revision: str | None = "0004_blended_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    recommendation_decisions.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    recommendation_decisions.drop(op.get_bind(), checkfirst=True)
