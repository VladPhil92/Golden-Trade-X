import hashlib
import json
from datetime import datetime

import pytest
import requests

from scripts.capture_official_calendar_sources import capture_sources
from scripts.materialize_official_calendar import BLS_YEAR_URL, FED_CALENDAR_URL


FED_HTML = """
<html><body>
<a href="/monetarypolicy/fomcstatement20210127a.htm">January statement</a>
<a href="/monetarypolicy/fomcstatement20210317a.htm">March statement</a>
<a href="/monetarypolicy/fomcstatement20210428a.htm">April statement</a>
<a href="/monetarypolicy/fomcstatement20210616a.htm">June statement</a>
<a href="/monetarypolicy/fomcstatement20210728a.htm">July statement</a>
<a href="/monetarypolicy/fomcstatement20210922a.htm">September statement</a>
<a href="/monetarypolicy/fomcstatement20211103a.htm">November statement</a>
<a href="/monetarypolicy/fomcstatement20211215a.htm">December statement</a>
</body></html>
"""


def _complete_bls_html(year: int) -> str:
    rows = ["<table><tr><th>Date</th><th>Time</th><th>Release</th></tr>"]
    for month in range(1, 13):
        nfp = datetime(year, month, 1)
        cpi = datetime(year, month, 2)
        rows.append(
            f"<tr><td>{nfp.strftime('%A, %B %d, %Y')}</td><td>08:30 AM</td>"
            "<td>Employment Situation for prior month</td></tr>"
        )
        rows.append(
            f"<tr><td>{cpi.strftime('%A, %B %d, %Y')}</td><td>08:30 AM</td>"
            "<td>Consumer Price Index for prior month</td></tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


class _Response:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"HTTP {self.status}")


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses

    def get(self, url, **kwargs):
        return self.responses[url]


def test_capture_validates_then_writes_hashed_source_bundle(tmp_path) -> None:
    bls_raw = _complete_bls_html(2021).encode("utf-8")
    fed_raw = FED_HTML.encode("utf-8")
    session = _Session(
        {
            BLS_YEAR_URL.format(year=2021): _Response(bls_raw),
            FED_CALENDAR_URL: _Response(fed_raw),
        }
    )
    target = tmp_path / "sources"

    manifest = capture_sources(
        2021,
        2021,
        target,
        session=session,
        captured_at_utc="2026-08-29T17:00:00Z",
    )

    assert manifest["methodology"] == "OFFICIAL_CALENDAR_SOURCE_SNAPSHOT_V1"
    assert manifest["approved"] is False
    assert manifest["counts_by_year"]["2021"] == {"NFP": 12, "CPI": 12, "FOMC": 8}
    assert (target / "bls-2021.html").read_bytes() == bls_raw
    assert (target / "fomccalendars.html").read_bytes() == fed_raw
    persisted = json.loads((target / "source_manifest.json").read_text(encoding="utf-8"))
    assert persisted == manifest
    assert manifest["sources"][0]["sha256"] == hashlib.sha256(bls_raw).hexdigest()
    assert manifest["sources"][1]["sha256"] == hashlib.sha256(fed_raw).hexdigest()


def test_capture_is_atomic_when_an_official_source_fails(tmp_path) -> None:
    session = _Session(
        {
            BLS_YEAR_URL.format(year=2021): _Response(_complete_bls_html(2021).encode("utf-8")),
            FED_CALENDAR_URL: _Response(b"blocked", status=403),
        }
    )
    target = tmp_path / "sources"

    with pytest.raises(requests.HTTPError):
        capture_sources(2021, 2021, target, session=session)

    assert not target.exists()
    assert not (tmp_path / ".sources.capture-tmp").exists()
