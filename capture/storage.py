"""Where captures are kept. Keys look like paths: raw/<id>/<stamp>/page.html.

Every storage has the same four methods:
    read(key)          -> bytes, or None if the key does not exist
    write(key, data)   write-once: raises FileExistsError if the key exists
    replace(key, data) overwrite; only the manifest uses this
    list(prefix)       -> sorted keys that start with prefix
"""

import os
import uuid
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient


def _check_key(key):
    """Keys are plain a/b/c paths: no empty parts, no "." or "..", no leading "/"."""
    if any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key:
        raise ValueError(f"unsafe storage key {key!r}")


class LocalStorage:
    """Keys are files under root. Writes are atomic: a key is absent or complete."""

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, key):
        _check_key(key)
        return self.root / key

    def _tmp_for(self, path):
        # hidden, so list() never shows a half-written file
        return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

    def read(self, key):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def write(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_for(path)
        tmp.write_bytes(data)
        try:
            os.link(tmp, path)  # fails with FileExistsError instead of overwriting
        finally:
            tmp.unlink()

    def replace(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_for(path)
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def list(self, prefix):
        if not self.root.exists():
            return []
        keys = (
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        )
        return sorted(key for key in keys if key.startswith(prefix))


class BlobStorage:
    """Keys are blobs in one Azure container.

    In Azure the job signs in with its managed identity (DefaultAzureCredential),
    so there is no key or password anywhere. Pass credential= only for Azurite.
    """

    def __init__(self, account_url, container, credential=None):
        self.container = ContainerClient(
            account_url, container, credential=credential or DefaultAzureCredential()
        )

    def read(self, key):
        _check_key(key)
        try:
            return self.container.download_blob(key).readall()
        except ResourceNotFoundError:
            return None

    def write(self, key, data):
        _check_key(key)
        try:
            self.container.upload_blob(key, data, overwrite=False)
        except ResourceExistsError:
            raise FileExistsError(key) from None

    def replace(self, key, data):
        _check_key(key)
        self.container.upload_blob(key, data, overwrite=True)

    def list(self, prefix):
        return sorted(self.container.list_blob_names(name_starts_with=prefix))
