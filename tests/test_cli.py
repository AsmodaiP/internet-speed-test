import json

import pytest

from netmeter.cli import main


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


def test_content_length_mismatch_warning(server, capsys) -> None:
    main([server.url("/truncated"), "-n", "1"])
    assert "warning: request 1 received 400 bytes" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["example.com/file"], ["http://x/", "-n", "0"], ["http://x/", "--timeout", "-1"]],
)
def test_invalid_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
