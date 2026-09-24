"""Command-line interface. Formatting only; the numbers come from ``stats``."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from netmeter import __version__
from netmeter.download import DEFAULT_TIMEOUT
from netmeter.models import RequestFailure, RequestResult, Summary
from netmeter.runner import DEFAULT_REQUESTS, measure
from netmeter.stats import bps_to_mbitps, bps_to_mbps, bytes_to_megabytes, summarize

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netmeter",
        description=(
            "Measure download speed from this machine: fetch URL several times "
            "in a row and report average request time, downloaded volume and speed."
        ),
    )
    parser.add_argument("url", help="what to download, e.g. a large image (http:// or https://)")
    parser.add_argument(
        "-n",
        "--requests",
        type=_positive_int,
        default=DEFAULT_REQUESTS,
        help=f"number of sequential requests (default: {DEFAULT_REQUESTS})",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "give up on a request after this long without receiving any data "
            f"(default: {DEFAULT_TIMEOUT:g})"
        ),
    )
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help="reuse one connection for all requests instead of opening a new one each time",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="do not verify the server's TLS certificate",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON report to stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="print only the summary")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if "://" not in args.url:
        parser.error("URL must start with http:// or https://")

    # In JSON mode stdout carries only the report, so progress goes to stderr.
    progress: TextIO = sys.stderr if args.json else sys.stdout
    outcomes: list[RequestResult | RequestFailure] = []
    interrupted = False

    if not args.quiet:
        mode = "reusing one connection" if args.keep_alive else "new connection per request"
        print(f"Measuring {args.url}", file=progress)
        print(f"{args.requests} sequential requests, {mode}\n", file=progress)

    try:
        for outcome in measure(
            args.url,
            count=args.requests,
            timeout=args.timeout,
            keep_alive=args.keep_alive,
            verify_tls=not args.insecure,
        ):
            outcomes.append(outcome)
            if not args.quiet:
                print(_format_outcome(outcome, args.requests), file=progress, flush=True)
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted, summarizing what was measured so far", file=sys.stderr)

    _print_warnings(outcomes)

    summary = _try_summarize(outcomes)
    if args.json:
        print(json.dumps(_json_report(args.url, outcomes, summary), indent=2))
    elif summary is None:
        print("\nNo successful requests, nothing to summarize.", file=sys.stderr)
    else:
        if not args.quiet:
            print()
        print(_format_summary(summary))

    if interrupted:
        return EXIT_INTERRUPTED
    all_ok = summary is not None and summary.requests_succeeded == args.requests
    return EXIT_OK if all_ok else EXIT_FAILURES


# -- formatting ------------------------------------------------------------


def _format_outcome(outcome: RequestResult | RequestFailure, total: int) -> str:
    label = f"Request {outcome.index:2d}/{total}"
    if isinstance(outcome, RequestFailure):
        return f"{label}   FAILED after {outcome.duration:.3f} s: {outcome.error}"
    return (
        f"{label}   {outcome.duration:7.3f} s   "
        f"{bytes_to_megabytes(outcome.downloaded_bytes):8.2f} MB   "
        f"{bps_to_mbps(outcome.bytes_per_second):7.2f} MB/s"
    )


def _format_summary(s: Summary) -> str:
    lines = [
        "Summary",
        "─" * 40,
        f"Requests:       {s.requests_succeeded}/{s.requests_attempted} successful",
        f"Average time:   {s.average_time:.3f} s",
        f"Downloaded:     {bytes_to_megabytes(s.total_bytes):.2f} MB",
        f"Total time:     {s.total_time:.3f} s",
        f"Speed:          {bps_to_mbps(s.bytes_per_second):.2f} MB/s",
        f"                {bps_to_mbitps(s.bytes_per_second):.2f} Mbit/s",
    ]
    if s.requests_succeeded > 1:
        lines += [
            "",
            f"Request time:   min {s.min_time:.3f} s   "
            f"median {s.median_time:.3f} s   max {s.max_time:.3f} s",
            f"Request speed:  min {bps_to_mbps(s.min_bytes_per_second):.2f} MB/s   "
            f"max {bps_to_mbps(s.max_bytes_per_second):.2f} MB/s",
        ]
    return "\n".join(lines)


def _print_warnings(outcomes: Sequence[RequestResult | RequestFailure]) -> None:
    for outcome in outcomes:
        if isinstance(outcome, RequestFailure) and "TLS certificate verification" in outcome.error:
            print(
                "hint: your Python cannot find a CA bundle. Install certificates for it "
                "(on macOS: 'Install Certificates.command' in the Python folder, or "
                "'pip install certifi'), or pass --insecure to skip verification.",
                file=sys.stderr,
            )
            break
    for outcome in outcomes:
        if isinstance(outcome, RequestResult) and outcome.content_length_mismatch:
            print(
                f"warning: request {outcome.index} received {outcome.downloaded_bytes} bytes "
                f"but the server announced Content-Length {outcome.content_length}",
                file=sys.stderr,
            )


def _try_summarize(outcomes: Sequence[RequestResult | RequestFailure]) -> Summary | None:
    try:
        return summarize(outcomes)
    except ValueError:
        return None


def _json_report(
    url: str, outcomes: Sequence[RequestResult | RequestFailure], summary: Summary | None
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for outcome in outcomes:
        if isinstance(outcome, RequestFailure):
            requests.append(
                {
                    "index": outcome.index,
                    "ok": False,
                    "duration_s": outcome.duration,
                    "error": outcome.error,
                }
            )
        else:
            requests.append(
                {
                    "index": outcome.index,
                    "ok": True,
                    "duration_s": outcome.duration,
                    "time_to_first_byte_s": outcome.time_to_first_byte,
                    "downloaded_bytes": outcome.downloaded_bytes,
                    "content_length": outcome.content_length,
                    "bytes_per_second": outcome.bytes_per_second,
                    "status": outcome.status,
                    "final_url": outcome.final_url,
                }
            )

    summary_json: dict[str, Any] | None = None
    if summary is not None:
        summary_json = dataclasses.asdict(summary)
        summary_json["megabytes_per_second"] = bps_to_mbps(summary.bytes_per_second)
        summary_json["megabits_per_second"] = bps_to_mbitps(summary.bytes_per_second)

    return {"url": url, "requests": requests, "summary": summary_json}


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


if __name__ == "__main__":
    sys.exit(main())
