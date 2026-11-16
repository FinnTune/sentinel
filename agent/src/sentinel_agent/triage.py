"""Entry point: triage one failed CI run."""

from __future__ import annotations

import anthropic

from sentinel_agent.logscan import scan_log
from sentinel_agent.loop import DEFAULT_MODEL, AgentResult, Effort, run_agent
from sentinel_agent.models import TriageJob
from sentinel_agent.prompts import TRIAGE_SYSTEM_PROMPT, build_user_message
from sentinel_agent.tools import GitHubAPI, Scanner, build_triage_tools


def triage(
    client: anthropic.Anthropic,
    job: TriageJob,
    github: GitHubAPI,
    *,
    scanner: Scanner = scan_log,
    model: str = DEFAULT_MODEL,
    effort: Effort = "medium",
    max_turns: int = 10,
) -> AgentResult:
    """Investigate `job`, posting the diagnosis to its PR if it has one."""
    return run_agent(
        client,
        build_user_message(job),
        system=TRIAGE_SYSTEM_PROMPT,
        tools=build_triage_tools(job, github, scanner),
        model=model,
        effort=effort,
        max_turns=max_turns,
    )
