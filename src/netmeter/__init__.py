"""netmeter: measure download speed with sequential HTTP requests."""

from netmeter.download import Downloader, DownloadError
from netmeter.models import RequestFailure, RequestResult, Summary
from netmeter.runner import measure, run
from netmeter.stats import summarize

__version__ = "0.1.0"

__all__ = [
    "DownloadError",
    "Downloader",
    "RequestFailure",
    "RequestResult",
    "Summary",
    "measure",
    "run",
    "summarize",
]
