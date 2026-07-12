"""snooze_until on recommendation_decisions (snooze with expiry)

Adds recommendation_decisions.snooze_until (nullable DATE). A SNOOZED recommendation
re-surfaces as PROPOSED once this date passes, so snooze is a temporary defer, not a silent
dismiss. Idempotent (0001's metadata.create_all builds the current schema on fresh DBs).

Revision ID: 0006_snooze_until
Revises: 0005_recommendation_decisions
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_snooze_until"
down_revision: str | None = "0005_recommendation_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE recommendation_decisions ADD COLUMN IF NOT EXISTS snooze_until DATE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recommendation_decisions DROP COLUMN IF EXISTS snooze_until")
