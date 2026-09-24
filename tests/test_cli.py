import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from netmeter.cli import EXIT_INTERRUPTED, main
from netmeter.models import RequestResult


def test_help_and_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "sequential requests" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_human_output_and_exit_code(server, capsys) -> None:
    code = main([server.url("/file?size=2000000"), "-n", "3"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Measuring http://" in out
    assert all(f"Request  {i}/3" in out for i in (1, 2, 3))
    assert "Requests:       3/3 successful" in out
    assert "Downloaded:     6.00 MB" in out
    assert "MB/s" in out and "Mbit/s" in out


def test_quiet_prints_only_summary(server, capsys) -> None:
    main([server.url("/file"), "-n", "2", "--quiet"])
    out = capsys.readouterr().out
    assert "Measuring" not in out
    assert "Request  1/2" not in out
    assert out.startswith("Summary")


def test_json_report_goes_to_stdout_progress_to_stderr(server, capsys) -> None:
    code = main([server.url("/file?size=1000"), "-n", "2", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Request  1/2" in captured.err
    report = json.loads(captured.out)  # stdout must be pure JSON
    assert report["url"] == server.url("/file?size=1000")
    assert [r["ok"] for r in report["requests"]] == [True, True]
    assert report["summary"]["total_bytes"] == 2000
    assert report["summary"]["requests_succeeded"] == 2
    assert report["summary"]["megabits_per_second"] == pytest.approx(
        report["summary"]["bytes_per_second"] * 8 / 1e6
    )


def test_partial_failure_exit_code_and_json(server, capsys) -> None:
    code = main([server.url("/flaky?fail_on=2"), "-n", "3", "--json", "--quiet"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert [r["ok"] for r in report["requests"]] == [True, False, True]
    assert "HTTP 500" in report["requests"][1]["error"]
    assert report["summary"]["requests_succeeded"] == 2


def test_total_failure(server, capsys) -> None:
    code = main([server.url("/status/500"), "-n", "3"])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAILED" in captured.out
    assert "No successful requests" in captured.err


def test_truncated_body_is_reported_as_failure(server, capsys) -> None:
    code = main([server.url("/truncated"), "-n", "1"])
    assert code == 1
    assert "FAILED" in capsys.readouterr().out


def test_json_report_with_no_successes_has_null_summary(server, capsys) -> None:
    code = main([server.url("/status/500"), "-n", "3", "--json", "--quiet"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["summary"] is None
    assert [r["ok"] for r in report["requests"]] == [False]  # first failure aborts


def test_keep_alive_flag(server, capsys) -> None:
    assert main([server.url("/file"), "-n", "2", "--keep-alive"]) == 0
    assert "reusing one connection" in capsys.readouterr().out
    assert len({r.client_port for r in server.records}) == 1


def test_ctrl_c_summarizes_partial_run_and_exits_130(monkeypatch, capsys) -> None:
    def fake_measure(url, **kwargs):
        yield RequestResult(1, 0.5, 1000, 0.1, 200, 1000, url)
        raise KeyboardInterrupt

    monkeypatch.setattr("netmeter.cli.measure", fake_measure)
    code = main(["http://example.invalid/file", "-n", "5"])
    captured = capsys.readouterr()
    assert code == EXIT_INTERRUPTED == 130
    assert "Interrupted" in captured.err
    assert "Requests:       1/1 successful" in captured.out


REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "-m", "netmeter", "--version"],
        [sys.executable, str(REPO / "src" / "netmeter" / "cli.py"), "--version"],
    ],
    ids=["python -m netmeter", "python src/netmeter/cli.py"],
)
def test_entry_points_without_installing(command: list[str]) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(REPO / "src")
    proc = subprocess.run(command, capture_output=True, text=True, check=True, env=env)
    assert proc.stdout.strip() == "netmeter 0.1.0"


@pytest.mark.parametrize(
    "argv",
    [
        ["example.com/file"],
        ["ftp://example.com/file"],
        ["http://x/", "-n", "0"],
        ["http://x/", "--timeout", "-1"],
        ["http://x/", "--timeout", "nan"],
    ],
)
def test_invalid_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
