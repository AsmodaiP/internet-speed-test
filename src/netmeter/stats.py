"""Pure statistics over measurement results. No I/O, no CLI."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from netmeter.models import RequestFailure, RequestResult, Summary

BYTES_PER_MEGABYTE = 1_000_000
BITS_PER_MEGABIT = 1_000_000


def bytes_to_megabytes(count: int | float) -> float:
    """Decimal megabytes: 1 MB = 1,000,000 bytes."""
    return count / BYTES_PER_MEGABYTE


def bps_to_mbps(bytes_per_second: float) -> float:
    """Bytes per second to decimal megabytes per second."""
    return bytes_per_second / BYTES_PER_MEGABYTE


def bps_to_mbitps(bytes_per_second: float) -> float:
    """Bytes per second to decimal megabits per second (what ISPs advertise)."""
    return bytes_per_second * 8 / BITS_PER_MEGABIT


def summarize(outcomes: Sequence[RequestResult | RequestFailure]) -> Summary:
    """Aggregate a run. Failed requests are counted but excluded from the figures.

    Raises ``ValueError`` when there is not a single successful request, because
    there is nothing meaningful to average.
    """
    successes = [o for o in outcomes if isinstance(o, RequestResult)]
    if not successes:
        raise ValueError("no successful requests to summarize")

    durations = [r.duration for r in successes]
    speeds = [r.bytes_per_second for r in successes]
    total_time = sum(durations)
    total_bytes = sum(r.downloaded_bytes for r in successes)

    return Summary(
        requests_attempted=len(outcomes),
        requests_succeeded=len(successes),
        average_time=total_time / len(successes),
        total_bytes=total_bytes,
        total_time=total_time,
        bytes_per_second=total_bytes / total_time if total_time > 0 else 0.0,
        min_time=min(durations),
        median_time=statistics.median(durations),
        max_time=max(durations),
        min_bytes_per_second=min(speeds),
        max_bytes_per_second=max(speeds),
    )
