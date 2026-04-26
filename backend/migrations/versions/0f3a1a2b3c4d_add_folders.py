"""add folders table

Revision ID: 0f3a1a2b3c4d
Revises: 69b8689f399d
Create Date: 2026-04-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0f3a1a2b3c4d"
down_revision: Union[str, None] = "69b8689f399d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("original", sa.String(length=2048), nullable=False),
        sa.Column("folder_path", sa.String(length=2048), nullable=False),
        sa.Column("is_git_clone", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("folders")

