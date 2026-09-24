# netmeter

A small internet speed meter: download a URL several times in a row from your
machine and report the average request time, the downloaded volume and the
speed in MB/s.

Standard library only, Python 3.10+. No third-party runtime dependencies.

[![CI](https://github.com/AsmodaiP/internet-speed-test/actions/workflows/ci.yml/badge.svg)](https://github.com/AsmodaiP/internet-speed-test/actions/workflows/ci.yml)

## Task

> Написать скрипт-замерятель скорости интернета со своего компьютера.
> Он должен принимать адрес, куда стучаться (какая-нибудь тяжелая картинка),
> запускать последовательно 10 запросов к этому адресу, дожидаться ответа,
> вычислять среднее время запроса, объем скачанных данных и печатать в консоли
> скорость мб/с.

The repository has two layers:

- [`examples/minimal.py`](examples/minimal.py) is the task, literally: one file,
  no dependencies, no options, about 60 lines. Read this first.
- [`src/netmeter/`](src/netmeter/) is the same measurement packaged as a proper
  CLI tool with options, error handling, JSON output and tests.

Both measure the same thing the same way by default: 10 sequential GET
requests, a new connection for each, the same arithmetic. The differences are
in what happens when things go wrong: the minimal script stops at the first
error, the CLI has the failure policy described under *Error handling*.

## Quick start

```bash
git clone https://github.com/AsmodaiP/internet-speed-test.git
cd internet-speed-test
```

Minimal script, nothing to install:

```bash
python3 examples/minimal.py "https://speed.cloudflare.com/__down?bytes=25000000"
```

Full CLI, still nothing to install:

```bash
PYTHONPATH=src python3 -m netmeter "https://speed.cloudflare.com/__down?bytes=25000000"
```

Or install it (with [uv](https://docs.astral.sh/uv/) or plain pip) to get the
`netmeter` command:

```bash
uv venv && uv pip install -e .        # or: python3 -m venv .venv && .venv/bin/pip install -e .
uv run netmeter "https://speed.cloudflare.com/__down?bytes=25000000"
```

Any `http://` or `https://` URL that returns a sizeable body works. Two that
are known to be fine with repeated downloads:

- `https://speed.cloudflare.com/__down?bytes=25000000` (25 MB of zeros; change the number for any size)
- `https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg` (14.7 MB JPEG; Wikimedia rate-limits after a few dozen downloads)

> **macOS note.** If the first request fails with
> `CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate`, your
> Python has no CA bundle. That is the python.org installer's default; run
> `Install Certificates.command` from its folder once, or use a Homebrew
> Python. The `netmeter` CLI also accepts `--insecure` and picks up `certifi`
> if it is installed; the minimal script deliberately has neither.

## Example output

```
$ netmeter https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg
Measuring https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg
10 sequential requests, new connection per request

Request  1/10     4.057 s      14.68 MB      3.62 MB/s
Request  2/10     4.396 s      14.68 MB      3.34 MB/s
Request  3/10     4.323 s      14.68 MB      3.40 MB/s
Request  4/10     3.822 s      14.68 MB      3.84 MB/s
Request  5/10     3.592 s      14.68 MB      4.09 MB/s
Request  6/10     4.348 s      14.68 MB      3.38 MB/s
Request  7/10     3.400 s      14.68 MB      4.32 MB/s
Request  8/10     3.706 s      14.68 MB      3.96 MB/s
Request  9/10     3.601 s      14.68 MB      4.08 MB/s
Request 10/10     3.896 s      14.68 MB      3.77 MB/s

Summary
────────────────────────────────────────
Requests:       10/10 successful
Average time:   3.914 s
Downloaded:     146.79 MB
Total time:     39.142 s
Speed:          3.75 MB/s
                30.00 Mbit/s

Request time:   min 3.400 s   median 3.859 s   max 4.396 s
Request speed:  min 3.34 MB/s   max 4.32 MB/s
```

The minimal script prints the same figures in a plainer form:

```
$ python3 examples/minimal.py "https://speed.cloudflare.com/__down?bytes=25000000"
Request  1/10: 7.343 s, 25.00 MB, 3.40 MB/s
Request  2/10: 6.386 s, 25.00 MB, 3.92 MB/s
...
Request 10/10: 6.141 s, 25.00 MB, 4.07 MB/s

Average request time: 6.896 s
Downloaded:           250.00 MB in 68.956 s
Speed:                3.63 MB/s
                      29.00 Mbit/s
```

## How it works

1. Open a connection to the host and send `GET url`.
2. Read the response body in 64 KiB chunks until the server has sent everything,
   counting the bytes as they arrive. Nothing is written to disk or kept in
   memory.
3. Stop the clock. The request time is the wall-clock time from step 1 to the
   end of step 2, measured with `time.perf_counter()`.
4. Close the connection and go back to step 1, ten times in total. The next
   request starts only after the previous one has fully finished.
5. Print the per-request figures and the summary.

The request time therefore includes everything a client has to wait for to get
the resource: DNS lookup, TCP connect, TLS handshake, server processing and the
transfer itself. That is what "how long does it take to download this" means
from the application's point of view. The time until the response headers
arrived is recorded separately (`time_to_headers_s` in the JSON output) if you
want to separate latency from transfer.

## How speed is calculated

```
average_time     = sum(request_times) / successful_requests
total_bytes      = sum(bytes_received)
total_time       = sum(request_times)
bytes_per_second = total_bytes / total_time
MB/s             = bytes_per_second / 1_000_000
Mbit/s           = bytes_per_second * 8 / 1_000_000
```

The headline speed is `total_bytes / total_time`, **not** the mean of the ten
per-request speeds. The mean of speeds over-weights fast requests: 100 bytes in
1 s and 100 bytes in 3 s average to 66.7 B/s, but the run actually moved 200
bytes in 4 s, which is 50 B/s. Since only the whole run is observable, the
aggregate is the honest number. Per-request speeds are still shown as min/max
so you can see the spread.

Units are decimal: 1 MB = 1,000,000 bytes, 1 Mbit = 1,000,000 bits. The task
asks for MB/s, and Mbit/s is printed alongside because that is what internet
plans are sold in. Divide MB/s by 1.048576 if you want MiB/s.

## CLI options

```
netmeter URL [-n N] [--timeout SECONDS] [--keep-alive] [--insecure] [--json] [-q]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `URL` | | What to download. `http://` or `https://`. Redirects are followed. |
| `-n`, `--requests N` | 10 | Number of sequential requests. |
| `--timeout SECONDS` | 30 | Give up on a request after this long *without receiving any data*. It is an inactivity timeout, not a total limit, so a slow but steady download of a big file is not cut off. |
| `--keep-alive` | off | Reuse one connection for all requests. See below. |
| `--insecure` | off | Skip TLS certificate verification. |
| `--json` | off | Print a machine-readable report to stdout. Progress lines go to stderr so `netmeter --json URL > report.json` works. |
| `-q`, `--quiet` | off | Print only the summary. |

Exit code is 0 when every request succeeded, 1 when any failed, 2 for invalid
arguments (bad URL, `-n 0`, negative timeout), 130 on Ctrl-C (a summary of the
requests completed so far is still printed).

`python -m netmeter` behaves the same as `netmeter`.

## Error handling

- HTTP 4xx and 5xx are failures. A speed measured on an error page is not a
  speed measurement.
- Network errors (DNS, refused connection, TLS, timeout, connection dropped
  mid-body) are reported in plain words, e.g.
  `FAILED after 0.047 s: HTTP 404 Not Found` or
  `timed out after 30 s without receiving data`. Failures are printed even
  with `--quiet`.
- A body shorter than the announced `Content-Length` is a failure
  (`server closed the connection after 400 of 1000 bytes`), not a fast
  success. The bytes that did arrive are not counted towards the speed.
- If the **first** request fails the run stops immediately: that almost always
  means a wrong URL, and repeating it nine more times just wastes time.
  A failure **later** in the run is recorded, the run continues, and the summary
  says `9/10 successful` and averages over the nine. Exit code is 1 either way.
- There are no automatic retries of a measurement. A retry would hide exactly
  the thing a speed meter should show. The one exception is in `--keep-alive`
  mode: if the server silently closed an idle connection, the request is sent
  again on a new one, because nothing had been transferred yet. That is how
  every pooled HTTP client behaves.
- TLS: if you see `TLS certificate verification failed: unable to get local
  issuer certificate`, your Python has no CA bundle. This is common with the
  python.org installer on macOS (run `Install Certificates.command` from the
  Python folder, or `pip install certifi`, which netmeter picks up
  automatically). `--insecure` skips verification if you just want the number.
  A different message (`self-signed certificate`, `hostname mismatch`) means
  the server's certificate is the problem, not your Python.
- Some CDNs reject Python's default `User-Agent` (Wikimedia answers 403), and
  most rate-limit after a few dozen downloads of the same file (Wikimedia
  answers 429). netmeter sends its own descriptive User-Agent; if you get
  rate-limited, wait a bit or point it at another file.

## Fresh connection vs keep-alive

The task does not say whether the ten requests should share a connection. It
matters: with a shared connection only the first request pays for DNS, TCP and
the TLS handshake, so the other nine look faster and the average mixes two
different things.

- **Default: new connection per request.** Every request is an independent,
  complete download and the ten numbers are comparable with each other. This
  is what "run 10 requests" most literally means.
- **`--keep-alive`:** one connection is reused, the way a browser or a pooled
  HTTP client would. Requests 2..10 then measure transfer speed with almost no
  setup cost. Use this if you want to know what the pipe does once it is open.

Both modes are strictly sequential. There is deliberately no parallel mode:
the task asks for sequential requests, and a multi-connection number measures a
different property of the link.

Other things worth knowing when reading the numbers:

- `Accept-Encoding: identity` is sent so the server does not compress the
  body. The bytes counted are the bytes that crossed the wire, not the
  decompressed size.
- If the server answers with HTTP/1.0 or `Connection: close`, `--keep-alive`
  cannot actually reuse the connection and silently degrades to one
  connection per request.
- The first request to a CDN may be served from the origin and the rest from
  an edge cache, which can make request 1 an outlier.
- A single TCP connection ramps up (slow start); short downloads never reach
  full speed. Use a file of at least several megabytes.

## Tests

```bash
uv sync --extra dev          # or: pip install -e ".[dev]"
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests spin up a local HTTP (and HTTPS, with a throwaway self-signed
certificate) server. No test makes an HTTP request to the internet; the one
that checks DNS failure reporting resolves a name under the reserved
`.invalid` domain. They cover:

- the arithmetic: average time, total bytes, `total/total` throughput versus
  the mean of speeds, min/median/max, decimal unit conversions, empty run,
  zero duration;
- the downloader: real byte counting, chunked bodies without `Content-Length`,
  truncated bodies (plain and chunked), redirects (including loops and missing
  `Location`), non-2xx statuses, inactivity timeout that does not fire on a
  slow-but-flowing body, refused connections, DNS failures, malformed and
  non-ASCII URLs, `Accept-Encoding: identity`, new-connection-per-request vs
  keep-alive (checked by counting distinct client ports on the server side),
  keep-alive recovery after the server drops an idle connection and after a
  timeout, TLS verification and `--insecure`;
- the runner: exactly N requests, **requests never overlap** (the server
  delays every response, so sequential requests must start at least that far
  apart), stop on first failure, continue on later failure;
- the CLI: human output, `--quiet`, `--json` on a clean stdout, `--keep-alive`,
  `--insecure`, Ctrl-C, exit codes, argument validation, `python -m netmeter`.

CI runs the same on Python 3.10 through 3.14.

## Design decisions

1. **Count received bytes, don't trust `Content-Length`.** The header is what
   the server intends to send; the byte count is what arrived. They differ
   with chunked encoding (no header at all), with truncated transfers, and
   with misconfigured servers. Speed is bytes that arrived over time they took.
2. **`time.perf_counter()`.** Monotonic and high-resolution. `time.time()` can
   jump when the clock is adjusted by NTP, which would corrupt a measurement.
3. **`total_bytes / total_time`, not the mean of per-request speeds.**
   Explained in *How speed is calculated*.
4. **Stream the body.** Reading in 64 KiB chunks keeps memory flat whatever the
   file size, and lets the byte count be exact without ever holding the file.
5. **No retries.** A retry turns one failed measurement into a different,
   slower successful one and hides the failure. The run continues past a
   failed request instead, and reports it.
6. **Request time = from sending the request to the last body byte.** That is
   the only interval the client can observe end to end and the one users
   experience. Time to headers is kept separately for those who want to
   split it.
7. **New connection per request by default.** Explained in *Fresh connection
   vs keep-alive*.
8. **`http.client` instead of `urllib.request` in the package.** `urllib` gives
   no control over connection reuse; `http.client` makes both modes explicit
   with a few dozen lines and no third-party dependency. The minimal script
   uses `urllib` because it only needs the default mode.
9. **No third-party runtime dependencies.** A speed meter should be runnable
   on any machine with Python on it. Rich output, progress bars and an HTTP
   client library would each add a dependency for something the standard
   library does adequately here.

## Project layout

```
examples/minimal.py      the task in one file, stdlib only
src/netmeter/
  download.py            HTTP execution: connections, redirects, streaming, errors
  runner.py              the sequential loop and its failure policy
  stats.py               pure arithmetic: summary and unit conversions
  models.py              RequestResult / RequestFailure / Summary dataclasses
  cli.py                 argument parsing and output formatting
  __main__.py            makes `python -m netmeter` work
tests/                   pytest suite with a local HTTP/HTTPS server
.github/workflows/       ruff + pytest on every push
```
