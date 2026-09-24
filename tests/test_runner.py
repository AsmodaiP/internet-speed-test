from itertools import pairwise

from netmeter.models import RequestFailure, RequestResult
from netmeter.runner import run


def test_runs_exactly_n_requests(server) -> None:
    outcomes = run(server.url("/file?size=10"), count=4)
    assert [o.index for o in outcomes] == [1, 2, 3, 4]
    assert all(isinstance(o, RequestResult) for o in outcomes)
    assert len(server.records) == 4


def test_requests_do_not_overlap(server) -> None:
    # The server sleeps DELAY before answering, so if requests are sequential
    # each one can only start after the previous one has slept and replied.
    # Concurrent requests would all start within a few milliseconds.
    delay = 0.05
    run(server.url(f"/file?size=10&delay={delay}"), count=5)
    starts = sorted(rec.started for rec in server.records)
    assert len(starts) == 5
    for earlier, later in pairwise(starts):
        assert later - earlier >= delay, "next request began before the previous one finished"


def test_first_failure_aborts_the_run(server) -> None:
    outcomes = run(server.url("/status/404"), count=5)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], RequestFailure)
    assert "HTTP 404" in outcomes[0].error


def test_later_failure_is_recorded_and_run_continues(server) -> None:
    outcomes = run(server.url("/flaky?fail_on=2"), count=4)
    kinds = [type(o).__name__ for o in outcomes]
    assert kinds == ["RequestResult", "RequestFailure", "RequestResult", "RequestResult"]
    assert outcomes[1].index == 2


def test_timeout_failure_message(server) -> None:
    outcomes = run(server.url("/file?delay=1"), count=1, timeout=0.1)
    assert isinstance(outcomes[0], RequestFailure)
    assert "timed out" in outcomes[0].error
