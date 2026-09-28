"""Add invite-only access records, research domains, and per-domain weekly selections."""
import uuid
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "20260927_0007"
down_revision = "20260926_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    access_status = sa.Enum("pending", "approved", "declined", "revoked", name="accessstatus",
                            native_enum=False)
    access = op.create_table(
        "access_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("discipline", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", access_status, nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_access_requests_email"),
    )
    op.create_index("ix_access_requests_email", "access_requests", ["email"])
    op.create_index("ix_access_requests_status", "access_requests", ["status"])
    op.create_index("ix_access_requests_created_at", "access_requests", ["created_at"])

    bind = op.get_bind()
    now = datetime.now(UTC)
    existing = bind.execute(sa.text("SELECT email FROM users WHERE email IS NOT NULL")).scalars()
    rows = [{"id": str(uuid.uuid4()), "email": email, "name": "", "role": "", "discipline": "",
             "note": "", "source": "existing", "status": "approved",
             "decision_reason": "Account existed before invite-only access.",
             "decided_by": None, "decided_at": now, "created_at": now} for email in existing]
    if rows:
        op.bulk_insert(access, rows)

    with op.batch_alter_table("question_submissions") as batch:
        batch.add_column(sa.Column("suggested_domain", sa.String(64)))
    with op.batch_alter_table("question_clusters") as batch:
        batch.add_column(sa.Column("domain", sa.String(64)))
        batch.create_index("ix_question_clusters_domain", ["domain"])

    selections = op.create_table(
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
    cycles = sa.table("weekly_cycles", sa.column("id", sa.String), sa.column("winner_cluster_id", sa.String),
                      sa.column("vote_snapshot", sa.JSON),
                      sa.column("frozen_at", sa.DateTime(timezone=True)))
    legacy = bind.execute(sa.select(cycles).where(cycles.c.winner_cluster_id.is_not(None))).mappings()
    rows = []
    for cycle in legacy:
        snapshot = cycle["vote_snapshot"] or {}
        votes = next((item["votes"] for item in snapshot.get("counts", [])
                      if item["cluster_id"] == cycle["winner_cluster_id"]), 0)
        rows.append({"id": str(uuid.uuid4()), "cycle_id": cycle["id"], "domain": "unassigned",
                     "cluster_id": cycle["winner_cluster_id"], "votes": votes,
                     "override": bool(snapshot.get("override")),
                     "created_at": cycle["frozen_at"] or now})
    if rows:
        op.bulk_insert(selections, rows)

    # Recreating weekly_cycles on SQLite would drop the partial one-open-cycle index, so it is
    # removed before the rebuild and restored explicitly afterwards.
    op.drop_index("uq_one_open_cycle", table_name="weekly_cycles")
    with op.batch_alter_table("weekly_cycles") as batch:
        batch.drop_column("winner_cluster_id")
    op.create_index("uq_one_open_cycle", "weekly_cycles", ["state"], unique=True,
                    postgresql_where=sa.text("state = 'open'"),
                    sqlite_where=sa.text("state = 'open'"))


def downgrade() -> None:
    op.drop_index("uq_one_open_cycle", table_name="weekly_cycles")
    with op.batch_alter_table("weekly_cycles") as batch:
        batch.add_column(sa.Column("winner_cluster_id", sa.String(36),
                                   sa.ForeignKey("question_clusters.id",
                                                 name="fk_weekly_cycles_winner")))
    op.create_index("uq_one_open_cycle", "weekly_cycles", ["state"], unique=True,
                    postgresql_where=sa.text("state = 'open'"),
                    sqlite_where=sa.text("state = 'open'"))
    op.execute(sa.text(
        "UPDATE weekly_cycles SET winner_cluster_id = (SELECT cluster_id FROM cycle_selections "
        "WHERE cycle_selections.cycle_id = weekly_cycles.id ORDER BY votes DESC, domain LIMIT 1)"))
    op.drop_table("cycle_selections")
    with op.batch_alter_table("question_clusters") as batch:
        batch.drop_index("ix_question_clusters_domain")
        batch.drop_column("domain")
    with op.batch_alter_table("question_submissions") as batch:
        batch.drop_column("suggested_domain")
    op.drop_table("access_requests")
