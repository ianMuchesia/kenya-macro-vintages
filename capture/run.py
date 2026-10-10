"""Capture each source under its own timestamped prefix: raw/<id>/<stamp>/.

Everything goes through a storage object (see capture/storage.py), which is
write-once: a saved key can never be overwritten. The only key that is ever
replaced is raw/<id>/manifest.json, the index of files already downloaded.

page.html is saved first and meta.json last, so a capture without meta.json is
incomplete and is ignored. Linked files are then saved one at a time, each one
whole before the manifest lists it: if the process dies (Ctrl+C, kill, power
cut) every file in the manifest is in storage and the rest are fetched by the
next run.
"""

import hashlib
import json
import re
import uuid
from datetime import UTC
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse

KINDS = ("page_table", "listing_page")
FILE_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".csv")
MAX_NEW_FILES_PER_RUN = (
    50  # a big backlog is fetched over several runs, not all at once
)


def folder_name(now):
    """2026-10-08T03:00:00+00:00 -> 2026-10-08T03-00-00Z (no colons, safe on every OS)."""
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value.strip())


def find_file_links(body, base_url):
    """Absolute URLs of every linked data file on the page, in page order, without repeats."""
    parser = _LinkParser()
    parser.feed(body.decode("utf-8", errors="replace"))

    links = []
    for href in parser.hrefs:
        url, _fragment = urldefrag(urljoin(base_url, href))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.path.lower().endswith(FILE_EXTENSIONS) and url not in links:
            links.append(url)
    return links


def file_name_for(url, taken):
    """A safe local file name for url that is not already in taken."""
    name = unquote(Path(urlparse(url).path).name)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".") or "file"

    stem, suffix = Path(name).stem, Path(name).suffix
    candidate = name
    n = 2
    while candidate in taken:
        candidate = f"{stem}_{n}{suffix}"
        n += 1
    return candidate


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data):
    return json.dumps(data, indent=2, sort_keys=True).encode()


def _read_manifest(storage, key):
    data = storage.read(key)
    return json.loads(data) if data is not None else {}


def _previous_sha256(storage, source_prefix):
    """sha256 of the newest complete capture of this source, or None if there is none."""
    metas = [
        key
        for key in storage.list(source_prefix)
        if key.count("/") == source_prefix.count("/") + 1 and key.endswith("/meta.json")
    ]
    if not metas:
        return None
    return json.loads(storage.read(metas[-1]))["sha256"]


def _fetch_ok(fetch, url):
    response = fetch(url)
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")
    return response


def capture_source(source, fetch, storage, now):
    """Capture one source. Never raises: any failure comes back as a "failed" record."""
    record = {
        "source": None,
        "status": "failed",
        "http": None,
        "sha256": None,
        "changed": None,
        "new_files": [],
        "error": None,
    }
    try:
        record["source"] = source["id"]
        record.update(_capture(source, fetch, storage, now, record))
        record["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - one failing source must never stop the others
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def _capture(source, fetch, storage, now, record):
    kind = source["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}, expected one of {KINDS}")

    response = fetch(source["url"])
    record["http"] = response.status
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")

    source_prefix = f"raw/{source['id']}/"
    stamp = folder_name(now)
    capture_prefix = f"{source_prefix}{stamp}/"
    if storage.list(capture_prefix):
        raise FileExistsError(f"capture {capture_prefix} already exists")

    sha256 = _sha256(response.body)
    changed = sha256 != _previous_sha256(storage, source_prefix)

    storage.write(capture_prefix + "page.html", response.body)
    meta = {
        "url": source["url"],
        "fetched_at": stamp,
        "sha256": sha256,
        "status": response.status,
        "changed": changed,
    }
    storage.write(
        capture_prefix + "meta.json", _json_bytes(meta)
    )  # last: marks it complete

    downloaded = []
    file_errors = []
    if kind == "listing_page":
        manifest_key = source_prefix + "manifest.json"
        manifest = _read_manifest(storage, manifest_key)
        new_links = [
            url
            for url in find_file_links(response.body, source["url"])
            if url not in manifest
        ]
        taken = {"page.html", "meta.json"}
        for url in new_links[:MAX_NEW_FILES_PER_RUN]:
            try:
                file_response = _fetch_ok(fetch, url)
            except Exception as exc:  # noqa: BLE001 - one failing file must not lose the others
                file_errors.append(f"{url}: {type(exc).__name__}: {exc}")
                continue
            name = file_name_for(url, taken)
            taken.add(name)
            storage.write(capture_prefix + name, file_response.body)
            # The file is safely stored, so only now does it join the manifest.
            manifest[url] = {
                "file": f"{stamp}/{name}",
                "fetched_at": stamp,
                "sha256": _sha256(file_response.body),
            }
            storage.replace(manifest_key, _json_bytes(manifest))
            downloaded.append(url)

    return {
        "sha256": sha256,
        "changed": changed,
        "new_files": downloaded,
        "error": "; ".join(file_errors) or None,
    }


def run(sources, fetch, storage, now):
    """Capture every source, then save one log object per run: logs/<run_id>.jsonl.

    Each log line is also printed as it happens, so a run that dies part-way
    still shows its progress in the job's console logs.
    """
    run_id = f"{folder_name(now)}-{uuid.uuid4().hex[:6]}"
    records = []
    try:
        for source in sources:
            record = {"run_id": run_id, **capture_source(source, fetch, storage, now)}
            print(json.dumps(record), flush=True)
            records.append(record)
    finally:
        lines = "".join(json.dumps(record) + "\n" for record in records)
        storage.write(f"logs/{run_id}.jsonl", lines.encode())
    return records
