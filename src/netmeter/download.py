"""HTTP download execution on top of the standard library's ``http.client``.

``http.client`` (rather than ``urllib.request``) is used so that the same code
can either open a brand-new connection for every request or deliberately reuse
one, because that choice changes what a measurement means.
"""

from __future__ import annotations

import http.client
import socket
import ssl
from time import perf_counter
from urllib.parse import SplitResult, urljoin, urlsplit

from netmeter.models import RequestResult

DEFAULT_TIMEOUT = 30.0
DEFAULT_CHUNK_SIZE = 64 * 1024
MAX_REDIRECTS = 10
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "netmeter/0.1 (+https://github.com/AsmodaiP/internet-speed-test)"

ConnectionKey = tuple[str, str, int]


class DownloadError(Exception):
    """A request could not be completed: network error, timeout or HTTP error."""


class Downloader:
    """Downloads a URL and measures how long it took.

    With ``keep_alive=False`` (the default) every :meth:`download` opens a new
    TCP (and TLS) connection and closes it afterwards, so every measurement is
    independent and includes connection setup. With ``keep_alive=True``
    connections are kept between calls, like a browser or a pooled HTTP client
    would do, and only the first request pays for the handshake.

    Response bodies are streamed in chunks and discarded, so memory usage does
    not depend on the size of the file.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        keep_alive: bool = False,
        verify_tls: bool = True,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._verify_tls = verify_tls
        self._chunk_size = chunk_size
        self._connections: dict[ConnectionKey, http.client.HTTPConnection] = {}

    def __enter__(self) -> Downloader:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close every open connection."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()

    def download(self, url: str, *, index: int = 0) -> RequestResult:
        """GET ``url``, read the whole body and return timing and size."""
        started = perf_counter()
        try:
            response, final_url = self._open(url)
            time_to_first_byte = perf_counter() - started
            received = 0
            while chunk := response.read(self._chunk_size):
                received += len(chunk)
            duration = perf_counter() - started
        except DownloadError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise DownloadError(self._describe(exc)) from exc
        finally:
            if not self._keep_alive:
                self.close()

        return RequestResult(
            index=index,
            duration=duration,
            downloaded_bytes=received,
            time_to_first_byte=time_to_first_byte,
            status=response.status,
            content_length=_content_length(response),
            final_url=final_url,
        )

    # -- internals ---------------------------------------------------------

    def _open(self, url: str) -> tuple[http.client.HTTPResponse, str]:
        """Send the request, follow redirects, return the final response."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            key = _connection_key(parts)
            response = self._send(key, _request_target(parts))

            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                response.read()  # drain the (tiny) body so the connection stays usable
                if not location:
                    raise DownloadError(
                        f"HTTP {response.status} redirect without a Location header"
                    )
                current = urljoin(current, location)
                continue

            if not 200 <= response.status < 300:
                self._drop(key)
                raise DownloadError(f"HTTP {response.status} {response.reason}".rstrip())

            return response, current

        raise DownloadError(f"too many redirects (more than {MAX_REDIRECTS})")

    def _send(self, key: ConnectionKey, target: str) -> http.client.HTTPResponse:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
        reused = key in self._connections
        conn = self._connections.get(key) or self._connect(key)
        try:
            conn.request("GET", target, headers=headers)
            return conn.getresponse()
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
            if not reused:
                raise
            # A kept-alive connection was closed by the server while idle.
            # Nothing was transferred yet, so retry once on a fresh connection.
            self._drop(key)
            conn = self._connect(key)
            conn.request("GET", target, headers=headers)
            return conn.getresponse()

    def _connect(self, key: ConnectionKey) -> http.client.HTTPConnection:
        scheme, host, port = key
        conn: http.client.HTTPConnection
        if scheme == "https":
            context = _ssl_context(verify=self._verify_tls)
            conn = http.client.HTTPSConnection(host, port, timeout=self._timeout, context=context)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=self._timeout)
        self._connections[key] = conn
        return conn

    def _drop(self, key: ConnectionKey) -> None:
        conn = self._connections.pop(key, None)
        if conn is not None:
            conn.close()

    def _describe(self, exc: BaseException) -> str:
        if isinstance(exc, TimeoutError):
            return f"timed out after {self._timeout:g} s without receiving data"
        if isinstance(exc, socket.gaierror):
            return f"DNS resolution failed: {exc.strerror or exc}"
        if isinstance(exc, ConnectionRefusedError):
            return "connection refused"
        if isinstance(exc, ssl.SSLCertVerificationError):
            return f"TLS certificate verification failed: {exc.verify_message}"
        if isinstance(exc, ssl.SSLError):
            return f"TLS error: {exc.reason or exc}"
        if isinstance(exc, http.client.RemoteDisconnected):
            return "server closed the connection before sending a response"
        if isinstance(exc, http.client.IncompleteRead):
            return f"server closed the connection mid-body ({len(exc.partial)} bytes received)"
        return f"{type(exc).__name__}: {exc}"


def _ssl_context(*, verify: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    # Some Python builds (notably the python.org installer on macOS) ship
    # without a CA bundle. If certifi happens to be installed, use it too.
    try:
        import certifi
    except ImportError:
        return context
    context.load_verify_locations(certifi.where())
    return context


def _connection_key(parts: SplitResult) -> ConnectionKey:
    if parts.scheme not in ("http", "https"):
        raise DownloadError(f"unsupported URL scheme {parts.scheme!r}: use http:// or https://")
    if not parts.hostname:
        raise DownloadError("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise DownloadError(f"invalid port in URL: {exc}") from exc
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return parts.scheme, parts.hostname, port


def _request_target(parts: SplitResult) -> str:
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return target


def _content_length(response: http.client.HTTPResponse) -> int | None:
    raw = response.getheader("Content-Length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
