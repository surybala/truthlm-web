"""Add user research subscriptions and revocable personal feed credentials."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0006"
down_revision = "20260926_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value_key", sa.String(160), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "value_key", name="uq_research_subscription"),
    )
    op.create_index("ix_research_subscriptions_user_id", "research_subscriptions", ["user_id"])
    op.create_index("ix_research_subscriptions_kind", "research_subscriptions", ["kind"])
    op.create_table(
        "feed_access_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", name="uq_feed_access_tokens_user_id"),
    )
    op.create_index("ix_feed_access_tokens_user_id", "feed_access_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("feed_access_tokens")
    op.drop_table("research_subscriptions")
