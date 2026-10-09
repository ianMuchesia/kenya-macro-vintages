"""Capture each source into its own timestamped folder under <out_dir>/raw/<id>/.

The page (page.html + meta.json) is built under a hidden staging name and
renamed into place only when complete, and an existing capture is never
overwritten. Linked files are then added to that folder one at a time: each is
written whole before manifest.json lists it, so if the process dies (Ctrl+C,
kill, power cut) every file in the manifest is on disk and the rest are
fetched by the next run.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
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


def _write_atomic(path, data):
    """Write bytes so path is either absent or complete, never half-written."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_json_atomic(path, data):
    _write_atomic(path, json.dumps(data, indent=2, sort_keys=True).encode())


def _read_manifest(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _previous_sha256(source_dir):
    """sha256 of the newest earlier capture of this source, or None if there is none."""
    if not source_dir.exists():
        return None
    for folder in sorted(source_dir.iterdir(), reverse=True):
        meta_path = folder / "meta.json"
        if folder.is_dir() and not folder.name.startswith(".") and meta_path.exists():
            return json.loads(meta_path.read_text())["sha256"]
    return None


def _remove_capture(capture_dir, source_dir):
    shutil.rmtree(capture_dir, ignore_errors=True)
    with contextlib.suppress(OSError):
        source_dir.rmdir()  # only succeeds if this left it empty


def _fetch_ok(fetch, url):
    response = fetch(url)
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")
    return response


def capture_source(source, fetch, out_dir, now):
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
        record.update(_capture(source, fetch, Path(out_dir), now, record))
        record["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - one failing source must never stop the others
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def _capture(source, fetch, out_dir, now, record):
    kind = source["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}, expected one of {KINDS}")

    response = fetch(source["url"])
    record["http"] = response.status
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")

    source_dir = out_dir / "raw" / source["id"]
    stamp = folder_name(now)
    final_dir = source_dir / stamp
    if final_dir.exists():
        raise FileExistsError(f"capture {final_dir} already exists")

    sha256 = _sha256(response.body)
    changed = sha256 != _previous_sha256(source_dir)

    staging_dir = source_dir / f".partial-{stamp}"
    shutil.rmtree(staging_dir, ignore_errors=True)  # leftover from a crashed run
    staging_dir.mkdir(parents=True)
    try:
        (staging_dir / "page.html").write_bytes(response.body)
        meta = {
            "url": source["url"],
            "fetched_at": stamp,
            "sha256": sha256,
            "status": response.status,
            "changed": changed,
        }
        _write_json_atomic(staging_dir / "meta.json", meta)
        staging_dir.rename(final_dir)
    except BaseException:
        _remove_capture(staging_dir, source_dir)
        raise

    downloaded = []
    file_errors = []
    if kind == "listing_page":
        manifest_path = source_dir / "manifest.json"
        manifest = _read_manifest(manifest_path)
        new_links = [
            url
            for url in find_file_links(response.body, source["url"])
            if url not in manifest
        ]
        taken = {"page.html", "meta.json"}
        try:
            for url in new_links[:MAX_NEW_FILES_PER_RUN]:
                try:
                    file_response = _fetch_ok(fetch, url)
                except Exception as exc:  # noqa: BLE001 - one failing file must not lose the others
                    file_errors.append(f"{url}: {type(exc).__name__}: {exc}")
                    continue
                name = file_name_for(url, taken)
                taken.add(name)
                _write_atomic(final_dir / name, file_response.body)
                # The file is safely on disk, so only now does it join the manifest.
                manifest[url] = {
                    "file": f"{stamp}/{name}",
                    "fetched_at": stamp,
                    "sha256": _sha256(file_response.body),
                }
                _write_json_atomic(manifest_path, manifest)
                downloaded.append(url)
        except BaseException:
            if (
                not downloaded
            ):  # interrupted before any file was kept: leave nothing behind
                _remove_capture(final_dir, source_dir)
            raise

    return {
        "sha256": sha256,
        "changed": changed,
        "new_files": downloaded,
        "error": "; ".join(file_errors) or None,
    }


def run(sources, fetch, out_dir, now, log_path):
    """Capture every source, writing one JSON log line per source as it finishes."""
    run_id = f"{folder_name(now)}-{uuid.uuid4().hex[:6]}"
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    with log_path.open("a") as log:
        for source in sources:
            record = {"run_id": run_id, **capture_source(source, fetch, out_dir, now)}
            log.write(json.dumps(record) + "\n")
            log.flush()
            records.append(record)
    return records
