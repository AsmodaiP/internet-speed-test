import socket

import pytest

from netmeter.download import Downloader, DownloadError


def test_reads_whole_body_and_counts_real_bytes(server) -> None:
    with Downloader() as d:
        r = d.download(server.url("/file?size=123456"), index=1)
    assert r.index == 1
    assert r.status == 200
    assert r.downloaded_bytes == 123456
    assert r.content_length == 123456
    assert not r.content_length_mismatch
    assert 0 < r.time_to_first_byte <= r.duration


def test_sends_identity_encoding_so_bytes_on_the_wire_are_counted(server) -> None:
    with Downloader() as d:
        d.download(server.url("/file"))
    headers = server.records[0].headers
    assert headers["Accept-Encoding"] == "identity"
    assert headers["User-Agent"].startswith("netmeter/")


def test_chunked_body_without_content_length(server) -> None:
    with Downloader() as d:
        r = d.download(server.url("/chunked"))
    assert r.downloaded_bytes == 500
    assert r.content_length is None
    assert not r.content_length_mismatch


def test_truncated_body_is_detected_not_trusted(server) -> None:
    with Downloader() as d:
        r = d.download(server.url("/truncated"))
    assert r.downloaded_bytes == 400
    assert r.content_length == 1000
    assert r.content_length_mismatch


def test_follows_redirects_and_reports_final_url(server) -> None:
    with Downloader() as d:
        r = d.download(server.url("/redirect"))
    assert r.status == 200
    assert r.downloaded_bytes == 500
    assert r.final_url == server.url("/file?size=500")


def test_redirect_loop_gives_up(server) -> None:
    with Downloader() as d, pytest.raises(DownloadError, match="too many redirects"):
        d.download(server.url("/redirect-loop"))


def test_redirect_without_location_is_an_error(server) -> None:
    with Downloader() as d, pytest.raises(DownloadError, match="without a Location"):
        d.download(server.url("/redirect-nowhere"))


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_status_is_a_failure(server, status: int) -> None:
    with Downloader() as d, pytest.raises(DownloadError, match=f"HTTP {status}"):
        d.download(server.url(f"/status/{status}"))


def test_timeout_is_inactivity_based(server) -> None:
    with Downloader(timeout=0.2) as d, pytest.raises(DownloadError, match="timed out"):
        d.download(server.url("/file?delay=2"))


def test_connection_refused() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with Downloader() as d, pytest.raises(DownloadError, match="connection refused"):
        d.download(f"http://127.0.0.1:{port}/file")


def test_dns_failure_is_reported_clearly() -> None:
    with Downloader() as d, pytest.raises(DownloadError, match="DNS resolution failed"):
        d.download("http://this-host-does-not-exist.invalid/file")


@pytest.mark.parametrize("url", ["ftp://example.com/x", "example.com/x", "http:///x"])
def test_bad_urls_are_rejected(url: str) -> None:
    with Downloader() as d, pytest.raises(DownloadError):
        d.download(url)


def test_new_connection_per_request_by_default(server) -> None:
    with Downloader() as d:
        for _ in range(3):
            d.download(server.url("/file"))
    ports = {rec.client_port for rec in server.records}
    assert len(ports) == 3


def test_keep_alive_reuses_one_connection(server) -> None:
    with Downloader(keep_alive=True) as d:
        for _ in range(3):
            d.download(server.url("/file"))
    ports = {rec.client_port for rec in server.records}
    assert len(ports) == 1


def test_keep_alive_survives_redirect_and_error(server) -> None:
    with Downloader(keep_alive=True) as d:
        d.download(server.url("/redirect"))
        with pytest.raises(DownloadError):
            d.download(server.url("/status/404"))
        r = d.download(server.url("/file?size=10"))
    assert r.downloaded_bytes == 10
