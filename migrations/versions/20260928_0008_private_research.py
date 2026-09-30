"""Add paid research accounts and private answers."""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0008"
down_revision = "20260927_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_submissions") as batch:
        batch.add_column(sa.Column("answer", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("answered_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("question_submissions") as batch:
        batch.drop_column("answered_at")
        batch.drop_column("answer")
