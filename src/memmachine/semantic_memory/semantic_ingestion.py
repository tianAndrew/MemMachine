"""Ingestion pipeline for converting episodes into semantic features."""

import asyncio
import itertools
import logging
from itertools import chain

import numpy as np
from pydantic import BaseModel, InstanceOf, TypeAdapter

from memmachine.common.embedder import Embedder
from memmachine.episode_store.episode_model import Episode, EpisodeIdT
from memmachine.episode_store.episode_storage import EpisodeStorage
from memmachine.semantic_memory.semantic_llm import (
    LLMReducedFeature,
    llm_consolidate_features,
    llm_feature_update,
)
from memmachine.semantic_memory.semantic_model import (
    ResourceRetriever,
    Resources,
    SemanticCategory,
    SemanticCommand,
    SemanticCommandType,
    SemanticFeature,
    SetIdT,
)
from memmachine.semantic_memory.storage.storage_base import SemanticStorage

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Processes un-ingested history for each set_id and updates semantic features.

    The service pulls pending messages, invokes the LLM to generate mutation commands,
    applies the resulting changes, and optionally consolidates redundant memories.
    """

    class Params(BaseModel):
        """Dependencies and tuning knobs for the ingestion workflow."""

        semantic_storage: InstanceOf[SemanticStorage]
        history_store: InstanceOf[EpisodeStorage]
        resource_retriever: InstanceOf[ResourceRetriever]
        consolidated_threshold: int = 20
        debug_fail_loudly: bool = False

    def __init__(self, params: Params) -> None:
        """Initialize the ingestion service with storage backends and helpers."""
        self._semantic_storage = params.semantic_storage
        self._history_store = params.history_store
        self._resource_retriever = params.resource_retriever
        self._consolidation_threshold = params.consolidated_threshold
        self._debug_fail_loudly = params.debug_fail_loudly

    async def process_set_ids(self, set_ids: list[SetIdT]) -> None:
        results = await asyncio.gather(
            *[self._process_single_set(set_id) for set_id in set_ids],
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        if len(errors) > 0:
            raise ExceptionGroup("Failed to process set ids", errors)

    async def _process_single_set(self, set_id: str) -> None:  # noqa: C901
        logger.info("Processing set_id: %s", set_id)
        resources = self._resource_retriever.get_resources(set_id)

        history_ids = await self._semantic_storage.get_history_messages(
            set_ids=[set_id],
            limit=50,
            is_ingested=False,
        )
        logger.info(
            "Found %d uningested message(s) for set_id %s",
            len(history_ids),
            set_id,
        )

        logger.info(
            "Found %d semantic category/categories for set_id %s",
            len(resources.semantic_categories),
            set_id,
        )
        if len(resources.semantic_categories) == 0:
            logger.warning(
                "No semantic categories configured for set_id %s, marking messages as ingested",
                set_id,
            )
            await self._semantic_storage.mark_messages_ingested(
                set_id=set_id,
                history_ids=history_ids,
            )
            return

        if len(history_ids) == 0:
            return

        raw_messages = await asyncio.gather(
            *[self._history_store.get_episode(h_id) for h_id in history_ids],
            return_exceptions=True,
        )

        # Filter out None values and exceptions, log warnings for missing episodes
        valid_messages = []
        for i, msg in enumerate(raw_messages):
            if isinstance(msg, Exception):
                logger.warning(
                    "Failed to retrieve episode %s: %s",
                    history_ids[i],
                    msg,
                )
            elif msg is None:
                logger.warning(
                    "Episode %s not found in storage",
                    history_ids[i],
                )
            else:
                valid_messages.append(msg)

        if len(valid_messages) == 0:
            logger.warning(
                "No valid messages found for set_id %s, skipping",
                set_id,
            )
            # Mark all history_ids as ingested to avoid retrying
            await self._semantic_storage.mark_messages_ingested(
                set_id=set_id,
                history_ids=history_ids,
            )
            return

        messages = TypeAdapter(list[Episode]).validate_python(valid_messages)

        async def process_semantic_type(
            semantic_category: InstanceOf[SemanticCategory],
        ) -> None:
            logger.info(
                "Processing semantic category '%s' for set_id %s with %d message(s)",
                semantic_category.name,
                set_id,
                len(messages),
            )
            for message in messages:
                if message.uid is None:
                    raise ValueError(
                        "Message ID is None for message %s",
                        message.model_dump(),
                    )

                features = await self._semantic_storage.get_feature_set(
                    set_ids=[set_id],
                    category_names=[semantic_category.name],
                )
                logger.debug(
                    "Found %d existing feature(s) for category '%s'",
                    len(features),
                    semantic_category.name,
                )

                try:
                    logger.info(
                        "Calling LLM to extract features from message %s (content: %s...)",
                        message.uid,
                        message.content[:50] if message.content else "empty",
                    )
                    commands = await llm_feature_update(
                        features=features,
                        message_content=message.content,
                        model=resources.language_model,
                        update_prompt=semantic_category.prompt.update_prompt,
                    )
                    logger.info(
                        "LLM returned %d command(s) for message %s",
                        len(commands),
                        message.uid,
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to process message %s for semantic type %s: %s",
                        message.uid,
                        semantic_category.name,
                        e,
                    )
                    if self._debug_fail_loudly:
                        raise
                    # Still mark as processed to avoid infinite retries
                    if message.uid not in mark_messages:
                        mark_messages.append(message.uid)
                    continue

                if len(commands) == 0:
                    logger.info(
                        "LLM returned no commands for message %s in category '%s', marking as processed",
                        message.uid,
                        semantic_category.name,
                    )
                    if message.uid not in mark_messages:
                        mark_messages.append(message.uid)
                    continue

                try:
                    logger.info(
                        "Applying %d command(s) for message %s in category '%s'",
                        len(commands),
                        message.uid,
                        semantic_category.name,
                    )
                    await self._apply_commands(
                        commands=commands,
                        set_id=set_id,
                        category_name=semantic_category.name,
                        citation_id=message.uid,
                        embedder=resources.embedder,
                    )
                    logger.info(
                        "Successfully applied commands for message %s in category '%s'",
                        message.uid,
                        semantic_category.name,
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to apply commands for message %s in category '%s': %s",
                        message.uid,
                        semantic_category.name,
                        e,
                    )
                    # Still mark as processed to avoid infinite retries
                    if message.uid not in mark_messages:
                        mark_messages.append(message.uid)
                    continue

                if message.uid not in mark_messages:
                    mark_messages.append(message.uid)

        if len(resources.semantic_categories) == 0:
            logger.warning(
                "No semantic categories configured for set_id %s, marking all messages as ingested",
                set_id,
            )
            await self._semantic_storage.mark_messages_ingested(
                set_id=set_id,
                history_ids=history_ids,
            )
            return

        logger.info(
            "Processing %d message(s) with %d semantic category/categories",
            len(messages),
            len(resources.semantic_categories),
        )

        mark_messages: list[EpisodeIdT] = []
        semantic_category_runners = []
        for t in resources.semantic_categories:
            task = process_semantic_type(t)
            semantic_category_runners.append(task)

        await asyncio.gather(*semantic_category_runners)

        if len(mark_messages) == 0:
            logger.warning(
                "No messages were processed for set_id %s. Possible reasons:",
                set_id,
            )
            logger.warning(
                "  - LLM calls failed for all messages (check exception logs above)",
            )
            logger.warning(
                "  - LLM returned empty commands for all messages",
            )
            logger.warning(
                "  - _apply_commands failed silently",
            )
            # Don't return, still mark as ingested to avoid infinite retries
            # But log a warning so we know something is wrong
            logger.warning(
                "Marking all %d history_ids as ingested to prevent infinite retries",
                len(history_ids),
            )
            await self._semantic_storage.mark_messages_ingested(
                set_id=set_id,
                history_ids=history_ids,
            )
            return

        logger.info(
            "Marking %d message(s) as ingested for set_id %s",
            len(mark_messages),
            set_id,
        )
        await self._semantic_storage.mark_messages_ingested(
            set_id=set_id,
            history_ids=mark_messages,
        )

        await self._consolidate_set_memories_if_applicable(
            set_id=set_id,
            resources=resources,
        )

    async def _apply_commands(
        self,
        *,
        commands: list[SemanticCommand],
        set_id: SetIdT,
        category_name: str,
        citation_id: EpisodeIdT | None,
        embedder: InstanceOf[Embedder],
    ) -> None:
        for command in commands:
            match command.command:
                case SemanticCommandType.ADD:
                    logger.info(
                        "Adding feature: set_id=%s, category=%s, tag=%s, feature=%s, value=%s",
                        set_id,
                        category_name,
                        command.tag,
                        command.feature,
                        command.value[:100] if command.value else "empty",
                    )
                    value_embedding = (await embedder.ingest_embed([command.value]))[0]

                    f_id = await self._semantic_storage.add_feature(
                        set_id=set_id,
                        category_name=category_name,
                        feature=command.feature,
                        value=command.value,
                        tag=command.tag,
                        embedding=np.array(value_embedding),
                    )
                    logger.info(
                        "Successfully stored feature with id=%s for set_id=%s",
                        f_id,
                        set_id,
                    )

                    if citation_id is not None:
                        await self._semantic_storage.add_citations(f_id, [citation_id])
                        logger.info(
                            "Added citation: feature_id=%s, citation_id=%s",
                            f_id,
                            citation_id,
                        )

                case SemanticCommandType.DELETE:
                    await self._semantic_storage.delete_feature_set(
                        set_ids=[set_id],
                        category_names=[category_name],
                        feature_names=[command.feature],
                        tags=[command.tag],
                    )

                case _:
                    logger.error("Command with unknown action: %s", command.command)

    async def _consolidate_set_memories_if_applicable(
        self,
        *,
        set_id: SetIdT,
        resources: InstanceOf[Resources],
    ) -> None:
        async def _consolidate_type(
            semantic_category: InstanceOf[SemanticCategory],
        ) -> None:
            features = await self._semantic_storage.get_feature_set(
                set_ids=[set_id],
                category_names=[semantic_category.name],
                tag_threshold=self._consolidation_threshold,
                load_citations=True,
            )

            consolidation_sections: list[list[SemanticFeature]] = list(
                SemanticFeature.group_features_by_tag(features).values(),
            )

            await asyncio.gather(
                *[
                    self._deduplicate_features(
                        set_id=set_id,
                        memories=section_features,
                        resources=resources,
                        semantic_category=semantic_category,
                    )
                    for section_features in consolidation_sections
                ],
            )

        category_tasks = []
        for t in resources.semantic_categories:
            task = _consolidate_type(t)
            category_tasks.append(task)

        await asyncio.gather(*category_tasks)

    async def _deduplicate_features(
        self,
        *,
        set_id: str,
        memories: list[SemanticFeature],
        semantic_category: InstanceOf[SemanticCategory],
        resources: InstanceOf[Resources],
    ) -> None:
        try:
            consolidate_resp = await llm_consolidate_features(
                features=memories,
                model=resources.language_model,
                consolidate_prompt=semantic_category.prompt.consolidation_prompt,
            )
        except (ValueError, TypeError):
            logger.exception("Failed to update features while calling LLM")
            if self._debug_fail_loudly:
                raise
            return

        if consolidate_resp is None or consolidate_resp.keep_memories is None:
            logger.warning("Failed to consolidate features")
            if self._debug_fail_loudly:
                raise ValueError("Failed to consolidate features")
            return

        memories_to_delete = [
            m
            for m in memories
            if m.metadata.id is not None
            and m.metadata.id not in consolidate_resp.keep_memories
        ]
        await self._semantic_storage.delete_features(
            [m.metadata.id for m in memories_to_delete if m.metadata.id is not None],
        )

        merged_citations: chain[EpisodeIdT] = itertools.chain.from_iterable(
            [
                m.metadata.citations
                for m in memories_to_delete
                if m.metadata.citations is not None
            ],
        )
        citation_ids = TypeAdapter(list[EpisodeIdT]).validate_python(
            list(merged_citations),
        )

        async def _add_feature(f: LLMReducedFeature) -> None:
            value_embedding = (await resources.embedder.ingest_embed([f.value]))[0]

            f_id = await self._semantic_storage.add_feature(
                set_id=set_id,
                category_name=semantic_category.name,
                tag=f.tag,
                feature=f.feature,
                value=f.value,
                embedding=np.array(value_embedding),
            )

            await self._semantic_storage.add_citations(f_id, citation_ids)

        await asyncio.gather(
            *[
                _add_feature(feature)
                for feature in consolidate_resp.consolidated_memories
            ],
        )
