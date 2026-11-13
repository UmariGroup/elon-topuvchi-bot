"""Claude bilan ishlash qatlami.

Barcha chaqiruvlar bitta majburiy tool orqali JSON qaytaradi. Tizim prompti va tool
ta'rifi `cache_control` bilan keshlanadi (prompt caching).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolChoiceToolParam, ToolParam

from elon.llm.pricing import TokenUsage

ToolSchema = dict[str, Any]
ChatMessage = dict[str, str]


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    usage: TokenUsage


class LLMClient(Protocol):
    async def call_tool(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        tool: ToolSchema,
        max_tokens: int,
    ) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self, api_key: str, *, timeout: float = 60.0, max_retries: int = 2) -> None:
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)

    async def call_tool(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        tool: ToolSchema,
        max_tokens: int,
    ) -> LLMResult:
        # Kesh tartibi: tools -> system -> messages. System blokidagi belgi
        # tool ta'rifini ham qamrab oladi.
        system_blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        tool_choice: ToolChoiceToolParam = {"type": "tool", "name": tool["name"]}
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=[cast(ToolParam, tool)],
            tool_choice=tool_choice,
            messages=cast(list[MessageParam], messages),
        )
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
        )
        for block in response.content:
            if block.type == "tool_use" and isinstance(block.input, dict):
                return LLMResult(data=dict(block.input), usage=usage)
        raise LLMError(f"model tool chaqirmadi (stop_reason={response.stop_reason})")
