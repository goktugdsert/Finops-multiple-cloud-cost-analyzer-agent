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

from alembic import op

revision: str = "0003_line_reconciliation"
down_revision: str | None = "0002_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: migration 0001 runs metadata.create_all, which builds the CURRENT schema
    # (already including these columns) on a fresh DB, so guard every step with IF [NOT]
    # EXISTS. On an older DB the columns are genuinely added here.
    op.execute(
        "ALTER TABLE focus_costs "
        "ADD COLUMN IF NOT EXISTS is_estimated BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE focus_costs ADD COLUMN IF NOT EXISTS line_key TEXT")
    # Backfill any pre-existing rows with a unique placeholder, then enforce NOT NULL/UNIQUE.
    op.execute("UPDATE focus_costs SET line_key = md5(id::text) WHERE line_key IS NULL")
    op.execute("ALTER TABLE focus_costs ALTER COLUMN line_key SET NOT NULL")
    op.execute("ALTER TABLE focus_costs DROP CONSTRAINT IF EXISTS uq_focus_costs_line_key")
    op.execute("ALTER TABLE focus_costs ADD CONSTRAINT uq_focus_costs_line_key UNIQUE (line_key)")


def downgrade() -> None:
    op.execute("ALTER TABLE focus_costs DROP CONSTRAINT IF EXISTS uq_focus_costs_line_key")
    op.execute("ALTER TABLE focus_costs DROP COLUMN IF EXISTS line_key")
    op.execute("ALTER TABLE focus_costs DROP COLUMN IF EXISTS is_estimated")
