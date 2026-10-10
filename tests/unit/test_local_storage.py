import pytest

from capture.storage import LocalStorage


def test_replace_overwrites(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.replace("raw/s/manifest.json", b"v1")
    storage.replace("raw/s/manifest.json", b"v2")
    assert storage.read("raw/s/manifest.json") == b"v2"


def test_list_is_sorted_filtered_by_prefix_and_hides_temp_files(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.write("raw/b/x", b"")
    storage.write("raw/a/y", b"")
    storage.write("logs/r.jsonl", b"")
    (tmp_path / "raw" / "a" / ".y.123.tmp").write_bytes(b"half")
    assert storage.list("raw/") == ["raw/a/y", "raw/b/x"]
    assert LocalStorage(tmp_path / "missing").list("") == []


def test_failed_write_leaves_no_temp_file(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.write("k", b"1")
    with pytest.raises(FileExistsError):
        storage.write("k", b"2")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["k"]


@pytest.mark.parametrize("key", ["../escape", "/abs", "a//b", "a/./b", ""])
def test_unsafe_keys_are_rejected(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).read(key)
