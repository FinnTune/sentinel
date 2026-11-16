from types import SimpleNamespace
from typing import Any, cast

import anthropic

from sentinel_agent.models import TriageJob
from sentinel_agent.prompts import TRIAGE_SYSTEM_PROMPT
from sentinel_agent.triage import triage


class FakeClient:
    def __init__(self, *responses: SimpleNamespace) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


class FakeGitHub:
    def __init__(self) -> None:
        self.comments: list[tuple[str, int, str]] = []

    def list_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        return [{"id": 11, "name": "go", "conclusion": "failure", "steps": []}]

    def get_job_log(self, repo: str, job_id: int) -> str:
        return "error: boom\n"

    def post_issue_comment(self, repo: str, number: int, body: str) -> str:
        self.comments.append((repo, number, body))
        return "https://github.com/o/r/pull/5#c1"


def usage(read: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=None,
        cache_read_input_tokens=read,
    )


def test_triage_runs_the_investigation_end_to_end() -> None:
    comment = SimpleNamespace(
        type="tool_use", id="t2", name="post_pr_comment", input={"body": "Root cause: boom"}
    )
    listing = SimpleNamespace(type="tool_use", id="t1", name="list_failed_jobs", input={})
    client = FakeClient(
        SimpleNamespace(stop_reason="tool_use", content=[listing], usage=usage()),
        SimpleNamespace(stop_reason="tool_use", content=[comment], usage=usage(read=800)),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
            usage=usage(read=900),
        ),
    )
    github = FakeGitHub()
    job = TriageJob(repo="o/r", run_id=42, pr_numbers=(5,))

    result = triage(cast(anthropic.Anthropic, client), job, github, scanner=lambda log: log)

    assert result.text == "done"
    assert github.comments[0][:2] == ("o/r", 5)
    assert result.usage.cache_read_input_tokens == 1700

    first = client.calls[0]
    # Frozen prompt in the cached system block; per-run details only in the user turn.
    assert first["system"][0]["text"] == TRIAGE_SYSTEM_PROMPT
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "run_id: 42" in first["messages"][0]["content"]
    assert [t["name"] for t in first["tools"]] == [
        "get_job_log_errors",
        "list_failed_jobs",
        "post_pr_comment",
    ]
    # Identical prefix on every turn is what makes caching work.
    assert all(
        c["system"] == first["system"] and c["tools"] == first["tools"] for c in client.calls
    )
