"""
sync_sqlalchemy_schema.

Revision ID: 3d6aaebdc526
Revises: 001
Create Date: 2025-11-04 20:32:38.622715

"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "3d6aaebdc526"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sync the database schema with the current SQLAlchemy models."""
    # Vector extension (no-op if already installed)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1) prof -> feature (rename), all inside TX
    # Guarded rename to avoid errors if already renamed by earlier runs
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name='prof'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name='feature'
            ) THEN
                ALTER TABLE prof RENAME TO feature;
            END IF;
        END$$;
        """,
    )

    # Column renames & transformations on feature
    # Check which columns exist before renaming
    op.execute(
        """
        DO $$
        BEGIN
            -- Rename user_id to set_id if user_id exists and set_id doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'user_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'set_id'
            ) THEN
                ALTER TABLE feature RENAME COLUMN user_id TO set_id;
            END IF;
            
            -- Rename tag to tag_id if tag exists and tag_id doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'tag'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'tag_id'
            ) THEN
                ALTER TABLE feature RENAME COLUMN tag TO tag_id;
            END IF;
            
            -- Rename create_at to created_at if create_at exists and created_at doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'create_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'created_at'
            ) THEN
                ALTER TABLE feature RENAME COLUMN create_at TO created_at;
            END IF;
            
            -- Rename update_at to updated_at if update_at exists and updated_at doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'update_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'updated_at'
            ) THEN
                ALTER TABLE feature RENAME COLUMN update_at TO updated_at;
            END IF;
        END$$;
        """,
    )
    
    with op.batch_alter_table("feature", schema=None) as b:
        # Add semantic_type_id if it doesn't exist
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'semantic_type_id'
                ) THEN
                    ALTER TABLE feature ADD COLUMN semantic_type_id VARCHAR DEFAULT 'default';
                END IF;
            END$$;
            """,
        )
        # Drop isolations if it exists
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'isolations'
                ) THEN
                    ALTER TABLE feature DROP COLUMN isolations;
                END IF;
            END$$;
            """,
        )

    # Type fixes / defaults
    # Change created_at type if it exists and is timestamptz
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'created_at'
                  AND data_type = 'timestamp with time zone'
            ) THEN
                ALTER TABLE feature ALTER COLUMN created_at TYPE timestamp USING created_at::timestamp;
            END IF;
        END$$;
        """,
    )
    # Change updated_at type if it exists and is timestamptz
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' 
                  AND column_name = 'updated_at'
                  AND data_type = 'timestamp with time zone'
            ) THEN
                ALTER TABLE feature ALTER COLUMN updated_at TYPE timestamp USING updated_at::timestamp;
            END IF;
        END$$;
        """,
    )
    # Change metadata type if it exists and is not jsonb
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feature' AND column_name = 'metadata'
            ) THEN
                -- Set default if not already set
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature' 
                      AND column_name = 'metadata'
                      AND column_default = '''{}''::jsonb'
                ) THEN
                    ALTER TABLE feature ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
                END IF;
                -- Change type if not already jsonb
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature' 
                      AND column_name = 'metadata'
                      AND data_type != 'jsonb'
                ) THEN
                    ALTER TABLE feature ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb;
                END IF;
            END IF;
        END$$;
        """,
    )

    # Indexes
    op.execute("DROP INDEX IF EXISTS prof_user_idx")
    # Drop existing indexes if they exist before creating new ones
    op.execute("DROP INDEX IF EXISTS idx_feature_set_id")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_id_semantic_type")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag_feature")
    # Create indexes
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_id'
            ) THEN
                CREATE INDEX idx_feature_set_id ON feature (set_id);
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
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_id_semantic_type'
            ) THEN
                CREATE INDEX idx_feature_set_id_semantic_type ON feature (set_id, semantic_type_id);
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
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_semantic_type_tag'
            ) THEN
                CREATE INDEX idx_feature_set_semantic_type_tag ON feature (set_id, semantic_type_id, tag_id);
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
                WHERE schemaname = 'public' AND indexname = 'idx_feature_set_semantic_type_tag_feature'
            ) THEN
                CREATE INDEX idx_feature_set_semantic_type_tag_feature ON feature (set_id, semantic_type_id, tag_id, feature);
            END IF;
        END$$;
        """,
    )

    # 2) history changes
    # Rename create_at to created_at if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'create_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'created_at'
            ) THEN
                ALTER TABLE history RENAME COLUMN create_at TO created_at;
            END IF;
        END$$;
        """,
    )
    # Change created_at type if it exists and is timestamptz
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' 
                  AND column_name = 'created_at'
                  AND data_type = 'timestamp with time zone'
            ) THEN
                ALTER TABLE history ALTER COLUMN created_at TYPE timestamp USING created_at::timestamp;
            END IF;
        END$$;
        """,
    )
    # Change metadata type if it exists and is not jsonb
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'metadata'
            ) THEN
                -- Set default if not already set
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'history' 
                      AND column_name = 'metadata'
                      AND column_default = '''{}''::jsonb'
                ) THEN
                    ALTER TABLE history ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
                END IF;
                -- Change type if not already jsonb
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'history' 
                      AND column_name = 'metadata'
                      AND data_type != 'jsonb'
                ) THEN
                    ALTER TABLE history ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb;
                END IF;
            END IF;
        END$$;
        """,
    )

    # 2a) New join table and backfill
    # Check if table exists before creating
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'set_ingested_history'
            ) THEN
                CREATE TABLE set_ingested_history (
                    set_id VARCHAR NOT NULL,
                    history_id INTEGER NOT NULL,
                    ingested BOOLEAN DEFAULT false,
                    PRIMARY KEY (set_id, history_id),
                    FOREIGN KEY(history_id) REFERENCES history (id) ON DELETE CASCADE ON UPDATE CASCADE
                );
            END IF;
        END$$;
        """,
    )
    # Backfill set_ingested_history only if history table has user_id column
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'user_id'
            ) THEN
                INSERT INTO set_ingested_history (set_id, history_id, ingested)
                SELECT user_id, id, COALESCE(ingested, false)
                FROM history
                WHERE user_id IS NOT NULL
                ON CONFLICT DO NOTHING;
            END IF;
        END$$;
        """,
    )

    # 2b) Drop legacy columns / indexes
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'user_id'
            ) THEN
                ALTER TABLE history DROP COLUMN user_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'ingested'
            ) THEN
                ALTER TABLE history DROP COLUMN ingested;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'history' AND column_name = 'isolations'
            ) THEN
                ALTER TABLE history DROP COLUMN isolations;
            END IF;
        END$$;
        """,
    )
    op.execute("DROP INDEX IF EXISTS history_user_idx")
    op.execute("DROP INDEX IF EXISTS history_user_ingested_idx")
    op.execute("DROP INDEX IF EXISTS history_user_ingested_ts_desc")

    # 3) citations column renames (preserve data) + rebuild FKs
    # Check if columns exist before renaming
    op.execute(
        """
        DO $$
        BEGIN
            -- Rename profile_id to feature_id if profile_id exists and feature_id doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'profile_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'feature_id'
            ) THEN
                ALTER TABLE citations RENAME COLUMN profile_id TO feature_id;
            END IF;
            
            -- Rename content_id to history_id if content_id exists and history_id doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'content_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'history_id'
            ) THEN
                ALTER TABLE citations RENAME COLUMN content_id TO history_id;
                -- Change type from INTEGER to VARCHAR if needed
                -- Check current type first
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'citations' 
                      AND column_name = 'history_id' 
                      AND data_type = 'integer'
                ) THEN
                    ALTER TABLE citations ALTER COLUMN history_id TYPE VARCHAR USING history_id::text;
                END IF;
            END IF;
        END$$;
        """,
    )

    # Drop existing FKs (unknown names) and recreate with explicit names
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'citations'::regclass
                  AND contype = 'f'
            LOOP
                EXECUTE format('ALTER TABLE citations DROP CONSTRAINT IF EXISTS %I', r.conname);
            END LOOP;
        END$$;
        """,
    )
    # Create foreign keys only if columns exist and constraints don't exist
    op.execute(
        """
        DO $$
        BEGIN
            -- Add foreign key for feature_id if it exists and constraint doesn't
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'feature_id'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'feature'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'citations'::regclass
                  AND conname = 'fk_citations_feature'
            ) THEN
                ALTER TABLE citations
                ADD CONSTRAINT fk_citations_feature
                FOREIGN KEY (feature_id) REFERENCES feature(id)
                ON DELETE CASCADE ON UPDATE CASCADE;
            END IF;
            
            -- Add foreign key for history_id if it exists and constraint doesn't
            -- Note: history_id is now VARCHAR (episode uid), not INTEGER (history.id),
            -- so we don't create a foreign key constraint for it.
            -- The Alembic migration will handle this properly.
        END$$;
        """,
    )


def downgrade() -> None:
    """Revert the schema changes applied in this migration."""
    # citations back
    with op.batch_alter_table("citations", schema=None) as b:
        with contextlib.suppress(Exception):
            b.drop_constraint("fk_citations_history", type_="foreignkey")
        with contextlib.suppress(Exception):
            b.drop_constraint("fk_citations_feature", type_="foreignkey")
    with op.batch_alter_table("citations", schema=None) as b:
        with contextlib.suppress(Exception):
            b.alter_column(
                "history_id",
                new_column_name="content_id",
                existing_type=sa.Integer,
            )
        with contextlib.suppress(Exception):
            b.alter_column(
                "feature_id",
                new_column_name="profile_id",
                existing_type=sa.Integer,
            )

    # history: add back legacy cols & data
    with op.batch_alter_table("history", schema=None) as b:
        b.add_column(sa.Column("user_id", sa.TEXT(), nullable=True))
        b.add_column(
            sa.Column(
                "ingested",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
        b.add_column(
            sa.Column(
                "isolations",
                pg.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
    op.execute(
        """
        UPDATE history h
        SET user_id = s.set_id,
            ingested = s.ingested
        FROM set_ingested_history s
        WHERE s.history_id = h.id
        """,
    )
    op.execute("CREATE INDEX IF NOT EXISTS history_user_idx ON history (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS history_user_ingested_idx ON history (user_id, ingested)",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS history_user_ingested_ts_desc ON history (user_id, ingested, created_at DESC)",
    )
    op.drop_table("set_ingested_history")

    # history type back
    op.alter_column(
        "history",
        "metadata",
        type_=pg.JSONB(),
        postgresql_using="metadata::jsonb",
        server_default=sa.text("'{}'::jsonb"),
    )
    op.alter_column(
        "history",
        "created_at",
        type_=pg.TIMESTAMP(timezone=True),
        postgresql_using="created_at::timestamptz",
    )
    with op.batch_alter_table("history", schema=None) as b:
        b.alter_column(
            "created_at",
            new_column_name="create_at",
            existing_type=pg.TIMESTAMP(timezone=True),
        )

    # feature -> prof back
    op.alter_column(
        "feature",
        "metadata",
        type_=pg.JSONB(),
        postgresql_using="metadata::jsonb",
        server_default=sa.text("'{}'::jsonb"),
    )
    op.alter_column(
        "feature",
        "updated_at",
        type_=pg.TIMESTAMP(timezone=True),
        postgresql_using="updated_at::timestamptz",
    )
    op.alter_column(
        "feature",
        "created_at",
        type_=pg.TIMESTAMP(timezone=True),
        postgresql_using="created_at::timestamptz",
    )
    with op.batch_alter_table("feature", schema=None) as b:
        b.add_column(
            sa.Column(
                "isolations",
                pg.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
        b.drop_column("semantic_type_id")
        b.alter_column(
            "updated_at",
            new_column_name="update_at",
            existing_type=pg.TIMESTAMP(timezone=True),
        )
        b.alter_column(
            "created_at",
            new_column_name="create_at",
            existing_type=pg.TIMESTAMP(timezone=True),
        )
        b.alter_column("tag_id", new_column_name="tag", existing_type=sa.TEXT())
        b.alter_column("set_id", new_column_name="user_id", existing_type=sa.TEXT())

    op.execute("DROP INDEX IF EXISTS idx_feature_set_id")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_id_semantic_type")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag")
    op.execute("DROP INDEX IF EXISTS idx_feature_set_semantic_type_tag_feature")
    op.execute("CREATE INDEX IF NOT EXISTS prof_user_idx ON feature (user_id)")

    # rename back to prof (transaction-safe)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name='feature'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name='prof'
            ) THEN
                ALTER TABLE feature RENAME TO prof;
            END IF;
        END$$;
        """,
    )
