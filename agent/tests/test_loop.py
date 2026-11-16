from types import SimpleNamespace
from typing import Any, cast

import anthropic
import pytest

from sentinel_agent.loop import AgentError, AgentRefusal, Tool, Usage, run_agent


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def tool_use(id_: str, name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=tool_input)


def usage(
    input_tokens: int = 10,
    output_tokens: int = 5,
    created: int | None = None,
    read: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=created,
        cache_read_input_tokens=read,
    )


def reply(
    stop_reason: str, *blocks: SimpleNamespace, tokens: SimpleNamespace | None = None
) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks), usage=tokens or usage())


class FakeClient:
    """Returns scripted responses and records every request."""

    def __init__(self, *responses: SimpleNamespace) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)

    def as_client(self) -> anthropic.Anthropic:
        return cast(anthropic.Anthropic, self)


def echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="Echo the input",
        input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
        handler=lambda args: f"echo:{args['msg']}",
    )


def test_returns_text_when_no_tools_needed() -> None:
    fake = FakeClient(reply("end_turn", text("all good")))
    result = run_agent(fake.as_client(), "hi")
    assert result.text == "all good"
    assert result.turns == 1


def test_request_uses_adaptive_thinking_and_effort() -> None:
    fake = FakeClient(reply("end_turn", text("ok")))
    run_agent(fake.as_client(), "hi", system="be brief", effort="low")
    call = fake.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "low"}
    assert call["system"][0]["text"] == "be brief"
    assert "tools" not in call


def test_runs_tool_and_returns_all_results_in_one_message() -> None:
    fake = FakeClient(
        reply(
            "tool_use",
            tool_use("t1", "echo", {"msg": "a"}),
            tool_use("t2", "echo", {"msg": "b"}),
        ),
        reply("end_turn", text("done")),
    )
    result = run_agent(fake.as_client(), "go", tools=[echo_tool()])

    assert result.text == "done"
    assert result.turns == 2
    sent = fake.calls[1]["messages"][-1]
    assert sent["role"] == "user"
    assert [r["tool_use_id"] for r in sent["content"]] == ["t1", "t2"]
    assert [r["content"] for r in sent["content"]] == ["echo:a", "echo:b"]


def test_tool_exception_becomes_error_result() -> None:
    def boom(_: dict[str, Any]) -> str:
        raise ValueError("nope")

    failing = Tool("boom", "fails", {"type": "object"}, boom)
    fake = FakeClient(
        reply("tool_use", tool_use("t1", "boom", {})),
        reply("end_turn", text("recovered")),
    )
    run_agent(fake.as_client(), "go", tools=[failing])
    block = fake.calls[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True
    assert "ValueError: nope" in block["content"]


def test_unknown_tool_becomes_error_result() -> None:
    fake = FakeClient(
        reply("tool_use", tool_use("t1", "missing", {})),
        reply("end_turn", text("ok")),
    )
    run_agent(fake.as_client(), "go", tools=[echo_tool()])
    block = fake.calls[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True
    assert "unknown tool" in block["content"]


def test_pause_turn_resends_without_running_tools() -> None:
    fake = FakeClient(
        reply("pause_turn", text("working")),
        reply("end_turn", text("finished")),
    )
    result = run_agent(fake.as_client(), "go")
    assert result.text == "finished"
    assert result.turns == 2


def test_refusal_raises() -> None:
    fake = FakeClient(reply("refusal"))
    with pytest.raises(AgentRefusal):
        run_agent(fake.as_client(), "go")


def test_max_tokens_raises() -> None:
    fake = FakeClient(reply("max_tokens", text("cut off")))
    with pytest.raises(AgentError, match="max_tokens"):
        run_agent(fake.as_client(), "go")


def test_turn_limit_raises() -> None:
    fake = FakeClient(
        reply("tool_use", tool_use("t1", "echo", {"msg": "x"})),
        reply("tool_use", tool_use("t2", "echo", {"msg": "y"})),
    )
    with pytest.raises(AgentError, match="2 turns"):
        run_agent(fake.as_client(), "go", tools=[echo_tool()], max_turns=2)


def test_caching_marks_system_prompt_and_conversation_tail() -> None:
    fake = FakeClient(reply("end_turn", text("ok")))
    run_agent(fake.as_client(), "hi", system="stable prompt")
    call = fake.calls[0]
    assert call["system"] == [
        {"type": "text", "text": "stable prompt", "cache_control": {"type": "ephemeral"}}
    ]
    assert call["cache_control"] == {"type": "ephemeral"}


def test_caching_can_be_disabled() -> None:
    fake = FakeClient(reply("end_turn", text("ok")))
    run_agent(fake.as_client(), "hi", system="stable prompt", cache=False)
    call = fake.calls[0]
    assert call["system"] == "stable prompt"
    assert "cache_control" not in call


def test_tools_are_sent_in_a_stable_order() -> None:
    def tool(name: str) -> Tool:
        return Tool(name, "d", {"type": "object"}, lambda _: "")

    first = FakeClient(reply("end_turn", text("ok")))
    second = FakeClient(reply("end_turn", text("ok")))
    run_agent(first.as_client(), "hi", tools=[tool("b"), tool("c"), tool("a")])
    run_agent(second.as_client(), "hi", tools=[tool("c"), tool("a"), tool("b")])

    assert [t["name"] for t in first.calls[0]["tools"]] == ["a", "b", "c"]
    assert first.calls[0]["tools"] == second.calls[0]["tools"]


def test_usage_is_summed_across_turns() -> None:
    fake = FakeClient(
        reply(
            "tool_use",
            tool_use("t1", "echo", {"msg": "a"}),
            tokens=usage(input_tokens=100, output_tokens=20, created=900),
        ),
        reply("end_turn", text("done"), tokens=usage(input_tokens=30, output_tokens=40, read=900)),
    )
    result = run_agent(fake.as_client(), "go", tools=[echo_tool()])

    assert result.usage.input_tokens == 130
    assert result.usage.output_tokens == 60
    assert result.usage.cache_creation_input_tokens == 900
    assert result.usage.cache_read_input_tokens == 900
    assert result.usage.cache_hit_ratio == pytest.approx(900 / 1930)


def test_cache_hit_ratio_is_zero_with_no_tokens() -> None:
    assert Usage().cache_hit_ratio == 0.0
