import stat
from pathlib import Path

import pytest

from sentinel_agent.logscan import LogscanError, scan_log

REAL_BINARY = Path(__file__).resolve().parents[2] / "logscan" / "target" / "debug" / "logscan"


def script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "fake-logscan"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_passes_log_on_stdin_and_flags_as_args(tmp_path: Path) -> None:
    exe = script(tmp_path, 'echo "args:$*"; cat')
    out = scan_log("hello", binary=exe, before=1, after=2, max_windows=3)
    assert out == "args:--before 1 --after 2 --max 3\nhello"


def test_missing_binary_raises(tmp_path: Path) -> None:
    with pytest.raises(LogscanError, match="not found"):
        scan_log("x", binary=str(tmp_path / "nope"))


def test_nonzero_exit_raises(tmp_path: Path) -> None:
    exe = script(tmp_path, 'echo "bad flag" >&2; exit 2')
    with pytest.raises(LogscanError, match="exited 2: bad flag"):
        scan_log("x", binary=exe)


def test_binary_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_LOGSCAN_BIN", script(tmp_path, "echo from-env"))
    assert scan_log("x").strip() == "from-env"


@pytest.mark.skipif(not REAL_BINARY.exists(), reason="build logscan first: cargo build")
def test_real_binary_extracts_error_window() -> None:
    log = "compiling\n\x1b[31merror\x1b[0m: boom\nnext\n"
    out = scan_log(log, binary=str(REAL_BINARY), before=1, after=1)
    assert "--- lines 1-3 ---" in out
    assert "error: boom" in out  # colour codes stripped
