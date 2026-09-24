"""Run measurements strictly one after another."""

from __future__ import annotations

from collections.abc import Iterator
from time import perf_counter

from netmeter.download import DEFAULT_TIMEOUT, Downloader, DownloadError
from netmeter.models import RequestFailure, RequestResult

DEFAULT_REQUESTS = 10


def measure(
    url: str,
    *,
    count: int = DEFAULT_REQUESTS,
    timeout: float = DEFAULT_TIMEOUT,
    keep_alive: bool = False,
    verify_tls: bool = True,
) -> Iterator[RequestResult | RequestFailure]:
    """Yield one outcome per request, sequentially.

    The next request starts only after the previous one has been fully read
    (or has failed); this is a plain loop, nothing runs concurrently.

    If the very first request fails the run stops: that almost always means a
    wrong URL rather than a transient problem, and repeating it nine more times
    would only waste time. A failure later in the run is recorded and the run
    continues, so one hiccup does not throw away the other measurements.
    """
    with Downloader(timeout=timeout, keep_alive=keep_alive, verify_tls=verify_tls) as downloader:
        for index in range(1, count + 1):
            started = perf_counter()
            try:
                outcome: RequestResult | RequestFailure = downloader.download(url, index=index)
            except DownloadError as exc:
                outcome = RequestFailure(
                    index=index, error=str(exc), duration=perf_counter() - started
                )
            yield outcome
            if index == 1 and isinstance(outcome, RequestFailure):
                return


def run(
    url: str,
    *,
    count: int = DEFAULT_REQUESTS,
    timeout: float = DEFAULT_TIMEOUT,
    keep_alive: bool = False,
    verify_tls: bool = True,
) -> list[RequestResult | RequestFailure]:
    """Run all requests and return their outcomes."""
    return list(
        measure(url, count=count, timeout=timeout, keep_alive=keep_alive, verify_tls=verify_tls)
    )
