"""Result models shared by the downloader, the statistics and the CLI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestResult:
    """One successfully completed download.

    ``duration`` is wall-clock time in seconds from the moment the request was
    started until the last byte of the body arrived. On a fresh connection it
    therefore includes DNS resolution, TCP connect, the TLS handshake, server
    processing time and the transfer itself: everything a client has to wait
    for to obtain the resource.
    """

    index: int
    duration: float
    downloaded_bytes: int
    time_to_first_byte: float
    status: int
    content_length: int | None
    final_url: str

    @property
    def bytes_per_second(self) -> float:
        """Throughput of this single request."""
        return self.downloaded_bytes / self.duration if self.duration > 0 else 0.0

    @property
    def content_length_mismatch(self) -> bool:
        """True when the server announced a size that differs from what arrived."""
        return self.content_length is not None and self.content_length != self.downloaded_bytes


@dataclass(frozen=True, slots=True)
class RequestFailure:
    """A request that did not complete (network error, timeout, HTTP error)."""

    index: int
    error: str
    duration: float


@dataclass(frozen=True, slots=True)
class Summary:
    """Aggregate figures over the successful requests of one run.

    ``bytes_per_second`` is ``total_bytes / total_time``, i.e. the effective
    throughput of the whole run, not the mean of per-request speeds.
    """

    requests_attempted: int
    requests_succeeded: int
    average_time: float
    total_bytes: int
    total_time: float
    bytes_per_second: float
    min_time: float
    median_time: float
    max_time: float
    min_bytes_per_second: float
    max_bytes_per_second: float
