"""LLM helpers for extracting and consolidating semantic features."""

import json
import logging

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    TypeAdapter,
    validate_call,
)

from memmachine.common.language_model import LanguageModel
from memmachine.episode_store.episode_model import EpisodeIdT
from memmachine.semantic_memory.semantic_model import SemanticCommand, SemanticFeature

logger = logging.getLogger(__name__)


def _features_to_llm_format(
    features: list[SemanticFeature],
) -> dict[str, dict[str, str]]:
    structured_features: dict[str, dict[str, str]] = {}

    for feature in features:
        if feature.tag not in structured_features:
            structured_features[feature.tag] = {}

        structured_features.setdefault(feature.tag, {})[feature.feature_name] = (
            feature.value
        )

    return structured_features


class _SemanticFeatureUpdateRes(BaseModel):
    """Schema used to validate parsed feature-update commands returned by the LLM."""

    commands: list[SemanticCommand] = Field(default_factory=list)


@validate_call
async def llm_feature_update(
    features: list[SemanticFeature],
    message_content: str,
    model: InstanceOf[LanguageModel],
    update_prompt: str,
) -> list[SemanticCommand]:
    """Generate feature update commands from an incoming message using the LLM."""
    user_prompt = (
        "The old feature set is provided below:\n"
        "<OLD_PROFILE>\n"
        f"{json.dumps(_features_to_llm_format(features))}\n"
        "</OLD_PROFILE>\n"
        "\n"
        "The history is provided below:\n"
        "<HISTORY>\n"
        f"{message_content}\n"
        "</HISTORY>\n"
    )

    # Log the input for debugging
    logger.info(
        "LLM input - message content length: %d, existing features count: %d",
        len(message_content) if message_content else 0,
        len(features),
    )
    logger.debug(
        "LLM input - message content: %s",
        message_content[:200] if message_content else "empty",
    )
    logger.debug(
        "LLM input - existing features: %s",
        json.dumps(_features_to_llm_format(features))[:500] if features else "{}",
    )

    parsed_output = await model.generate_parsed_response(
        system_prompt=update_prompt,
        user_prompt=user_prompt,
        output_format=_SemanticFeatureUpdateRes,
    )

    # Log the raw LLM output
    logger.info(
        "LLM raw output (parsed_output): %s",
        parsed_output,
    )
    
    if parsed_output is None:
        logger.warning(
            "LLM returned None for message content: %s...",
            message_content[:100] if message_content else "empty",
        )
        return []

    try:
        # Log the parsed output before validation
        logger.info(
            "LLM parsed output (before validation): %s",
            parsed_output,
        )
        
        validated_output = TypeAdapter(_SemanticFeatureUpdateRes).validate_python(
            parsed_output,
        )
        
        # Log the validated output
        logger.info(
            "LLM validated output: %s",
            validated_output.model_dump_json() if hasattr(validated_output, "model_dump_json") else str(validated_output),
        )
        logger.info(
            "LLM commands count: %d, commands: %s",
            len(validated_output.commands),
            [cmd.model_dump() if hasattr(cmd, "model_dump") else str(cmd) for cmd in validated_output.commands],
        )
        return validated_output.commands
    except Exception as e:
        logger.exception(
            "Failed to validate LLM output. Raw output: %s, Error: %s",
            parsed_output,
            e,
        )
        return []


class LLMReducedFeature(BaseModel):
    """Minimal feature payload emitted by the consolidation prompt for reinsertion."""

    tag: str
    feature: str
    value: str


class SemanticConsolidateMemoryRes(BaseModel):
    """LLM response describing merged features and ids of features to retain."""

    consolidated_memories: list[LLMReducedFeature] = Field(default_factory=list)
    keep_memories: list[EpisodeIdT] | None
    model_config = ConfigDict(coerce_numbers_to_str=True)


@validate_call
async def llm_consolidate_features(
    features: list[SemanticFeature],
    model: InstanceOf[LanguageModel],
    consolidate_prompt: str,
) -> SemanticConsolidateMemoryRes | None:
    """Merge overlapping features and return consolidation commands from the LLM."""
    parsed_output = await model.generate_parsed_response(
        system_prompt=consolidate_prompt,
        user_prompt=json.dumps(_features_to_llm_format(features)),
        output_format=SemanticConsolidateMemoryRes,
    )

    if parsed_output is None:
        return None

    validated_output = TypeAdapter(SemanticConsolidateMemoryRes).validate_python(
        parsed_output,
    )
    return validated_output
