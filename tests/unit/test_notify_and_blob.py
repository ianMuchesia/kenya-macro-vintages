import argparse

import httpx
import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from capture.__main__ import make_storage
from capture.notify import ping_heartbeat, send_telegram
from capture.storage import BlobStorage, LocalStorage


class FakePost:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return httpx.Response(self.status, request=httpx.Request("POST", url))


def test_heartbeat_pings_success_or_fail_url():
    post = FakePost()
    ping_heartbeat("https://hc.test/abc", [], post=post)
    ping_heartbeat("https://hc.test/abc/", ["cbk_cbr"], post=post)
    assert [url for url, _ in post.calls] == [
        "https://hc.test/abc",
        "https://hc.test/abc/fail",
    ]


def test_telegram_sends_one_message_only_when_something_failed():
    post = FakePost()
    send_telegram("TOKEN", "42", [], post=post)
    assert post.calls == []

    send_telegram("TOKEN", "42", ["cbk_cbr", "knbs_cpi"], post=post)
    assert len(post.calls) == 1
    url, kwargs = post.calls[0]
    assert url == "https://api.telegram.org/botTOKEN/sendMessage"
    assert kwargs["json"]["chat_id"] == "42"
    assert "cbk_cbr, knbs_cpi" in kwargs["json"]["text"]


def test_alert_errors_are_printed_without_the_token(capsys):
    send_telegram("SECRET", "42", ["x"], post=FakePost(status=500))
    ping_heartbeat("https://hc.test/abc", [], post=FakePost(status=500))
    out = capsys.readouterr().out
    assert "telegram alert failed" in out
    assert "heartbeat ping failed" in out
    assert "SECRET" not in out


class FakeContainer:
    """Behaves like azure ContainerClient for the calls BlobStorage makes."""

    def __init__(self):
        self.blobs = {}

    def download_blob(self, key):
        if key not in self.blobs:
            raise ResourceNotFoundError("missing")
        data = self.blobs[key]
        return type("Downloader", (), {"readall": lambda self: data})()

    def upload_blob(self, key, data, overwrite):
        if key in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[key] = data

    def list_blob_names(self, name_starts_with):
        return [k for k in reversed(self.blobs) if k.startswith(name_starts_with)]


def blob_storage():
    storage = BlobStorage.__new__(BlobStorage)  # skip the real Azure client
    storage.container = FakeContainer()
    return storage


def test_blob_storage_is_write_once_and_maps_azure_errors():
    storage = blob_storage()
    storage.write("raw/s/page.html", b"first")
    with pytest.raises(FileExistsError):
        storage.write("raw/s/page.html", b"second")
    assert storage.read("raw/s/page.html") == b"first"
    assert storage.read("raw/s/missing") is None

    storage.replace("raw/s/manifest.json", b"v1")
    storage.replace("raw/s/manifest.json", b"v2")
    assert storage.read("raw/s/manifest.json") == b"v2"
    assert storage.list("raw/") == ["raw/s/manifest.json", "raw/s/page.html"]


def test_blob_storage_rejects_unsafe_keys():
    with pytest.raises(ValueError):
        blob_storage().write("../x", b"")


def test_make_storage_defaults_to_local_and_checks_blob_settings():
    parser = argparse.ArgumentParser()
    assert isinstance(make_storage({}, parser), LocalStorage)
    with pytest.raises(SystemExit):
        make_storage({"STORAGE": "blob"}, parser)
    with pytest.raises(SystemExit):
        make_storage({"STORAGE": "s3"}, parser)
