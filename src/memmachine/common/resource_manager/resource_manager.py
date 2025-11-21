"""Resource manager wiring together storage, embedders, and models."""

import asyncio
from typing import Any

from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncEngine

from memmachine.common.configuration import Configuration
from memmachine.common.configuration.metrics_conf import WithMetricsFactoryId
from memmachine.common.embedder import Embedder
from memmachine.common.language_model import LanguageModel
from memmachine.common.metrics_factory import MetricsFactory
from memmachine.common.reranker import Reranker
from memmachine.common.resource_manager.database_manager import DatabaseManager
from memmachine.common.resource_manager.embedder_manager import EmbedderManager
from memmachine.common.resource_manager.language_model_manager import (
    LanguageModelManager,
)
from memmachine.common.resource_manager.reranker_manager import RerankerManager
from memmachine.common.resource_manager.semantic_manager import SemanticResourceManager
from memmachine.common.session_manager.session_data_manager import SessionDataManager
from memmachine.common.session_manager.session_data_manager_sql_impl import (
    SessionDataManagerSQL,
)
from memmachine.common.vector_graph_store import VectorGraphStore
from memmachine.episode_store.episode_sqlalchemy_store import (
    BaseEpisodeStore,
    SqlAlchemyEpisodeStore,
)
from memmachine.episode_store.episode_storage import EpisodeStorage
from memmachine.episodic_memory.episodic_memory_manager import (
    EpisodicMemoryManager,
    EpisodicMemoryManagerParams,
)
from memmachine.semantic_memory.semantic_session_manager import SemanticSessionManager
from memmachine.semantic_memory.storage.sqlalchemy_pgvector_semantic import (
    BaseSemanticStorage,
)


class ResourceManagerImpl:
    """Concrete resource manager for MemMachine services."""

    def __init__(self, conf: Configuration) -> None:
        """Initialize managers from configuration."""
        self._conf = conf
        self._conf.logging.apply()
        self._database_manager: DatabaseManager = DatabaseManager(
            self._conf.resources.databases
        )
        self._embedder_manager: EmbedderManager = EmbedderManager(
            self._conf.resources.embedders
        )
        self._model_manager: LanguageModelManager = LanguageModelManager(
            self._conf.resources.language_models,
        )
        self._reranker_manager: RerankerManager = RerankerManager(
            self._conf.resources.rerankers,
            embedder_factory=self._embedder_manager,
        )

        self._session_data_manager: SessionDataManager | None = None
        self._episodic_memory_manager: EpisodicMemoryManager | None = None

        self._episode_storage: EpisodeStorage | None = None
        self._semantic_manager: SemanticResourceManager | None = None

    async def build(self) -> None:
        """Build all configured resources in parallel."""
        tasks = [
            self._database_manager.build_all(validate=True),
            self._embedder_manager.build_all(),
            self._model_manager.build_all(),
            self._reranker_manager.build_all(),
        ]

        await asyncio.gather(*tasks)

        if self._session_data_manager is None:
            database = self._conf.session_manager.database
            engine = await self._database_manager.async_get_sql_engine(database)
            self._session_data_manager = SessionDataManagerSQL(engine)
            await self._session_data_manager.create_tables()

        if self._episode_storage is None:
            database = self._conf.episode_store.database
            engine = await self._database_manager.async_get_sql_engine(database)
            self._episode_storage = SqlAlchemyEpisodeStore(engine)
            async with engine.begin() as conn:
                # Only create vector extension for PostgreSQL
                if engine.dialect.name == "postgresql":
                    await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.run_sync(BaseEpisodeStore.metadata.create_all)
                # Add uid column if it doesn't exist (migration for existing tables)
                await self._add_uid_column_if_missing(conn, engine.dialect.name)
                # Only create semantic storage tables for PostgreSQL
                if engine.dialect.name == "postgresql":
                    await conn.run_sync(BaseSemanticStorage.metadata.create_all)
                    # Fix citations table column names if needed (migration for existing tables)
                    await self._fix_citations_table_columns(conn, engine.dialect.name)

    async def _add_uid_column_if_missing(
        self,
        conn: Any,
        dialect_name: str,
    ) -> None:
        """Add uid column to episodestore table if it doesn't exist."""
        from sqlalchemy import inspect, text

        # Check if column exists
        def check_and_add(sync_conn: Any) -> None:
            inspector = inspect(sync_conn.engine)
            table_exists = "episodestore" in inspector.get_table_names()
            
            if not table_exists:
                return  # Table doesn't exist, create_all will handle it
            
            columns = [col["name"] for col in inspector.get_columns("episodestore")]
            if "uid" in columns:
                return  # Column already exists
            
            # Add the column
            if dialect_name == "postgresql":
                # PostgreSQL doesn't support IF NOT EXISTS in ALTER TABLE ADD COLUMN
                # We check if column exists above, so we can safely add it
                try:
                    sync_conn.execute(
                        text("ALTER TABLE episodestore ADD COLUMN uid VARCHAR")
                    )
                    sync_conn.execute(
                        text("CREATE UNIQUE INDEX ix_episodestore_uid ON episodestore(uid)")
                    )
                    sync_conn.commit()
                except Exception:
                    # Column might have been added by another process, ignore
                    sync_conn.rollback()
                    pass
            elif dialect_name == "sqlite":
                # SQLite doesn't support IF NOT EXISTS in ALTER TABLE
                try:
                    sync_conn.execute(
                        text("ALTER TABLE episodestore ADD COLUMN uid VARCHAR")
                    )
                    sync_conn.execute(
                        text("CREATE INDEX IF NOT EXISTS ix_episodestore_uid ON episodestore(uid)")
                    )
                except Exception:
                    # Column might already exist, ignore
                    pass
        
        await conn.run_sync(check_and_add)

    async def _fix_citations_table_columns(
        self,
        conn: Any,
        dialect_name: str,
    ) -> None:
        """Fix citations table column names if they use old names."""
        from sqlalchemy import inspect, text

        def check_and_fix(sync_conn: Any) -> None:
            inspector = inspect(sync_conn.engine)
            table_exists = "citations" in inspector.get_table_names()
            
            if not table_exists:
                return  # Table doesn't exist, create_all will handle it
            
            columns = {col["name"]: col for col in inspector.get_columns("citations")}
            
            # Check if table has old column names
            has_old_columns = "profile_id" in columns or "content_id" in columns
            has_new_columns = "feature_id" in columns and "history_id" in columns
            
            if has_new_columns:
                return  # Already has correct columns
            
            if not has_old_columns:
                return  # Table exists but has neither old nor new columns, let create_all handle it
            
            # Migrate from old column names to new ones
            if dialect_name == "postgresql":
                try:
                    # First, drop all foreign key constraints on citations table
                    # This is necessary before changing column types
                    sync_conn.execute(
                        text("""
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
                        """)
                    )
                    
                    # Rename columns if they exist
                    if "profile_id" in columns and "feature_id" not in columns:
                        sync_conn.execute(
                            text("ALTER TABLE citations RENAME COLUMN profile_id TO feature_id")
                        )
                    if "content_id" in columns and "history_id" not in columns:
                        # Check if content_id is INTEGER, if so we need to change it to VARCHAR
                        if columns["content_id"]["type"].python_type == int:
                            # First rename, then change type
                            sync_conn.execute(
                                text("ALTER TABLE citations RENAME COLUMN content_id TO history_id")
                            )
                            sync_conn.execute(
                                text("ALTER TABLE citations ALTER COLUMN history_id TYPE VARCHAR USING history_id::text")
                            )
                        else:
                            sync_conn.execute(
                                text("ALTER TABLE citations RENAME COLUMN content_id TO history_id")
                            )
                    
                    # Recreate foreign key constraints if columns exist
                    # Note: history_id is now VARCHAR (episode uid), not INTEGER (history.id),
                    # so we don't create a foreign key constraint for it
                    sync_conn.execute(
                        text("""
                            DO $$
                            BEGIN
                                -- Add foreign key for feature_id if it exists and constraint doesn't
                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = 'public' AND table_name = 'citations' AND column_name = 'feature_id'
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
                                
                                -- Note: history_id is VARCHAR (episode uid), not INTEGER (history.id),
                                -- so we don't create a foreign key constraint for it.
                                -- The Alembic migration will handle this properly.
                            END$$;
                        """)
                    )
                    
                    sync_conn.commit()
                except Exception as e:
                    sync_conn.rollback()
                    # Log but don't fail - migration might have been done by another process
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Failed to migrate citations table columns: %s",
                        e,
                    )
        
        await conn.run_sync(check_and_fix)

    async def close(self) -> None:
        """Close resources and clean up state."""
        tasks = []
        if self._semantic_manager is not None:
            tasks.append(self._semantic_manager.close())

        tasks.append(self._database_manager.close())

        await asyncio.gather(*tasks)

    async def get_sql_engine(self, name: str) -> AsyncEngine:
        """Return a SQL engine by name."""
        return await self._database_manager.async_get_sql_engine(name)

    async def get_neo4j_driver(self, name: str) -> AsyncDriver:
        """Return a Neo4j driver by name."""
        return await self._database_manager.async_get_neo4j_driver(name)

    async def get_vector_graph_store(self, name: str) -> VectorGraphStore:
        """Return a vector graph store by name."""
        return await self._database_manager.async_get_vector_graph_store(name)

    async def get_embedder(self, name: str) -> Embedder:
        """Return an embedder by name."""
        return await self._embedder_manager.get_embedder(name)

    async def get_language_model(self, name: str) -> LanguageModel:
        """Return a language model by name."""
        return await self._model_manager.get_language_model(name)

    async def get_reranker(self, name: str) -> Reranker:
        """Return a reranker by name."""
        return await self._reranker_manager.get_reranker(name)

    @property
    def config(self) -> Configuration:
        """Return the configuration instance."""
        return self._conf

    @property
    def session_data_manager(self) -> SessionDataManager:
        """Return the session data manager."""
        if self._session_data_manager is None:
            raise RuntimeError(
                "session_data_manager must be initialized via build() first"
            )
        return self._session_data_manager


    @property
    def episodic_memory_manager(self) -> EpisodicMemoryManager:
        """Lazy-load the episodic memory manager."""
        if self._episodic_memory_manager is not None:
            return self._episodic_memory_manager
        session_data_manager = self.session_data_manager
        params = EpisodicMemoryManagerParams(
            resource_manager=self,
            session_data_manager=session_data_manager,
        )
        self._episodic_memory_manager = EpisodicMemoryManager(params)
        return self._episodic_memory_manager

    @property
    def episode_storage(self) -> EpisodeStorage:
        """Return the episode storage instance."""
        if self._episode_storage is not None:
            return self._episode_storage
        raise RuntimeError("episode_storage must be initialized via build() first")

    async def get_semantic_manager(self) -> SemanticResourceManager:
        """Return the semantic resource manager, constructing if needed."""
        if self._semantic_manager is not None:
            return self._semantic_manager

        self._semantic_manager = SemanticResourceManager(
            semantic_conf=self._conf.semantic_memory,
            prompt_conf=self._conf.prompt,
            resource_manager=self,
            episode_storage=self.episode_storage,
        )
        return self._semantic_manager

    async def get_semantic_session_manager(self) -> SemanticSessionManager:
        """Return the semantic session manager."""
        semantic_manager = await self.get_semantic_manager()
        return await semantic_manager.get_semantic_session_manager()

    @staticmethod
    async def get_metrics_factory(name: str) -> MetricsFactory:
        """Return the metrics factory by name."""
        factory_cache = WithMetricsFactoryId(metrics_factory_id=name)
        ret = factory_cache.get_metrics_factory()
        if ret is None:
            raise ValueError(f"MetricsFactory '{name}' could not be created.")
        return ret
