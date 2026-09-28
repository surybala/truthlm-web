"""Add audited moderator resolution fields to question reports."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_reports") as batch:
        batch.add_column(sa.Column("resolution", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("resolved_by", sa.String(36),
                                   sa.ForeignKey("users.id", name="fk_question_reports_resolver")))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("question_reports") as batch:
        batch.drop_column("resolved_at")
        batch.drop_column("resolved_by")
        batch.drop_column("resolution")
