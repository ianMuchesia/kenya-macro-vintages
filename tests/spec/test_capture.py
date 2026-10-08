import hashlib
import json
from datetime import UTC, datetime

import pytest
from capture.run import capture_source, run

#  ------------ Test helpers ----------------------


class FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body


class FakeFetch:
    """Pretends to be the internet, Maps url -> FakeResponse(or an exception)"""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def __call__(self, url: str) -> FakeResponse:
        self.calls.append(url)
        result = self.responses[url]

        if isinstance(result, Exception):
            raise result
        else:
            return result


T1 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 3, 5, 0, tzinfo=UTC)

D1 = "2026-10-08T03-00-00Z"  # folder name for T1
D2 = "2026-10-08T03-05-00Z"  # folder name for T2

CBR = {"id": "cbk_cbr", "kind": "page_table", "url": "https://example.test/cbr"}


# ------- 1. Never overwrite existing files -----------------


def test_two_captures_of_same_source_never_overwrite(tmp_path):
    fetch = FakeFetch(
        {
            CBR["url"]: FakeResponse(200, b"<html>day one</html> "),
        }
    )

    capture_source(CBR, fetch, tmp_path, T1)

    fetch.responses[CBR["url"]] = FakeResponse(200, b"<html>day two</html> ")

    capture_source(CBR, fetch, tmp_path, T2)

    folders = sorted((tmp_path / "raw" / "cbk_cbr").iterdir())

    assert len(folders) == 2
    bodies = [(folder / "page.html").read_bytes() for folder in folders]

    assert bodies == [b"<html>day one</html> ", b"<html>day two</html> "]


# ----- 2. Meta.json -----
def test_every_capture_writes_meta_with_url_time_hash_status(tmp_path):
    fake = FakeFetch(
        {
            CBR["url"]: FakeResponse(200, b"<html>day one</html> "),
        }
    )

    # open its meta.json file and check it has the right fields
    capture_source(CBR, fake, tmp_path, T1)

    meta_path = tmp_path / "raw" / "cbk_cbr" / D1 / "meta.json"
    meta = json.loads(meta_path.read_text())

    assert meta["url"] == CBR["url"]
    assert meta["fetched_at"] == D1
    assert meta["status"] == 200
    assert "sha256" in meta

    # and that sha256 matches with hash of the saved pages bytes(use hashlib )

    page_path = tmp_path / "raw" / "cbk_cbr" / D1 / "page.html"
    with open(page_path, "rb") as f:
        page_data = f.read()
    assert meta["sha256"] == hashlib.sha256(page_data).hexdigest()


# ------ 3. Listing pages-----------


def test_listing_link_already_in_manifest_is_not_downloaded_again(tmp_path):
    # a listing page linking to a.pdf and b.pdf

    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"""<html>
        <a href="a.pdf">A</a>
        <a href="b.pdf">B</a>
        </html>""",
            ),
            "https://example.test/a.pdf": FakeResponse(200, b"PDF A"),
            "https://example.test/b.pdf": FakeResponse(200, b"PDF B"),
        }
    )

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T1,
    )

    # first capture both downloaded
    assert (tmp_path / "raw" / "listing" / D1 / "a.pdf").exists()
    assert (tmp_path / "raw" / "listing" / D1 / "b.pdf").exists()

    # second capture: neither fetched again (check FakeFetch.calls)
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T2,
    )
    assert fake.calls.count("https://example.test/a.pdf") == 1
    assert fake.calls.count("https://example.test/b.pdf") == 1


def test_new_link_on_listing_page_is_downloaded(tmp_path):
    # a listing page linking to a.pdf and b.pdf

    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"""<html>
        <a href="a.pdf">A</a>
        <a href="b.pdf">B</a>
        </html>""",
            ),
            "https://example.test/a.pdf": FakeResponse(200, b"PDF A"),
            "https://example.test/b.pdf": FakeResponse(200, b"PDF B"),
            "https://example.test/c.pdf": FakeResponse(200, b"PDF C"),
        }
    )

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T1,
    )

    # first capture both downloaded
    assert (tmp_path / "raw" / "listing" / D1 / "a.pdf").exists()
    assert (tmp_path / "raw" / "listing" / D1 / "b.pdf").exists()

    # second capture: add c.pdf to the listing page
    fake.responses["https://example.test/listing"] = FakeResponse(
        200,
        b"""<html>
        <a href="a.pdf">A</a>
        <a href="b.pdf">B</a>
        <a href="c.pdf">C</a>
        </html>""",
    )

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T2,
    )

    # c.pdf should be downloaded now
    assert (tmp_path / "raw" / "listing" / D2 / "c.pdf").exists()


# -------  ----4. Failure Isolation --------------


def test_one_failing_source_does_not_stop_others(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/good": FakeResponse(200, b"good"),
            "https://example.test/bad": Exception("network error"),
        }
    )

    run(
        [
            {"id": "good", "kind": "page_table", "url": "https://example.test/good"},
            {"id": "bad", "kind": "page_table", "url": "https://example.test/bad"},
        ],
        fetch=fake,
        out_dir=tmp_path,
        now=T1,
        log_path=tmp_path / "capture.log",
    )

    # good should be captured
    assert (tmp_path / "raw" / "good" / D1 / "page.html").exists()

    meta_path = tmp_path / "raw" / "good" / D1 / "meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["status"] == 200

    # bad should not be captured
    assert not (tmp_path / "raw" / "bad").exists()


# ---------------------5.logging--------------------------


def test_every_source_produces_exactly_one_log_line(tmp_path):
    # run three sources, one of which fails
    fake = FakeFetch(
        {
            "https://example.test/good": FakeResponse(200, b"good"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": FakeResponse(404, b"not found"),
        }
    )

    log_path = tmp_path / "capture.log"
    run(
        [
            {"id": "good", "kind": "page_table", "url": "https://example.test/good"},
            {"id": "bad", "kind": "page_table", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "page_table", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        out_dir=tmp_path,
        now=T1,
        log_path=log_path,
    )

    # check log file has three lines, one for each source
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3

    # each with a source, status, and run_id
    for line in lines:
        log_entry = json.loads(line)
        assert "source" in log_entry
        assert "status" in log_entry
        assert "run_id" in log_entry


# ------------5. Website  is down or returns an error-----------


def test_source_with_404_or_network_error_is_logged(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/good": FakeResponse(200, b"good"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": FakeResponse(404, b"not found"),
        }
    )

    log_path = tmp_path / "capture.log"
    run(
        [
            {"id": "good", "kind": "listing_page", "url": "https://example.test/good"},
            {"id": "bad", "kind": "listing_page", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "listing_page", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        out_dir=tmp_path,
        now=T1,
        log_path=log_path,
    )

    lines = log_path.read_text().strip().splitlines()
    log_entries = [json.loads(line) for line in lines]

    good_entry = next(entry for entry in log_entries if entry["source"] == "good")
    bad_entry = next(entry for entry in log_entries if entry["source"] == "bad")
    ugly_entry = next(entry for entry in log_entries if entry["source"] == "ugly")

    assert good_entry["status"] == "ok"
    assert good_entry["http"] == 200

    # network error: failed, and no website answer at all
    assert bad_entry["status"] == "failed"
    assert bad_entry.get("http") is None

    # 404: failed, and the website's answer is kept separately
    assert ugly_entry["status"] == "failed"
    assert ugly_entry["http"] == 404


# -------------------the internet custs out completely--------------------


def test_all_sources_fail_is_logged(tmp_path):
    # the program does not crash and does not leave half-written files, and logs the errors
    fake = FakeFetch(
        {
            "https://example.test/good": Exception("network error"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": Exception("network error"),
        }
    )

    log_path = tmp_path / "capture.log"
    run(
        [
            {"id": "good", "kind": "page_table", "url": "https://example.test/good"},
            {"id": "bad", "kind": "page_table", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "page_table", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        out_dir=tmp_path,
        now=T1,
        log_path=log_path,
    )

    # check log file has three lines, one for each source
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3

    # each with a source, status, and run_id
    for line in lines:
        log_entry = json.loads(line)
        assert "source" in log_entry
        assert "status" in log_entry
        assert "run_id" in log_entry


# ---- A pdf download fails on day one


def test_pdf_download_fails_on_day_one_but_succeeds_on_day_two(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"""<html>
        <a href="a.pdf">A</a>
        </html>""",
            ),
            "https://example.test/a.pdf": Exception("network error"),
        }
    )

    # day one: pdf fails to download
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T1,
    )

    # day two: pdf is now available
    fake.responses["https://example.test/a.pdf"] = FakeResponse(200, b"PDF A")

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T2,
    )

    # check that a.pdf was downloaded on day two
    assert (tmp_path / "raw" / "listing" / D2 / "a.pdf").exists()


# same file name but different content on day two: should be saved as a new file, not overwrite the old one
@pytest.mark.xfail(
    reason="v0 known gap: same-URL replacement not detected; manifest skips known URLs"
)
def test_same_file_name_different_content_on_day_two(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"""<html>
        <a href="a.pdf">A</a>
        </html>""",
            ),
            "https://example.test/a.pdf": FakeResponse(200, b"PDF A v1"),
        }
    )

    # day one: pdf v1
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T1,
    )

    # day two: pdf v2
    fake.responses["https://example.test/a.pdf"] = FakeResponse(200, b"PDF A v2")

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T2,
    )

    # check that both versions exist
    assert (tmp_path / "raw" / "listing" / D1 / "a.pdf").exists()
    assert (tmp_path / "raw" / "listing" / D2 / "a.pdf").exists()

    # check that the contents are different
    with open(tmp_path / "raw" / "listing" / D1 / "a.pdf", "rb") as f:
        content_v1 = f.read()
    with open(tmp_path / "raw" / "listing" / D2 / "a.pdf", "rb") as f:
        content_v2 = f.read()

    assert content_v1 != content_v2


# A link dissapears from the listing page: should not be downloaded again, but old version remains
def test_link_disappears_from_listing_page(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"""<html>
        <a href="a.pdf">A</a>
        </html>""",
            ),
            "https://example.test/a.pdf": FakeResponse(200, b"PDF A v1"),
        }
    )

    # day one: pdf v1
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T1,
    )

    # day two: listing page no longer has a.pdf
    fake.responses["https://example.test/listing"] = FakeResponse(
        200,
        b"""<html>
        </html>""",
    )

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        tmp_path,
        T2,
    )

    # check that a.pdf from day one still exists
    assert (tmp_path / "raw" / "listing" / D1 / "a.pdf").exists()

    # check that a.pdf was not downloaded again on day two
    assert not (tmp_path / "raw" / "listing" / D2 / "a.pdf").exists()


# the page did not change at all: should not be downloaded again, but old version remains
def test_page_did_not_change(tmp_path):
    fake = FakeFetch(
        {
            "https://example.test/page": FakeResponse(
                200, b"<html>same content</html>"
            ),
        }
    )

    # day one: capture the page
    capture_source(
        {"id": "page", "kind": "listing_page", "url": "https://example.test/page"},
        fake,
        tmp_path,
        T1,
    )

    # day two: same content
    capture_source(
        {"id": "page", "kind": "listing_page", "url": "https://example.test/page"},
        fake,
        tmp_path,
        T2,
    )

    # check that the page from day one still exists
    assert (tmp_path / "raw" / "page" / D1 / "page.html").exists()

    # day two IS saved; meta says nothing changed
    assert (tmp_path / "raw" / "page" / T2 / "page.html").exists()
    meta2 = json.loads((tmp_path / "raw" / "page" / T2 / "meta.json").read_text())
    assert meta2["changed"] is False
