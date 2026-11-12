from typing import Any

import pytest

from sentinel_agent.loop import Tool
from sentinel_agent.models import TriageJob
from sentinel_agent.tools import (
    COMMENT_MARKER,
    MAX_COMMENT_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    build_triage_tools,
)

JOBS = [
    {
        "id": 11,
        "name": "go",
        "conclusion": "failure",
        "steps": [
            {"name": "Vet", "conclusion": "success"},
            {"name": "Test", "conclusion": "failure"},
        ],
    },
    {"id": 12, "name": "rust", "conclusion": "success", "steps": []},
]


class FakeGitHub:
    def __init__(self, log: str = "") -> None:
        self.log = log
        self.comments: list[tuple[str, int, str]] = []
        self.log_requests: list[tuple[str, int]] = []

    def list_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        return JOBS

    def get_job_log(self, repo: str, job_id: int) -> str:
        self.log_requests.append((repo, job_id))
        return self.log

    def post_issue_comment(self, repo: str, number: int, body: str) -> str:
        self.comments.append((repo, number, body))
        return f"https://github.com/{repo}/pull/{number}#c1"


def job(prs: tuple[int, ...] = (5,)) -> TriageJob:
    return TriageJob(repo="o/r", run_id=42, pr_numbers=prs)


def by_name(tools: list[Tool], name: str) -> Tool:
    return next(t for t in tools if t.name == name)


def test_triage_job_from_gateway_json() -> None:
    j = TriageJob.from_dict(
        {"repo": "o/r", "run_id": 9, "pr_numbers": [3, 4], "branch": "m", "extra": "ignored"}
    )
    assert (j.repo, j.run_id, j.branch, j.pr_numbers) == ("o/r", 9, "m", (3, 4))
    assert TriageJob.from_dict({"repo": "o/r", "run_id": 9, "pr_numbers": None}).pr_numbers == ()


def test_list_failed_jobs_shows_only_failures_and_steps() -> None:
    out = by_name(build_triage_tools(job(), FakeGitHub()), "list_failed_jobs").handler({})
    assert out == "job_id=11 name=go (failed steps: Test)"


def test_get_job_log_errors_returns_scanner_output() -> None:
    gh = FakeGitHub(log="a\nerror: x\n")
    tools = build_triage_tools(job(), gh, scanner=lambda log: f"SCANNED[{log.strip()}]")
    out = by_name(tools, "get_job_log_errors").handler({"job_id": 11})
    assert out == "SCANNED[a\nerror: x]"
    assert gh.log_requests == [("o/r", 11)]


def test_get_job_log_errors_falls_back_to_tail() -> None:
    gh = FakeGitHub(log="\n".join(f"line{i}" for i in range(100)))
    tools = build_triage_tools(job(), gh, scanner=lambda log: "")
    out = by_name(tools, "get_job_log_errors").handler({"job_id": 11})
    assert "No error lines found" in out
    assert "line99" in out
    assert "line10\n" not in out


def test_get_job_log_errors_clips_huge_output() -> None:
    tools = build_triage_tools(job(), FakeGitHub(log="x"), scanner=lambda log: "e" * 100_000)
    out = by_name(tools, "get_job_log_errors").handler({"job_id": 11})
    assert len(out) < MAX_TOOL_OUTPUT_CHARS + 50
    assert out.endswith("[output truncated]")


@pytest.mark.parametrize("bad", [None, "11", 11.0, True, 999])
def test_get_job_log_errors_rejects_bad_or_foreign_job_ids(bad: object) -> None:
    gh = FakeGitHub()
    tool = by_name(build_triage_tools(job(), gh), "get_job_log_errors")
    with pytest.raises(ValueError):
        tool.handler({"job_id": bad})
    assert gh.log_requests == []  # never fetched a log for a job outside this run


def test_post_pr_comment_is_bound_to_the_jobs_pr() -> None:
    gh = FakeGitHub()
    tool = by_name(build_triage_tools(job((5, 6)), gh), "post_pr_comment")
    # Extra fields the model might invent (like another repo/PR) are ignored.
    out = tool.handler({"body": "Root cause: X", "repo": "evil/repo", "number": 99})

    assert gh.comments == [("o/r", 5, f"{COMMENT_MARKER}\nRoot cause: X")]
    assert "PR #5" in out


@pytest.mark.parametrize("bad", [None, "", "   ", 5, "x" * (MAX_COMMENT_CHARS + 1)])
def test_post_pr_comment_validates_body(bad: object) -> None:
    gh = FakeGitHub()
    tool = by_name(build_triage_tools(job(), gh), "post_pr_comment")
    with pytest.raises(ValueError):
        tool.handler({"body": bad})
    assert gh.comments == []


def test_no_comment_tool_without_a_pr() -> None:
    names = [t.name for t in build_triage_tools(job(prs=()), FakeGitHub())]
    assert names == ["list_failed_jobs", "get_job_log_errors"]


def test_tools_expose_valid_api_definitions() -> None:
    for tool in build_triage_tools(job(), FakeGitHub()):
        param = tool.to_param()
        assert param["name"] == tool.name
        assert param["description"]
        assert param["input_schema"]["type"] == "object"
