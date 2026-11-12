"""Run the Rust `logscan` binary to shrink a CI log to its error windows."""

from __future__ import annotations

import os
import subprocess

DEFAULT_BINARY = "logscan"
TIMEOUT_SECONDS = 30


class LogscanError(Exception):
    """The logscan binary is missing or failed."""


def scan_log(
    log: str,
    *,
    binary: str | None = None,
    before: int = 3,
    after: int = 5,
    max_windows: int = 20,
) -> str:
    """Return the rendered error windows of `log`; empty if it has no errors.

    The binary comes from `binary`, else $SENTINEL_LOGSCAN_BIN, else `logscan`
    on PATH.
    """
    exe = binary or os.environ.get("SENTINEL_LOGSCAN_BIN") or DEFAULT_BINARY
    cmd = [exe, "--before", str(before), "--after", str(after), "--max", str(max_windows)]
    try:
        proc = subprocess.run(
            cmd,
            input=log,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LogscanError(f"logscan binary not found: {exe}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LogscanError(f"logscan timed out after {TIMEOUT_SECONDS}s") from exc
    if proc.returncode != 0:
        raise LogscanError(f"logscan exited {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout
