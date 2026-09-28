"""Add passwordless browser authentication and question reports."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email", sa.String(320)))
        batch.create_unique_constraint("uq_users_email", ["email"])
        batch.create_index("ix_users_email", ["email"])
    op.create_table(
        "magic_link_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"])
    op.create_index("ix_magic_link_tokens_expires_at", "magic_link_tokens", ["expires_at"])
    op.create_index("ix_magic_link_tokens_created_at", "magic_link_tokens", ["created_at"])
    op.create_table(
        "browser_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"])
    op.create_index("ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"])
    op.create_table(
        "question_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reporter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reporter_id", "cluster_id", name="uq_reporter_cluster"),
    )
    op.create_index("ix_question_reports_reporter_id", "question_reports", ["reporter_id"])
    op.create_index("ix_question_reports_cluster_id", "question_reports", ["cluster_id"])
    op.create_index("ix_question_reports_status", "question_reports", ["status"])


def downgrade() -> None:
    op.drop_table("question_reports")
    op.drop_table("browser_sessions")
    op.drop_table("magic_link_tokens")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_email")
        batch.drop_constraint("uq_users_email", type_="unique")
        batch.drop_column("email")
