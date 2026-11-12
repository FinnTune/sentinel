import json

import pytest

from sentinel_agent.github import GitHubClient, GitHubError, Response


class FakeTransport:
    """Replays scripted responses and records requests."""

    def __init__(self, *responses: Response) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        max_bytes: int | None = None,
    ) -> Response:
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "body": body, "max": max_bytes}
        )
        return self._responses.pop(0)


def ok(payload: object, status: int = 200) -> Response:
    return Response(status, {}, json.dumps(payload).encode())


def test_requires_token() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubClient("")


def test_list_run_jobs() -> None:
    transport = FakeTransport(ok({"jobs": [{"id": 1, "name": "go"}]}))
    jobs = GitHubClient("tok", transport=transport).list_run_jobs("o/r", 42)

    assert jobs == [{"id": 1, "name": "go"}]
    req = transport.requests[0]
    assert str(req["url"]).endswith("/repos/o/r/actions/runs/42/jobs?per_page=100")
    headers = req["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer tok"


def test_list_run_jobs_rejects_bad_shape() -> None:
    client = GitHubClient("tok", transport=FakeTransport(ok({"nope": []})))
    with pytest.raises(GitHubError, match="jobs"):
        client.list_run_jobs("o/r", 1)


@pytest.mark.parametrize("repo", ["", "noslash", "a/b/c", "o/r?x=1", "o/../r x", "../etc"])
def test_rejects_malformed_repo(repo: str) -> None:
    client = GitHubClient("tok", transport=FakeTransport())
    with pytest.raises(ValueError, match="invalid repo"):
        client.list_run_jobs(repo, 1)


def test_job_log_follows_redirect_without_token() -> None:
    transport = FakeTransport(
        Response(302, {"location": "https://blob.example/log?sig=abc"}, b""),
        Response(200, {}, b"line1\nerror: boom\n"),
    )
    log = GitHubClient("tok", transport=transport).get_job_log("o/r", 7)

    assert log == "line1\nerror: boom\n"
    first, second = transport.requests
    assert "Authorization" in first["headers"]  # type: ignore[operator]
    assert second["url"] == "https://blob.example/log?sig=abc"
    assert "Authorization" not in second["headers"]  # type: ignore[operator]
    assert second["max"] is not None


def test_job_log_redirect_without_location_fails() -> None:
    client = GitHubClient("tok", transport=FakeTransport(Response(302, {}, b"")))
    with pytest.raises(GitHubError, match="Location"):
        client.get_job_log("o/r", 7)


def test_job_log_http_error() -> None:
    client = GitHubClient("tok", transport=FakeTransport(Response(404, {}, b"")))
    with pytest.raises(GitHubError, match="404"):
        client.get_job_log("o/r", 7)


def test_job_log_tolerates_invalid_utf8() -> None:
    client = GitHubClient("tok", transport=FakeTransport(Response(200, {}, b"ok \xff bad")))
    assert "bad" in client.get_job_log("o/r", 7)


def test_post_issue_comment() -> None:
    transport = FakeTransport(ok({"html_url": "https://github.com/o/r/pull/5#c1"}, 201))
    url = GitHubClient("tok", transport=transport).post_issue_comment("o/r", 5, "hello")

    assert url == "https://github.com/o/r/pull/5#c1"
    req = transport.requests[0]
    assert req["method"] == "POST"
    assert str(req["url"]).endswith("/repos/o/r/issues/5/comments")
    assert json.loads(req["body"]) == {"body": "hello"}  # type: ignore[arg-type]


def test_post_issue_comment_failure() -> None:
    client = GitHubClient("tok", transport=FakeTransport(Response(403, {}, b"{}")))
    with pytest.raises(GitHubError, match="403"):
        client.post_issue_comment("o/r", 5, "x")
