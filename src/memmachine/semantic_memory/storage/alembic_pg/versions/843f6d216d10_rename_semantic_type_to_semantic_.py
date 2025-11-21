"""
Rename semantic type to semantic category.

Revision ID: 843f6d216d10
Revises: 3d6aaebdc526
Create Date: 2025-11-11 10:54:06.010773

"""

from collections.abc import Sequence

import pgvector
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy.vector import VECTOR
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "843f6d216d10"
down_revision: str | Sequence[str] | None = "3d6aaebdc526"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename semantic_type_id to semantic_category_id if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'semantic_type_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'semantic_category_id'
            ) THEN
                ALTER TABLE feature RENAME COLUMN semantic_type_id TO semantic_category_id;
            END IF;
        END$$;
        """,
    )

    # Convert TEXT columns to VARCHAR if needed (TEXT and VARCHAR are compatible in PostgreSQL,
    # but we'll check to avoid unnecessary operations)
    # Note: PostgreSQL treats TEXT and VARCHAR as compatible types, so these conversions
    # are mainly for consistency. We'll skip if already VARCHAR.
    
    # Convert semantic_category_id type if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'semantic_category_id'
                  AND data_type = 'text'
            ) THEN
                ALTER TABLE feature ALTER COLUMN semantic_category_id TYPE VARCHAR;
            END IF;
        END$$;
        """,
    )
    
    # Convert created_at and updated_at to timestamptz if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'created_at'
                  AND data_type = 'timestamp without time zone'
            ) THEN
                ALTER TABLE feature ALTER COLUMN created_at TYPE timestamptz USING created_at::timestamptz;
            END IF;
        END$$;
        """,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'updated_at'
                  AND data_type = 'timestamp without time zone'
            ) THEN
                ALTER TABLE feature ALTER COLUMN updated_at TYPE timestamptz USING updated_at::timestamptz;
            END IF;
        END$$;
        """,
    )
    # Change embedding to nullable if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'embedding' AND is_nullable = 'NO'
            ) THEN
                ALTER TABLE feature ALTER COLUMN embedding DROP NOT NULL;
            END IF;
        END$$;
        """,
    )
    # Drop old indexes if they exist
    op.execute("DROP INDEX IF EXISTS idx_feature_set_id_semantic_type")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag_feature")
    # Create new indexes if they don't exist
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_id_semantic_category'
            ) THEN
                CREATE INDEX idx_feature_set_id_semantic_category ON feature (set_id, semantic_category_id);
            END IF;
        END$$;
        """,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_semantic_category_tag'
            ) THEN
                CREATE INDEX idx_feature_set_semantic_category_tag ON feature (set_id, semantic_category_id, tag_id);
            END IF;
        END$$;
        """,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_semantic_category_tag_feature'
            ) THEN
                CREATE INDEX idx_feature_set_semantic_category_tag_feature ON feature (set_id, semantic_category_id, tag_id, feature);
            END IF;
        END$$;
        """,
    )
    # Convert history.created_at to timestamptz if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' 
                  AND column_name = 'created_at'
                  AND data_type = 'timestamp without time zone'
            ) THEN
                ALTER TABLE history ALTER COLUMN created_at TYPE timestamptz USING created_at::timestamptz;
            END IF;
        END$$;
        """,
    )
    
    # Make history.metadata nullable if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' 
                  AND column_name = 'metadata' AND is_nullable = 'NO'
            ) THEN
                ALTER TABLE history ALTER COLUMN metadata DROP NOT NULL;
            END IF;
        END$$;
        """,
    )
    
    # Make set_ingested_history.ingested NOT NULL if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'set_ingested_history' 
                  AND column_name = 'ingested' AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE set_ingested_history ALTER COLUMN ingested SET NOT NULL;
            END IF;
        END$$;
        """,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "set_ingested_history",
        "ingested",
        existing_type=sa.BOOLEAN(),
        nullable=True,
        existing_server_default=sa.text("false"),
    )
    op.alter_column(
        "history",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "history",
        "metadata",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        existing_server_default=sa.text("'{}'::jsonb"),
    )
    op.alter_column(
        "history",
        "content",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.add_column(
        "feature",
        sa.Column(
            "semantic_type_id",
            sa.VARCHAR(),
            server_default=sa.text("'default'::character varying"),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.drop_index("idx_feature_set_semantic_category_tag_feature", table_name="feature")
    op.drop_index("idx_feature_set_semantic_category_tag", table_name="feature")
    op.drop_index("idx_feature_set_id_semantic_category", table_name="feature")
    op.create_index(
        op.f("idx_feature_set_semantic_type_tag_feature"),
        "feature",
        ["set_id", "semantic_type_id", "tag_id", "feature"],
        unique=False,
    )
    op.create_index(
        op.f("idx_feature_set_semantic_type_tag"),
        "feature",
        ["set_id", "semantic_type_id", "tag_id"],
        unique=False,
    )
    op.create_index(
        op.f("idx_feature_set_id_semantic_type"),
        "feature",
        ["set_id", "semantic_type_id"],
        unique=False,
    )
    op.alter_column(
        "feature",
        "embedding",
        existing_type=pgvector.sqlalchemy.vector.VECTOR(),
        nullable=False,
    )
    op.alter_column(
        "feature",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "feature",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "feature",
        "value",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "feature",
        "feature",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "feature",
        "tag_id",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
        existing_server_default=sa.text("'Miscellaneous'::text"),
    )
    op.alter_column(
        "feature",
        "set_id",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.drop_column("feature", "semantic_category_id")
    # ### end Alembic commands ###
