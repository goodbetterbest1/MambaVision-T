#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from app.server import AppState, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Local panoramic dental annotation web tool")
    root = Path(__file__).resolve().parent
    parser.add_argument("--data", default=str(root / "data/images"), help="directory containing local image files")
    parser.add_argument("--db", default=str(root / "annotations/annotator.sqlite3"), help="SQLite output path")
    parser.add_argument("--coco", default=None, help="optional COCO JSON for read-only public polygon overlay")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; keep 127.0.0.1 for private local use")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    state = AppState(args.data, args.db, args.coco)
    serve(args.host, args.port, state)


if __name__ == "__main__":
    main()
