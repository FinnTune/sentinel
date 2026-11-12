"""Data passed between the gateway and the agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TriageJob:
    """One failed CI run to investigate. Mirrors proto/sentinel/v1/job.proto."""

    repo: str
    run_id: int
    delivery_id: str = ""
    workflow: str = ""
    branch: str = ""
    head_sha: str = ""
    run_url: str = ""
    pr_numbers: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriageJob:
        """Build a job from the gateway's JSON payload."""
        return cls(
            repo=str(data["repo"]),
            run_id=int(data["run_id"]),
            delivery_id=str(data.get("delivery_id", "")),
            workflow=str(data.get("workflow", "")),
            branch=str(data.get("branch", "")),
            head_sha=str(data.get("head_sha", "")),
            run_url=str(data.get("run_url", "")),
            pr_numbers=tuple(int(n) for n in data.get("pr_numbers") or ()),
        )
