"""Remove member voting and the paid research tier; add email delivery to subscribers."""
from alembic import op
import sqlalchemy as sa

revision = "20261004_0009"
down_revision = "20260928_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET role = 'user' WHERE role = 'paid'"))
    op.drop_table("votes")
    op.drop_table("cycle_selections")
    op.drop_index("uq_one_open_cycle", table_name="weekly_cycles")
    op.drop_table("weekly_cycles")
    with op.batch_alter_table("question_submissions") as batch:
        batch.drop_column("answered_at")
        batch.drop_column("answer")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("voting_eligible")
        batch.add_column(sa.Column("email_subscribed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("email_opt_out_at", sa.DateTime(timezone=True)))
    op.execute(sa.text("UPDATE users SET email_subscribed_at = created_at"))
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "article_id", name="uq_email_delivery_user_article"),
    )
    for column in ("user_id", "article_id", "status"):
        op.create_index(f"ix_email_deliveries_{column}", "email_deliveries", [column])


def downgrade() -> None:
    op.drop_table("email_deliveries")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_opt_out_at")
        batch.drop_column("email_subscribed_at")
        batch.add_column(sa.Column("voting_eligible", sa.Boolean(), nullable=False,
                                   server_default=sa.true()))
    with op.batch_alter_table("question_submissions") as batch:
        batch.add_column(sa.Column("answer", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("answered_at", sa.DateTime(timezone=True)))
    cycle_state = sa.Enum("draft", "open", "frozen", name="cyclestate", native_enum=False)
    op.create_table(
        "weekly_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cycle_key", sa.String(16), nullable=False, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", cycle_state, nullable=False),
        sa.Column("vote_snapshot", sa.JSON()),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_one_open_cycle", "weekly_cycles", ["state"], unique=True,
                    postgresql_where=sa.text("state = 'open'"),
                    sqlite_where=sa.text("state = 'open'"))
    op.create_table(
        "cycle_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cycle_id", sa.String(36), sa.ForeignKey("weekly_cycles.id"), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("votes", sa.Integer(), nullable=False),
        sa.Column("override", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cycle_id", "domain", name="uq_cycle_selection_domain"),
        sa.UniqueConstraint("cycle_id", "cluster_id", name="uq_cycle_selection_cluster"),
    )
    op.create_index("ix_cycle_selections_cycle_id", "cycle_selections", ["cycle_id"])
    op.create_table(
        "votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("cycle_id", sa.String(36), sa.ForeignKey("weekly_cycles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "cluster_id", "cycle_id", name="uq_vote_user_cluster_cycle"),
    )
    for column in ("user_id", "cluster_id", "cycle_id"):
        op.create_index(f"ix_votes_{column}", "votes", [column])
