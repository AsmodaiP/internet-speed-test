#!/usr/bin/env python3
"""The task, literally, with nothing but the standard library.

Fetch a URL 10 times in a row, print how long each request took, then print
the average request time, the total downloaded volume and the speed in MB/s.

Usage:
    python examples/minimal.py https://example.com/large-image.jpg
"""

import http.client
import sys
import time
import urllib.request

REQUESTS = 10
TIMEOUT = 30  # seconds without data before giving up
CHUNK = 64 * 1024  # read the body piece by piece, never whole in memory


def download(url: str) -> tuple[float, int]:
    """Return (seconds from request start to last body byte, bytes received)."""
    # identity: count bytes as they travel on the wire, not after decompression.
    # A real User-Agent: some CDNs (e.g. Wikimedia) reject Python's default one.
    headers = {"Accept-Encoding": "identity", "User-Agent": "netmeter-minimal/0.1"}
    request = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        received = 0
        while chunk := response.read(CHUNK):
            received += len(chunk)
    return time.perf_counter() - started, received


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} URL")
    url = sys.argv[1]

    durations: list[float] = []
    total_bytes = 0
    for i in range(1, REQUESTS + 1):  # strictly one after another
        try:
            elapsed, received = download(url)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            sys.exit(f"request {i} failed: {exc}")
        durations.append(elapsed)
        total_bytes += received
        print(
            f"Request {i:2d}/{REQUESTS}: {elapsed:.3f} s, "
            f"{received / 1e6:.2f} MB, {received / elapsed / 1e6:.2f} MB/s"
        )

    total_time = sum(durations)
    print()
    print(f"Average request time: {total_time / REQUESTS:.3f} s")
    print(f"Downloaded:           {total_bytes / 1e6:.2f} MB in {total_time:.3f} s")
    print(f"Speed:                {total_bytes / total_time / 1e6:.2f} MB/s")
    print(f"                      {total_bytes * 8 / total_time / 1e6:.2f} Mbit/s")


if __name__ == "__main__":
    main()
