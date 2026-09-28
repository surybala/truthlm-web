"""Add immutable-content article revisions and visible editorial history."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0003"
down_revision = "20260926_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("article_revisions",
        sa.Column("bundle_id", sa.String(128), sa.ForeignKey("publication_bundles.bundle_id"),
                  primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_bundle_id", sa.String(128)),
        sa.Column("correction_summary", sa.Text(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_id", "revision", name="uq_article_revision"))
    op.create_index("ix_article_revisions_article_id", "article_revisions", ["article_id"])
    op.create_index("ix_article_revisions_status", "article_revisions", ["status"])
    op.create_index("ix_article_revisions_published_at", "article_revisions", ["published_at"])
    op.execute("""INSERT INTO article_revisions
        (bundle_id, article_id, revision, supersedes_bundle_id, correction_summary, title, summary,
         markdown, status, published_at, review_note, created_at)
        SELECT bundle_id, id, 1, NULL, '', title, summary, markdown, status, published_at, '', created_at
        FROM articles""")


def downgrade() -> None:
    op.drop_table("article_revisions")
