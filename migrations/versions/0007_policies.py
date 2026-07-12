"""policies table (configurable governance policies)

Creates the `policies` table so governance rules are stored/configurable instead of hardcoded.
Uses checkfirst so it is safe whether the table was already created via metadata.create_all.

Revision ID: 0007_policies
Revises: 0006_snooze_until
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mcca.warehouse.schema import policies

revision: str = "0007_policies"
down_revision: str | None = "0006_snooze_until"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    policies.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    policies.drop(op.get_bind(), checkfirst=True)
