import json
from datetime import UTC, datetime, timedelta, timezone

from capture.run import capture_source, file_name_for, find_file_links, folder_name
from capture.storage import LocalStorage


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body


T1 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)


def test_folder_name_is_utc_without_colons():
    nairobi = timezone(timedelta(hours=3))
    assert (
        folder_name(datetime(2026, 10, 8, 6, 0, 0, tzinfo=nairobi))
        == "2026-10-08T03-00-00Z"
    )


def test_find_file_links_resolves_filters_and_dedupes():
    body = b"""<html>
    <a href="/files/a.pdf">A</a>
    <a href="https://other.test/b.XLSX">B</a>
    <a href="c.csv?v=2#top">C</a>
    <a href="/files/a.pdf#page=3">A again</a>
    <a href="/contact-us/">Contact</a>
    <a href="mailto:x@example.test?subject=d.pdf">Mail</a>
    <a>no href</a>
    </html>"""
    assert find_file_links(body, "https://example.test/reports/") == [
        "https://example.test/files/a.pdf",
        "https://other.test/b.XLSX",
        "https://example.test/reports/c.csv?v=2",
    ]


def test_file_name_for_is_safe_and_unique():
    assert (
        file_name_for("https://example.test/x/Weekly%20Bulletin.pdf", set())
        == "Weekly_Bulletin.pdf"
    )
    assert (
        file_name_for("https://example.test/2025/report.pdf", {"report.pdf"})
        == "report_2.pdf"
    )


def test_same_timestamp_twice_fails_and_keeps_first_capture(tmp_path):
    source = {"id": "s", "kind": "page_table", "url": "https://example.test/s"}

    storage = LocalStorage(tmp_path)
    first = capture_source(source, lambda url: FakeResponse(200, b"first"), storage, T1)
    second = capture_source(
        source, lambda url: FakeResponse(200, b"second"), storage, T1
    )

    assert first["status"] == "ok"
    assert second["status"] == "failed"
    assert storage.read("raw/s/2026-10-08T03-00-00Z/page.html") == b"first"


def test_unknown_kind_fails_without_fetching(tmp_path):
    calls = []
    record = capture_source(
        {"id": "s", "kind": "typo", "url": "https://example.test/s"},
        lambda url: calls.append(url),
        LocalStorage(tmp_path),
        T1,
    )
    assert record["status"] == "failed"
    assert "unknown kind" in record["error"]
    assert calls == []


def test_failed_file_is_reported_and_left_out_of_manifest(tmp_path):
    responses = {
        "https://example.test/list": FakeResponse(
            200, b'<a href="a.pdf"></a><a href="b.pdf"></a>'
        ),
        "https://example.test/a.pdf": FakeResponse(200, b"A"),
        "https://example.test/b.pdf": FakeResponse(503, b"busy"),
    }
    record = capture_source(
        {"id": "s", "kind": "listing_page", "url": "https://example.test/list"},
        responses.__getitem__,
        LocalStorage(tmp_path),
        T1,
    )

    assert record["status"] == "ok"
    assert record["new_files"] == ["https://example.test/a.pdf"]
    assert "b.pdf" in record["error"]
    manifest = json.loads((tmp_path / "raw" / "s" / "manifest.json").read_text())
    assert list(manifest) == ["https://example.test/a.pdf"]


def test_crash_before_any_file_keeps_the_page_and_no_manifest(tmp_path):
    # Storage is write-once with no delete, so the finished page capture stays;
    # the PDF never finished, so it is neither stored nor in the manifest.
    def fetch(url):
        if url.endswith(".pdf"):
            raise KeyboardInterrupt
        return FakeResponse(200, b'<a href="a.pdf"></a>')

    storage = LocalStorage(tmp_path)
    try:
        capture_source(
            {"id": "s", "kind": "listing_page", "url": "https://example.test/l"},
            fetch,
            storage,
            T1,
        )
    except KeyboardInterrupt:
        pass

    assert storage.list("raw/s/") == [
        "raw/s/2026-10-08T03-00-00Z/meta.json",
        "raw/s/2026-10-08T03-00-00Z/page.html",
    ]


def test_previous_capture_without_meta_is_ignored(tmp_path):
    # A capture that died between page.html and meta.json must not count as "previous".
    storage = LocalStorage(tmp_path)
    storage.write("raw/s/2026-10-07T03-00-00Z/page.html", b"same")
    record = capture_source(
        {"id": "s", "kind": "page_table", "url": "https://example.test/s"},
        lambda url: FakeResponse(200, b"same"),
        storage,
        T1,
    )
    assert record["status"] == "ok"
    assert record["changed"] is True
