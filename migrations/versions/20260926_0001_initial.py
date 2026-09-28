"""Initial ORL Web question, voting, readiness, and metrics schema."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = sa.Enum("user", "moderator", "editor", "admin", "service", name="role", native_enum=False)
    moderation = sa.Enum("pending", "approved", "rejected", name="moderationstate", native_enum=False)
    public = sa.Enum("open", "selected", "answered", "deferred", "closed",
                     name="publicstatus", native_enum=False)
    cycle_state = sa.Enum("draft", "open", "frozen", name="cyclestate", native_enum=False)
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("external_subject", sa.String(200), nullable=False, unique=True),
        sa.Column("role", role, nullable=False),
        sa.Column("voting_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("question_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_question", sa.Text(), nullable=False),
        sa.Column("question_revision", sa.Integer(), nullable=False),
        sa.Column("public_status", public, nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_question_clusters_public_status", "question_clusters", ["public_status"])
    op.create_table("question_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submitter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("moderation_state", moderation, nullable=False),
        sa.Column("moderation_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("moderated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("submitter_id", "idempotency_key", name="uq_submission_idempotency"))
    op.create_index("ix_question_submissions_submitter_id", "question_submissions", ["submitter_id"])
    op.create_table("weekly_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cycle_key", sa.String(16), nullable=False, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", cycle_state, nullable=False),
        sa.Column("winner_cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id")),
        sa.Column("vote_snapshot", sa.JSON()),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_one_open_cycle", "weekly_cycles", ["state"], unique=True,
                    postgresql_where=sa.text("state = 'open'"),
                    sqlite_where=sa.text("state = 'open'"))
    op.create_table("cluster_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("question_submissions.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cluster_memberships_submission_id", "cluster_memberships", ["submission_id"])
    op.create_index("ix_cluster_memberships_cluster_id", "cluster_memberships", ["cluster_id"])
    op.create_index("uq_active_membership_submission", "cluster_memberships", ["submission_id"],
                    unique=True, postgresql_where=sa.text("active"), sqlite_where=sa.text("active = 1"))
    op.create_table("votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("cycle_id", sa.String(36), sa.ForeignKey("weekly_cycles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "cluster_id", "cycle_id", name="uq_vote_user_cluster_cycle"))
    for column in ("user_id", "cluster_id", "cycle_id"):
        op.create_index(f"ix_votes_{column}", "votes", [column])
    op.create_table("readiness_assessments",
        sa.Column("assessment_id", sa.String(128), primary_key=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("question_clusters.id"), nullable=False),
        sa.Column("question_revision", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("corpus_snapshot", sa.String(80), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_readiness_assessments_cluster_id", "readiness_assessments", ["cluster_id"])
    op.create_table("metrics_snapshots",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_metrics_snapshots_generated_at", "metrics_snapshots", ["generated_at"])
    op.create_table("audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("actor_id", "action", "target_id"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION orl_web_reject_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable ORL Web record'; END; $$ LANGUAGE plpgsql""")
        for table in ("audit_events", "metrics_snapshots"):
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                       "FOR EACH ROW EXECUTE FUNCTION orl_web_reject_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION orl_web_reject_mutation() CASCADE")
    for table in ("audit_events", "metrics_snapshots", "readiness_assessments", "votes",
                  "cluster_memberships", "weekly_cycles", "question_submissions",
                  "question_clusters", "users"):
        op.drop_table(table)
