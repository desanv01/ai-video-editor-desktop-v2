"""
LLM service — wraps DeepSeek API for all reasoning tasks.
DeepSeek uses OpenAI-compatible API format, so we use the OpenAI client.
"""

import json
from openai import AsyncOpenAI
from typing import Optional, List
from config import settings


class LLMService:
    """Handles all LLM calls (DeepSeek for reasoning, OpenAI for embeddings)."""

    def __init__(self):
        # DeepSeek client (OpenAI-compatible API)
        self.deepseek = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )
        # OpenAI client (for embeddings)
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Send a chat completion request to DeepSeek.

        Args:
            messages: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            model: Override model name
            temperature: 0.0 = deterministic, 1.0 = creative
            response_format: {"type": "json_object"} for structured output

        Returns:
            The assistant's response text.
        """
        kwargs = {
            "model": model or settings.AGENT2_MODEL,  # default to Agent 2's model; agents override as needed
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await self.deepseek.chat.completions.create(**kwargs)
        return response.choices[0].message.content

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
            # Try to extract JSON from markdown code blocks
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            raise ValueError(f"LLM did not return valid JSON: {result[:200]}")

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings using OpenAI API.

        Args:
            texts: List of strings to embed

        Returns:
            List of embedding vectors
        """
        response = await self.openai.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        return [item.embedding for item in response.data]

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single text string."""
        embeddings = await self.embed([text])
        return embeddings[0]


# Singleton
llm_service = LLMService()
