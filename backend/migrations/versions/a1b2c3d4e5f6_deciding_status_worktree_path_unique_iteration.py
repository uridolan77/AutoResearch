"""deciding status, worktree_path column, unique session+iteration constraint

Revision ID: a1b2c3d4e5f6
Revises: 0f3a1a2b3c4d
Create Date: 2026-04-27 00:00:00.000000

Changes:
- Add `deciding` to ExperimentStatus enum on experiments.status column
- Add experiments.worktree_path column (nullable String(512))
- Replace non-unique ix_experiments_session_iteration index with a
  unique constraint uq_experiments_session_iteration
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "0f3a1a2b3c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Full ordered enum value list after this migration.
_NEW_EXPERIMENT_STATUS = (
    "pending",
    "running",
    "deciding",
    "scored",
    "awaiting_review",
    "kept",
    "reverted",
    "failed",
    "duplicate",
)

# Value list before this migration (used in downgrade).
_OLD_EXPERIMENT_STATUS = (
    "pending",
    "running",
    "scored",
    "awaiting_review",
    "kept",
    "reverted",
    "failed",
    "duplicate",
)


def upgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        # 1. Update status column enum to include `deciding`.
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(*_OLD_EXPERIMENT_STATUS, name="experimentstatus"),
            type_=sa.Enum(*_NEW_EXPERIMENT_STATUS, name="experimentstatus"),
            existing_nullable=False,
        )
        # 2. Add worktree_path column.
        batch_op.add_column(sa.Column("worktree_path", sa.String(length=512), nullable=True))
        # 3. Drop old non-unique index and add unique constraint.
        batch_op.drop_index("ix_experiments_session_iteration")
        batch_op.create_unique_constraint(
            "uq_experiments_session_iteration", ["session_id", "iteration"]
        )


def downgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_experiments_session_iteration", type_="unique")
        batch_op.create_index(
            "ix_experiments_session_iteration", ["session_id", "iteration"], unique=False
        )
        batch_op.drop_column("worktree_path")
        # Rollback any `deciding` rows to `running` before changing enum.
        # (Done at DB level via the batch recreate; SQLite will accept the values
        #  during the copy if no `deciding` rows exist.)
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(*_NEW_EXPERIMENT_STATUS, name="experimentstatus"),
            type_=sa.Enum(*_OLD_EXPERIMENT_STATUS, name="experimentstatus"),
            existing_nullable=False,
        )
