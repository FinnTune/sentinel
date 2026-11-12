"""Agent tools for triaging one failed CI run.

Every tool is bound to a single job's repo, run and PR when it is built, so
the model can never point them at anything else, even if a log tries to
tell it to (CI logs are untrusted input).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from sentinel_agent.logscan import scan_log
from sentinel_agent.loop import Tool
from sentinel_agent.models import TriageJob

MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_COMMENT_CHARS = 60_000  # GitHub's limit is 65,536
TAIL_LINES = 40
COMMENT_MARKER = "<!-- sentinel -->"

Scanner = Callable[[str], str]


class GitHubAPI(Protocol):
    def list_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]: ...
    def get_job_log(self, repo: str, job_id: int) -> str: ...
    def post_issue_comment(self, repo: str, number: int, body: str) -> str: ...


def build_triage_tools(
    job: TriageJob,
    github: GitHubAPI,
    scanner: Scanner = scan_log,
) -> list[Tool]:
    """Tools for investigating `job`. Posting is offered only if it has a PR."""

    def list_failed_jobs(_: dict[str, Any]) -> str:
        failed = [j for j in github.list_run_jobs(job.repo, job.run_id) if _failed(j)]
        if not failed:
            return "No failed jobs found in this run."
        lines = []
        for j in failed:
            steps = [s["name"] for s in j.get("steps", []) if _failed(s)]
            suffix = f" (failed steps: {', '.join(steps)})" if steps else ""
            lines.append(f"job_id={j['id']} name={j['name']}{suffix}")
        return "\n".join(lines)

    def get_job_log_errors(args: dict[str, Any]) -> str:
        job_id = args.get("job_id")
        if isinstance(job_id, bool) or not isinstance(job_id, int):
            raise ValueError("job_id must be an integer")
        known = {j["id"] for j in github.list_run_jobs(job.repo, job.run_id)}
        if job_id not in known:
            raise ValueError(f"job {job_id} does not belong to this run")

        log = github.get_job_log(job.repo, job_id)
        windows = scanner(log)
        if windows.strip():
            return _clip(windows)
        tail = "\n".join(log.splitlines()[-TAIL_LINES:])
        return _clip(f"No error lines found. Last {TAIL_LINES} log lines:\n{tail}")

    tools = [
        Tool(
            name="list_failed_jobs",
            description="List the failed jobs (and failed steps) of the CI run being triaged.",
            input_schema={"type": "object", "properties": {}},
            handler=list_failed_jobs,
        ),
        Tool(
            name="get_job_log_errors",
            description=(
                "Get the error-relevant excerpts of one job's log, with surrounding "
                "context and line numbers. Use a job_id from list_failed_jobs."
            ),
            input_schema={
                "type": "object",
                "properties": {"job_id": {"type": "integer", "description": "GitHub job ID"}},
                "required": ["job_id"],
            },
            handler=get_job_log_errors,
        ),
    ]

    if job.pr_numbers:
        pr = job.pr_numbers[0]

        def post_pr_comment(args: dict[str, Any]) -> str:
            body = args.get("body")
            if not isinstance(body, str) or not body.strip():
                raise ValueError("body must be a non-empty string")
            if len(body) > MAX_COMMENT_CHARS:
                raise ValueError(f"body exceeds {MAX_COMMENT_CHARS} characters")
            url = github.post_issue_comment(job.repo, pr, f"{COMMENT_MARKER}\n{body}")
            return f"Posted comment on PR #{pr}: {url}"

        tools.append(
            Tool(
                name="post_pr_comment",
                description=(
                    "Post your final diagnosis as a comment on the pull request. "
                    "Call this once, at the end, in Markdown."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"body": {"type": "string", "description": "Markdown"}},
                    "required": ["body"],
                },
                handler=post_pr_comment,
            )
        )
    return tools


def _failed(item: dict[str, Any]) -> bool:
    return item.get("conclusion") == "failure"


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:MAX_TOOL_OUTPUT_CHARS] + "\n[output truncated]"
