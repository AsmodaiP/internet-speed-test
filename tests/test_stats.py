import pytest

from netmeter.models import RequestFailure, RequestResult
from netmeter.stats import bps_to_mbitps, bps_to_mbps, bytes_to_megabytes, summarize


def result(index: int, duration: float, nbytes: int) -> RequestResult:
    return RequestResult(
        index=index,
        duration=duration,
        downloaded_bytes=nbytes,
        time_to_headers=duration / 10,
        status=200,
        content_length=nbytes,
        final_url="http://example/file",
    )


def test_average_duration_and_total_bytes() -> None:
    summary = summarize([result(1, 1.0, 100), result(2, 3.0, 100)])
    assert summary.requests_attempted == 2
    assert summary.requests_succeeded == 2
    assert summary.average_time == pytest.approx(2.0)
    assert summary.total_bytes == 200
    assert summary.total_time == pytest.approx(4.0)


def test_effective_throughput_is_total_bytes_over_total_time() -> None:
    # 100 B in 1 s and 100 B in 3 s. Mean of per-request speeds would be
    # (100 + 33.3) / 2 = 66.7 B/s; the run actually moved 200 B in 4 s = 50 B/s.
    summary = summarize([result(1, 1.0, 100), result(2, 3.0, 100)])
    assert summary.bytes_per_second == pytest.approx(50.0)
    assert summary.min_bytes_per_second == pytest.approx(100 / 3)
    assert summary.max_bytes_per_second == pytest.approx(100.0)


def test_min_median_max() -> None:
    summary = summarize([result(1, 3.0, 1), result(2, 1.0, 1), result(3, 2.0, 1)])
    assert summary.min_time == 1.0
    assert summary.median_time == 2.0
    assert summary.max_time == 3.0


def test_failures_are_counted_but_excluded_from_figures() -> None:
    outcomes = [result(1, 1.0, 100), RequestFailure(index=2, error="boom", duration=5.0)]
    summary = summarize(outcomes)
    assert summary.requests_attempted == 2
    assert summary.requests_succeeded == 1
    assert summary.average_time == pytest.approx(1.0)
    assert summary.total_bytes == 100


def test_empty_run_raises() -> None:
    with pytest.raises(ValueError):
        summarize([])
    with pytest.raises(ValueError):
        summarize([RequestFailure(index=1, error="boom", duration=0.1)])


def test_zero_duration_does_not_divide_by_zero() -> None:
    summary = summarize([result(1, 0.0, 100)])
    assert summary.bytes_per_second == 0.0


def test_unit_conversions_are_decimal() -> None:
    assert bytes_to_megabytes(25_000_000) == pytest.approx(25.0)
    assert bps_to_mbps(20_000_000) == pytest.approx(20.0)
    assert bps_to_mbitps(20_000_000) == pytest.approx(160.0)


def test_per_request_speed_property() -> None:
    assert result(1, 2.0, 500).bytes_per_second == 250.0
    assert result(1, 0.0, 500).bytes_per_second == 0.0
