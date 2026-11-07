"""Core agent loop: call Claude, run requested tools, feed results back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from anthropic.types import MessageParam, ToolParam

DEFAULT_MODEL = "claude-opus-5-5"
Effort = Literal["low", "medium", "high", "xhigh", "max"]
ToolHandler = Callable[[dict[str, Any]], str]


class AgentError(Exception):
    """The loop could not produce a final answer."""


class AgentRefusal(AgentError):
    """Claude declined the request (stop_reason == "refusal")."""


@dataclass(frozen=True)
class Tool:
    """A client-side tool: its API definition plus the function that runs it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def to_param(self) -> ToolParam:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class AgentResult:
    text: str
    turns: int
    messages: list[MessageParam] = field(default_factory=list)


def run_agent(
    client: anthropic.Anthropic,
    user_input: str,
    *,
    system: str | None = None,
    tools: list[Tool] | None = None,
    model: str = DEFAULT_MODEL,
    effort: Effort = "medium",
    max_tokens: int = 16000,
    max_turns: int = 10,
) -> AgentResult:
    """Run the tool-use loop until Claude finishes or a limit is hit."""
    tool_map = {t.name: t for t in tools or []}
    tool_params = [t.to_param() for t in tools or []]
    messages: list[MessageParam] = [{"role": "user", "content": user_input}]

    for turn in range(1, max_turns + 1):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        if system:
            kwargs["system"] = system
        if tool_params:
            kwargs["tools"] = tool_params

        response = client.messages.create(**kwargs)
        stop = response.stop_reason

        if stop == "refusal":
            raise AgentRefusal("Claude declined the request")
        if stop == "max_tokens":
            raise AgentError("response truncated at max_tokens")

        # Keep the assistant turn verbatim, including thinking blocks.
        messages.append({"role": "assistant", "content": response.content})

        if stop == "pause_turn":
            continue
        if stop != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return AgentResult(text=text, turns=turn, messages=messages)

        # All results for a turn go back together in a single user message.
        results = [
            _run_tool(tool_map, block.name, block.id, block.input)
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})

    raise AgentError(f"no final answer after {max_turns} turns")


def _run_tool(tool_map: dict[str, Tool], name: str, tool_use_id: str, tool_input: Any) -> Any:
    tool = tool_map.get(name)
    if tool is None:
        return _result(tool_use_id, f"unknown tool: {name}", is_error=True)
    try:
        return _result(tool_use_id, tool.handler(tool_input))
    except Exception as exc:  # tool failures are reported to the model, not raised
        return _result(tool_use_id, f"{type(exc).__name__}: {exc}", is_error=True)


def _result(tool_use_id: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        result["is_error"] = True
    return result
