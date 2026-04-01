"""LLM model registry for bot2.

Defines supported models, their providers, and a factory function.
Reference models by their key constant (e.g. CLAUDE_HAIKU) everywhere
in code and in agent markdown frontmatter ``model:`` fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ModelProvider(str, Enum):
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"


@dataclass(frozen=True)
class ModelSpec:
    provider: ModelProvider
    model_name: str


# Key constants — use these in code and in agent markdown frontmatter.
CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5-20251001"
GEMINI_FLASH = "gemini-2.5-flash"
GEMINI_FLASH_LITE = "gemini-2.5-flash-lite"
GROQ_LLAMA_70B = "groq/llama-3.3-70b-versatile"

_REGISTRY: dict[str, ModelSpec] = {
    CLAUDE_SONNET:     ModelSpec(ModelProvider.ANTHROPIC, "claude-sonnet-4-6"),
    CLAUDE_HAIKU:      ModelSpec(ModelProvider.ANTHROPIC, "claude-haiku-4-5-20251001"),
    GEMINI_FLASH:      ModelSpec(ModelProvider.GOOGLE,    "gemini-2.5-flash"),
    GEMINI_FLASH_LITE: ModelSpec(ModelProvider.GOOGLE,    "gemini-2.5-flash-lite"),
    GROQ_LLAMA_70B:    ModelSpec(ModelProvider.GROQ,      "llama-3.3-70b-versatile"),
}


def load_model(key: str, **kwargs: Any) -> Any:
    """Return an Agno model instance for the given registry key.

    Args:
        key: One of the key constants (e.g. CLAUDE_HAIKU). Also accepts raw
            model-id strings that appear in agent markdown frontmatter, as
            long as they are registered in _REGISTRY.
        **kwargs: Extra arguments forwarded to the model constructor
            (e.g. cache_system_prompt=True).

    Raises:
        KeyError: If key is not in the registry.
    """
    spec = _REGISTRY[key]
    if spec.provider == ModelProvider.ANTHROPIC:
        from agno.models.anthropic import Claude
        return Claude(id=spec.model_name, **kwargs)
    if spec.provider == ModelProvider.GOOGLE:
        from agno.models.google.gemini import Gemini
        return Gemini(id=spec.model_name, **kwargs)
    if spec.provider == ModelProvider.GROQ:
        from agno.models.groq import Groq
        return Groq(id=spec.model_name, **kwargs)
    raise ValueError(f"Unhandled provider: {spec.provider}")
