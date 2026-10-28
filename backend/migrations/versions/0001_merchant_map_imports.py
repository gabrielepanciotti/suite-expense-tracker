"""merchant_map + imports: the only data expenseTracker owns

Revision ID: 0001
Revises:
Create Date: 2026-09-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pattern", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("pattern", name="uq_merchant_map_pattern"),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_file", sa.String(), nullable=False),
        sa.Column("parsed", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reconciled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("imports")
    op.drop_table("merchant_map")
