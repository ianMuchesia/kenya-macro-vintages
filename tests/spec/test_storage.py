import pytest

from capture.storage import LocalStorage


def test_local_storage_is_write_once(tmp_path):
    storage = LocalStorage(tmp_path)

    # save a file called raw/x/page.html containing b first
    storage.write("raw/x/page.html", b"first")

    assert storage.read("raw/x/page.html") == b"first"

    with pytest.raises(FileExistsError):
        storage.write("raw/x/page.html", b"second")

    assert storage.read("raw/x/page.html") == b"first"

    assert storage.read("raw/x/missing.html") is None
