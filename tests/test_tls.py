"""TLS behaviour against a local HTTPS server with a self-signed certificate."""

from __future__ import annotations

import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from netmeter.cli import main
from netmeter.download import Downloader, DownloadError
from tests.conftest import LocalServer

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


@pytest.fixture
def tls_server(tmp_path: Path) -> Iterator[LocalServer]:
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-days", "1",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)

    srv = LocalServer()
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    srv.scheme = "https"
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def test_self_signed_certificate_is_rejected_by_default(tls_server) -> None:
    with (
        Downloader() as d,
        pytest.raises(DownloadError, match="TLS certificate verification failed"),
    ):
        d.download(tls_server.url("/file?size=10"))


def test_insecure_mode_skips_verification(tls_server) -> None:
    with Downloader(verify_tls=False, keep_alive=True) as d:
        first = d.download(tls_server.url("/file?size=10"))
        second = d.download(tls_server.url("/file?size=20"))
    assert (first.downloaded_bytes, second.downloaded_bytes) == (10, 20)
    ports = [r.client_port for r in tls_server.records]
    assert len(ports) == 2 and len(set(ports)) == 1  # keep-alive works over TLS


def test_cli_insecure_flag(tls_server, capsys) -> None:
    assert main([tls_server.url("/file?size=10"), "-n", "1", "-q"]) == 1
    err = capsys.readouterr().err
    assert "TLS certificate verification failed" in err
    assert "hint:" not in err  # a self-signed cert is not a missing CA bundle
    assert main([tls_server.url("/file?size=10"), "-n", "1", "-q", "--insecure"]) == 0
