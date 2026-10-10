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


class Crash(BaseException):
    """Pretends the program was killed. `except Exception` does not catch it."""


class FakeFetch:
    """Pretends to be the internet, Maps url -> FakeResponse(or an exception)"""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def __call__(self, url: str) -> FakeResponse:
        self.calls.append(url)
        result = self.responses[url]

        if isinstance(result, BaseException):
            raise result
        else:
            return result


class MemoryStorage:
    """Pretends to be Azure storage. Keeps files in a dict: key -> bytes. write once,like the real one"""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}  # key -> bytes
        self.replaced = []  # keys that were overwritten in order

    def write(self, key: str, data: bytes):
        if key in self.blobs:
            raise FileExistsError(f"Blob {key} already exists")
        self.blobs[key] = data

    def read(self, key: str) -> bytes | None:
        return self.blobs.get(key)

    def replace(self, key: str, data: bytes):

        self.replaced.append(key)
        self.blobs[key] = data

    def list(self, prefix: str):
        return sorted(k for k in self.blobs if k.startswith(prefix))


T1 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 3, 5, 0, tzinfo=UTC)

D1 = "2026-10-08T03-00-00Z"  # folder name for T1
D2 = "2026-10-08T03-05-00Z"  # folder name for T2

CBR = {"id": "cbk_cbr", "kind": "page_table", "url": "https://example.test/cbr"}


# ------- 1. Never overwrite existing files -----------------


def test_two_captures_of_same_source_never_overwrite():

    storage = MemoryStorage()

    fetch = FakeFetch(
        {
            CBR["url"]: FakeResponse(200, b"<html>day one</html> "),
        }
    )

    capture_source(CBR, fetch, storage, T1)

    fetch.responses[CBR["url"]] = FakeResponse(200, b"<html>day two</html> ")

    capture_source(CBR, fetch, storage, T2)

    # every saved page of this source, oldest first
    pages = [key for key in storage.list("raw/cbk_cbr/") if key.endswith("/page.html")]

    assert len(pages) == 2
    bodies = [storage.read(key) for key in pages]

    assert bodies == [b"<html>day one</html> ", b"<html>day two</html> "]


# ----- 2. Meta.json -----
def test_every_capture_writes_meta_with_url_time_hash_status():
    storage = MemoryStorage()
    fake = FakeFetch(
        {
            CBR["url"]: FakeResponse(200, b"<html>day one</html> "),
        }
    )

    # open its meta.json file and check it has the right fields
    capture_source(CBR, fake, storage, T1)

    meta = json.loads(storage.read("raw/cbk_cbr/" + D1 + "/meta.json"))  # type: ignore

    assert meta["url"] == CBR["url"]
    assert meta["fetched_at"] == D1
    assert meta["status"] == 200
    assert "sha256" in meta

    # and that sha256 matches with hash of the saved pages bytes(use hashlib )

    page_data = storage.read("raw/cbk_cbr/" + D1 + "/page.html")  # type: ignore
    assert meta["sha256"] == hashlib.sha256(page_data).hexdigest()  # type: ignore


# ------ 3. Listing pages-----------


def test_listing_link_already_in_manifest_is_not_downloaded_again():
    # a listing page linking to a.pdf and b.pdf

    storage = MemoryStorage()

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
        storage,
        T1,
    )

    # first capture both downloaded
    assert storage.read("raw/listing/" + D1 + "/a.pdf") is not None
    assert storage.read("raw/listing/" + D1 + "/b.pdf") is not None

    # second capture: neither fetched again (check FakeFetch.calls)
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        storage,
        T2,
    )
    assert fake.calls.count("https://example.test/a.pdf") == 1
    assert fake.calls.count("https://example.test/b.pdf") == 1


def test_new_link_on_listing_page_is_downloaded():
    # a listing page linking to a.pdf and b.pdf

    storage = MemoryStorage()

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
        storage,
        T1,
    )

    # first capture both downloaded
    assert storage.read("raw/listing/" + D1 + "/a.pdf") is not None
    assert storage.read("raw/listing/" + D1 + "/b.pdf") is not None

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
        storage,
        T2,
    )

    # c.pdf should be downloaded now
    assert storage.read("raw/listing/" + D2 + "/c.pdf") is not None


# -------  ----4. Failure Isolation --------------


def test_one_failing_source_does_not_stop_others():
    storage = MemoryStorage()
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
        storage=storage,
        now=T1,
    )

    # good should be captured

    assert storage.read("raw/good/" + D1 + "/page.html") is not None

    meta = json.loads(storage.read("raw/good/" + D1 + "/meta.json"))  # type: ignore
    assert meta["status"] == 200

    assert storage.list("raw/bad/") == []


# ---------------------5.logging--------------------------


def test_every_source_produces_exactly_one_log_line():
    # run three sources, one of which fails
    storage = MemoryStorage()
    fake = FakeFetch(
        {
            "https://example.test/good": FakeResponse(200, b"good"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": FakeResponse(404, b"not found"),
        }
    )

    run(
        [
            {"id": "good", "kind": "page_table", "url": "https://example.test/good"},
            {"id": "bad", "kind": "page_table", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "page_table", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        storage=storage,
        now=T1,
    )

    # check log file has three lines, one for each source
    log_keys = storage.list("logs/")
    assert len(log_keys) == 1
    lines = storage.read(log_keys[0]).decode().strip().splitlines()  # type: ignore

    assert len(lines) == 3

    # each with a source, status, and run_id
    for line in lines:
        log_entry = json.loads(line)
        assert "source" in log_entry
        assert "status" in log_entry
        assert "run_id" in log_entry


# ------------5. Website  is down or returns an error-----------


def test_source_with_404_or_network_error_is_logged():
    storage = MemoryStorage()
    fake = FakeFetch(
        {
            "https://example.test/good": FakeResponse(200, b"good"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": FakeResponse(404, b"not found"),
        }
    )

    run(
        [
            {"id": "good", "kind": "listing_page", "url": "https://example.test/good"},
            {"id": "bad", "kind": "listing_page", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "listing_page", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        storage=storage,
        now=T1,
    )

    log_keys = storage.list("logs/")
    assert len(log_keys) == 1
    lines = storage.read(log_keys[0]).decode().strip().splitlines()  # type: ignore

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


def test_all_sources_fail_is_logged():
    # the program does not crash and does not leave half-written files, and logs the errors
    storage = MemoryStorage()
    fake = FakeFetch(
        {
            "https://example.test/good": Exception("network error"),
            "https://example.test/bad": Exception("network error"),
            "https://example.test/ugly": Exception("network error"),
        }
    )

    run(
        [
            {"id": "good", "kind": "page_table", "url": "https://example.test/good"},
            {"id": "bad", "kind": "page_table", "url": "https://example.test/bad"},
            {"id": "ugly", "kind": "page_table", "url": "https://example.test/ugly"},
        ],
        fetch=fake,
        storage=storage,
        now=T1,
    )

    # check log file has three lines, one for each source
    log_keys = storage.list("logs/")
    assert len(log_keys) == 1
    lines = storage.read(log_keys[0]).decode().strip().splitlines()  # type: ignore
    assert len(lines) == 3

    # each with a source, status, and run_id
    for line in lines:
        log_entry = json.loads(line)
        assert "source" in log_entry
        assert "status" in log_entry
        assert "run_id" in log_entry


# ---- A pdf download fails on day one


def test_pdf_download_fails_on_day_one_but_succeeds_on_day_two():
    storage = MemoryStorage()
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
        storage,
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
        storage,
        T2,
    )

    # check that a.pdf was downloaded on day two
    assert storage.read("raw/listing/" + D2 + "/a.pdf") is not None


# same file name but different content on day two: should be saved as a new file, not overwrite the old one
@pytest.mark.xfail(
    reason="v0 known gap: same-URL replacement not detected; manifest skips known URLs"
)
def test_same_file_name_different_content_on_day_two():
    storage = MemoryStorage()
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
        storage,
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
        storage,
        T2,
    )

    # check that both versions exist
    assert storage.read("raw/listing/" + D1 + "/a.pdf") is not None
    assert storage.read("raw/listing/" + D2 + "/a.pdf") is not None

    # check that the contents are different
    content_v1 = storage.read("raw/listing/" + D1 + "/a.pdf")
    content_v2 = storage.read("raw/listing/" + D2 + "/a.pdf")

    assert content_v1 != content_v2


# A link dissapears from the listing page: should not be downloaded again, but old version remains
def test_link_disappears_from_listing_page():
    storage = MemoryStorage()
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
        storage,
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
        storage,
        T2,
    )

    # check that a.pdf from day one still exists
    assert storage.read("raw/listing/" + D1 + "/a.pdf") is not None

    # check that a.pdf was not downloaded again on day two
    assert storage.read("raw/listing/" + D2 + "/a.pdf") is None


# the page did not change at all: should not be downloaded again, but old version remains
def test_page_did_not_change():
    storage = MemoryStorage()
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
        storage,
        T1,
    )

    # day two: same content
    capture_source(
        {"id": "page", "kind": "listing_page", "url": "https://example.test/page"},
        fake,
        storage,
        T2,
    )

    # check that the page from day one still exists
    assert storage.read("raw/page/" + D1 + "/page.html") is not None

    # day two IS saved; meta says nothing changed
    assert storage.read("raw/page/" + D2 + "/page.html") is not None
    meta2 = json.loads(storage.read("raw/page/" + D2 + "/meta.json"))  # type: ignore
    assert meta2["changed"] is False


def test_files_downloaded_before_a_crash_are_kept_in_manifest():
    storage = MemoryStorage()
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
            "https://example.test/b.pdf": Crash(),  # the program dies here
        }
    )

    with pytest.raises(Crash):
        capture_source(
            {
                "id": "listing",
                "kind": "listing_page",
                "url": "https://example.test/listing",
            },
            fake,
            storage,
            T1,
        )

    # a.pdf was finished before the crash: it is in the manifest AND on disk
    manifest = json.loads(storage.read("raw/listing/manifest.json"))  # type: ignore
    assert "https://example.test/a.pdf" in manifest
    entry = manifest["https://example.test/a.pdf"]
    assert storage.read("raw/listing/" + entry["file"]) is not None

    # b.pdf was never finished: it is not in the manifest
    assert "https://example.test/b.pdf" not in manifest


def test_at_most_50_new_files_are_downloaded_per_run():
    # a listing page with 100 links, but only 50 should be downloaded per run
    storage = MemoryStorage()
    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200,
                b"<html>"
                + b"".join(
                    f'<a href="file{i}.pdf">File {i}</a>'.encode() for i in range(100)
                )
                + b"</html>",
            ),
            **{
                f"https://example.test/file{i}.pdf": FakeResponse(
                    200, f"PDF {i}".encode()
                )
                for i in range(100)
            },
        }
    )

    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        storage,
        T1,
    )

    # check that only 50 files were downloaded
    # first run: only 50 files
    day1_files = [
        key for key in storage.list("raw/listing/" + D1) if key.endswith(".pdf")
    ]
    assert len(day1_files) == 50

    # second run: the next 50, none repeated
    capture_source(
        {
            "id": "listing",
            "kind": "listing_page",
            "url": "https://example.test/listing",
        },
        fake,
        storage,
        T2,
    )

    day2_files = [
        key for key in storage.list("raw/listing/" + D2) if key.endswith(".pdf")
    ]
    assert len(day2_files) == 50

    assert {k.split("/")[-1] for k in day1_files}.isdisjoint(
        {k.split("/")[-1] for k in day2_files}
    )


def test_capturer_never_overwrites_a_raw_object():
    storage = MemoryStorage()

    storage.blobs[f"raw/cbk_cbr/{D1}/page.html"] = b"original content"

    fake = FakeFetch({CBR["url"]: FakeResponse(200, b"new")})

    record = capture_source(CBR, fake, storage, T1)

    # the original content is still there, not overwritten
    assert record["status"] == "failed"
    assert storage.read(f"raw/cbk_cbr/{D1}/page.html") == b"original content"

    record2 = capture_source(CBR, fake, storage, T2)

    assert record2["status"] == "ok"
    assert storage.read(f"raw/cbk_cbr/{D2}/page.html") == b"new"


def test_manifest_is_the_only_thing_replaced():
    storage = MemoryStorage()

    listing = {
        "id": "listing",
        "kind": "listing_page",
        "url": "https://example.test/listing",
    }

    fake = FakeFetch(
        {
            "https://example.test/listing": FakeResponse(
                200, b'<a href="a.pdf">A</a><a href="b.pdf">B</a>'
            ),
            "https://example.test/a.pdf": FakeResponse(200, b"PDF A"),
            "https://example.test/b.pdf": FakeResponse(200, b"PDF B"),
            "https://example.test/c.pdf": FakeResponse(200, b"PDF C"),
        }
    )

    capture_source(listing, fake, storage, T1)

    fake.responses["https://example.test/listing"] = FakeResponse(
        200, b'<a href="a.pdf">A</a><a href="b.pdf">B</a><a href="c.pdf">C</a>'
    )

    capture_source(listing, fake, storage, T2)

    # postive checks: both runs saved their files
    assert storage.read(f"raw/listing/{D1}/a.pdf") == b"PDF A"
    assert storage.read(f"raw/listing/{D1}/b.pdf") == b"PDF B"
    assert storage.read(f"raw/listing/{D2}/c.pdf") == b"PDF C"

    # manifest is replaced, but no other files are replaced
    assert storage.replaced

    assert all(key == "raw/listing/manifest.json" for key in storage.replaced)
