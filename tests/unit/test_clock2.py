import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml

from capture import http
from capture.run import capture_source
from capture.storage import LocalStorage

T1 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, status, body, final_url=None):
        self.status = status
        self.body = body
        if final_url is not None:
            self.final_url = final_url


# ---- 1. every sources*.yaml is in the image ----


def test_dockerfile_copies_every_sources_file():
    copies = [
        line.split()[1:-1]
        for line in (REPO / "Dockerfile").read_text().splitlines()
        if line.startswith("COPY ") and "--from" not in line
    ]
    assert ["sources*.yaml"] in copies
    # and there really are several files for that glob to pick up
    assert {"sources.yaml", "sources-regulatory.yaml"} <= {
        p.name for p in REPO.glob("sources*.yaml")
    }


# ---- 2. per-source crawl_delay ----


class Clock:
    """Fake time: sleeping moves the clock forward and is recorded."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


@pytest.fixture
def fetcher(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(http.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(http.time, "sleep", clock.sleep)
    f = http.Fetcher()
    f.client = type(
        "Client",
        (),
        {
            "get": lambda self, url: httpx.Response(
                200, request=httpx.Request("GET", url)
            )
        },
    )()
    return f, clock


def test_fetcher_pause_is_max_of_min_pause_and_default(fetcher):
    f, clock = fetcher
    f("https://a.test/1")  # first request: no pause
    f("https://a.test/2")  # default
    f("https://a.test/3", min_pause=5)  # crawl_delay above the default wins
    f("https://a.test/4", min_pause=1)  # below the default: default still applies
    assert clock.sleeps == [2, 5, 2]


def test_crawl_delay_is_passed_to_fetch_only_for_sources_that_set_it(tmp_path):
    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(200, b"page")

    storage = LocalStorage(tmp_path)
    capture_source(
        {"id": "a", "kind": "page_table", "url": "https://a.test"}, fetch, storage, T1
    )
    capture_source(
        {"id": "b", "kind": "page_table", "url": "https://b.test", "crawl_delay": 5},
        fetch,
        storage,
        T1,
    )
    assert calls == [{}, {"min_pause": 5}]


@pytest.mark.parametrize("bad", ["5", -1, True])
def test_bad_crawl_delay_fails_the_source_without_fetching(tmp_path, bad):
    calls = []
    record = capture_source(
        {"id": "a", "kind": "page_table", "url": "https://a.test", "crawl_delay": bad},
        lambda url, **kw: calls.append(url),
        LocalStorage(tmp_path),
        T1,
    )
    assert record["status"] == "failed"
    assert "crawl_delay" in record["error"]
    assert calls == []


def test_kenyalaw_sources_set_crawl_delay_5():
    sources = yaml.safe_load((REPO / "sources-regulatory.yaml").read_text())
    kenyalaw = [s for s in sources if s["id"].startswith("kenyalaw_")]
    assert len(kenyalaw) == 3
    assert all(s.get("crawl_delay") == 5 for s in kenyalaw)


# ---- 3. final_url in meta.json ----


def test_meta_records_final_url_after_redirects(tmp_path):
    storage = LocalStorage(tmp_path)
    capture_source(
        {"id": "law", "kind": "page_table", "url": "https://law.test/act/9"},
        lambda url: FakeResponse(
            200, b"act", final_url="https://law.test/act/9/eng@2024-12-27"
        ),
        storage,
        T1,
    )
    meta = json.loads(storage.read("raw/law/2026-10-08T03-00-00Z/meta.json"))
    assert meta["url"] == "https://law.test/act/9"
    assert meta["final_url"] == "https://law.test/act/9/eng@2024-12-27"


def test_meta_final_url_equals_url_when_fetch_reports_none(tmp_path):
    storage = LocalStorage(tmp_path)
    capture_source(
        {"id": "s", "kind": "page_table", "url": "https://s.test"},
        lambda url: FakeResponse(200, b"x"),
        storage,
        T1,
    )
    meta = json.loads(storage.read("raw/s/2026-10-08T03-00-00Z/meta.json"))
    assert meta["final_url"] == "https://s.test"


def test_fetcher_reports_final_url(fetcher):
    f, _ = fetcher
    assert f("https://a.test/x").final_url == "https://a.test/x"
