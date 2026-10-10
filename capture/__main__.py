"""Capture every source in sources.yaml once: uv run python -m capture [--only ID]

Environment:
    STORAGE                    "local" (default, ./data) or "blob"
    AZURE_STORAGE_ACCOUNT_URL  blob only, e.g. https://<account>.blob.core.windows.net
    AZURE_STORAGE_CONTAINER    blob only
    HC_PING_URL                optional heartbeat; /fail is appended if any source failed
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
                               optional; one message when any source failed
"""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from capture.http import fetch
from capture.notify import ping_heartbeat, send_telegram
from capture.run import run
from capture.storage import BlobStorage, LocalStorage


def make_storage(env, parser):
    kind = env.get("STORAGE", "local")
    if kind == "local":
        return LocalStorage(Path("data"))
    if kind == "blob":
        missing = [
            name
            for name in ("AZURE_STORAGE_ACCOUNT_URL", "AZURE_STORAGE_CONTAINER")
            if not env.get(name)
        ]
        if missing:
            parser.error("STORAGE=blob needs " + ", ".join(missing))
        return BlobStorage(
            env["AZURE_STORAGE_ACCOUNT_URL"], env["AZURE_STORAGE_CONTAINER"]
        )
    parser.error(f"STORAGE must be 'local' or 'blob', not {kind!r}")


def main():
    parser = argparse.ArgumentParser(prog="python -m capture")
    parser.add_argument("--only", metavar="SOURCE_ID", help="capture just this source")
    args = parser.parse_args()

    storage = make_storage(os.environ, parser)
    sources = yaml.safe_load(Path("sources.yaml").read_text())
    if args.only is not None:
        sources = [source for source in sources if source["id"] == args.only]
        if not sources:
            parser.error(f"no source with id {args.only!r} in sources.yaml")
    records = run(
        sources,
        fetch=fetch,
        storage=storage,
        now=datetime.now(UTC),
    )

    failed = [record["source"] for record in records if record["status"] == "failed"]
    print(f"captured {len(records) - len(failed)}/{len(records)} sources")
    if failed:
        print("failed: " + ", ".join(str(source_id) for source_id in failed))

    if os.environ.get("HC_PING_URL"):
        ping_heartbeat(os.environ["HC_PING_URL"], failed)
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        send_telegram(
            os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], failed
        )


if __name__ == "__main__":
    main()
