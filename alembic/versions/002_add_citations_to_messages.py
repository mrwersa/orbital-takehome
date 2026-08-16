"""Add citation persistence columns to messages

Revision ID: 002_citations
Revises: 001_initial
Create Date: 2026-08-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_citations"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with a server_default so existing rows backfill to an empty
    # list rather than failing the ALTER on a non-empty table.
    op.add_column(
        "messages",
        sa.Column(
            "citations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "rejected_quotes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Nullable, no default: NULL means citation checking never ran for this
    # row (no document, or an error before there was an answer to check).
    op.add_column(
        "messages",
        sa.Column("answer_supported", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "answer_supported")
    op.drop_column("messages", "rejected_quotes")
    op.drop_column("messages", "citations")
