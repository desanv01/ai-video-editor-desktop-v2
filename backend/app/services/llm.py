"""
LLM service - compatibility wrapper around the provider registry.
"""

import json
from typing import List, Optional

from providers import (
    ChatProvider,
    ChatRequest,
    EmbeddingProvider,
    EmbeddingRequest,
    ProviderKind,
    get_provider_registry,
)


class LLMService:
    """Handles existing LLM calls while delegating to typed AI providers."""

    def __init__(self):
        self.registry = get_provider_registry()

    async def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Send a chat completion request through the default chat provider.

        Args:
            messages: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            model: Override model name
            temperature: 0.0 = deterministic, 1.0 = creative
            response_format: {"type": "json_object"} for structured output

        Returns:
            The assistant's response text.
        """
        provider = self.registry.get(ProviderKind.CHAT)
        if not isinstance(provider, ChatProvider):
            raise TypeError("Default chat provider does not implement ChatProvider")

        response = await provider.chat(
            ChatRequest(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        )
        return response.text

    async def chat_json(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Send a chat request expecting JSON response.
        Automatically parses the response.
        """
        result = await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks.
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            raise ValueError(f"LLM did not return valid JSON: {result[:200]}")

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings through the default embedding provider.

        Args:
            texts: List of strings to embed

        Returns:
            List of embedding vectors
        """
        provider = self.registry.get(ProviderKind.EMBEDDING)
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("Default embedding provider does not implement EmbeddingProvider")

        response = await provider.embed(EmbeddingRequest(texts=texts))
        return response.embeddings

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single text string."""
        embeddings = await self.embed([text])
        return embeddings[0]


# Singleton
llm_service = LLMService()
