"""Add immutable publication bundles and rendered articles."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0002"
down_revision = "20260926_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("publication_bundles",
        sa.Column("bundle_id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("cluster_id", sa.String(128), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_publication_bundles_request_id", "publication_bundles", ["request_id"])
    op.create_index("ix_publication_bundles_cluster_id", "publication_bundles", ["cluster_id"])
    op.create_table("articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bundle_id", sa.String(128), sa.ForeignKey("publication_bundles.bundle_id"),
                  nullable=False, unique=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_articles_slug", "articles", ["slug"])
    op.create_index("ix_articles_status", "articles", ["status"])
    op.create_index("ix_articles_published_at", "articles", ["published_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE TRIGGER publication_bundles_immutable BEFORE UPDATE OR DELETE ON "
                   "publication_bundles FOR EACH ROW EXECUTE FUNCTION orl_web_reject_mutation()")


def downgrade() -> None:
    op.drop_table("articles")
    op.drop_table("publication_bundles")
