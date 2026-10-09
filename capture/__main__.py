"""Capture every source in sources.yaml once: uv run python -m capture [--only ID]"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

import yaml

from capture.http import fetch
from capture.run import run


def main():
    parser = argparse.ArgumentParser(prog="python -m capture")
    parser.add_argument("--only", metavar="SOURCE_ID", help="capture just this source")
    args = parser.parse_args()

    sources = yaml.safe_load(Path("sources.yaml").read_text())
    if args.only is not None:
        sources = [source for source in sources if source["id"] == args.only]
        if not sources:
            parser.error(f"no source with id {args.only!r} in sources.yaml")
    records = run(
        sources,
        fetch=fetch,
        out_dir=Path("data"),
        now=datetime.now(UTC),
        log_path=Path("data/capture.log"),
    )

    failed = [record["source"] for record in records if record["status"] == "failed"]
    print(f"captured {len(records) - len(failed)}/{len(records)} sources")
    if failed:
        print("failed: " + ", ".join(str(source_id) for source_id in failed))


if __name__ == "__main__":
    main()
