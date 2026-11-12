"""Minimal GitHub REST client for the endpoints Sentinel needs."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

API_BASE = "https://api.github.com"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_LOG_BYTES = 20 * 1024 * 1024


class GitHubError(Exception):
    """A GitHub request failed or returned something unexpected."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]  # keys lowercased
    body: bytes


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        max_bytes: int | None = None,
    ) -> Response: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class UrllibTransport:
    """Stdlib transport that reports redirects instead of following them."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        max_bytes: int | None = None,
    ) -> Response:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=30) as resp:
                data = resp.read(max_bytes) if max_bytes else resp.read()
                return Response(resp.status, _lower(resp.headers.items()), data)
        except urllib.error.HTTPError as err:
            # 3xx and 4xx/5xx arrive here; let the client decide what they mean.
            return Response(err.code, _lower(err.headers.items()), err.read())
        except urllib.error.URLError as err:
            raise GitHubError(f"request to {url} failed: {err.reason}") from err


def _lower(items: Any) -> dict[str, str]:
    return {k.lower(): v for k, v in items}


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        api_base: str = API_BASE,
        transport: Transport | None = None,
    ) -> None:
        if not token:
            raise ValueError("a GitHub token is required")
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._transport = transport or UrllibTransport()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sentinel-agent",
        }

    def list_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Jobs of a workflow run (first 100)."""
        _check_repo(repo)
        url = f"{self._api_base}/repos/{repo}/actions/runs/{int(run_id)}/jobs?per_page=100"
        data = self._json("GET", url)
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise GitHubError("unexpected response: no 'jobs' list")
        return jobs

    def get_job_log(self, repo: str, job_id: int) -> str:
        """Plain-text log of one job, capped at MAX_LOG_BYTES (keeps the start)."""
        _check_repo(repo)
        url = f"{self._api_base}/repos/{repo}/actions/jobs/{int(job_id)}/logs"
        resp = self._transport.request("GET", url, self._headers())
        if resp.status in REDIRECT_CODES:
            location = resp.headers.get("location")
            if not location:
                raise GitHubError("log redirect had no Location header")
            # The redirect target is pre-signed: never send our token to it.
            resp = self._transport.request(
                "GET", location, {"User-Agent": "sentinel-agent"}, max_bytes=MAX_LOG_BYTES
            )
        if resp.status != 200:
            raise GitHubError(f"fetching job log failed: HTTP {resp.status}")
        return resp.body.decode("utf-8", errors="replace")

    def post_issue_comment(self, repo: str, number: int, body: str) -> str:
        """Comment on an issue or pull request; returns the comment URL."""
        _check_repo(repo)
        url = f"{self._api_base}/repos/{repo}/issues/{int(number)}/comments"
        data = self._json("POST", url, {"body": body})
        return str(data.get("html_url", ""))

    def _json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = self._headers()
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        resp = self._transport.request(method, url, headers, body)
        if resp.status not in (200, 201):
            raise GitHubError(f"{method} {url} failed: HTTP {resp.status}")
        try:
            data = json.loads(resp.body)
        except json.JSONDecodeError as exc:
            raise GitHubError("response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise GitHubError("unexpected response shape")
        return data


def _check_repo(repo: str) -> None:
    if not REPO_PATTERN.match(repo) or any(part in (".", "..") for part in repo.split("/")):
        raise ValueError(f"invalid repo name: {repo!r}")
