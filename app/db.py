"""SQLite persistence for one local annotator."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .schema import utc_now, validate_case_payload


class AnnotationDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                image_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                annotator_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS annotation_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                FOREIGN KEY(image_id) REFERENCES annotations(image_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_annotations_updated ON annotations(updated_at);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get(self, image_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT payload_json FROM annotations WHERE image_id = ?", (image_id,)).fetchone()
            return validate_case_payload(json.loads(row["payload_json"]), require_identity=True) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT payload_json FROM annotations ORDER BY filename COLLATE NOCASE").fetchall()
            return [validate_case_payload(json.loads(row["payload_json"]), require_identity=True) for row in rows]

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = validate_case_payload(payload, require_identity=True)
        with self.lock:
            current = self.get(case["image_id"])
            now = utc_now()
            case["created_at"] = (current or {}).get("created_at") or case.get("created_at") or now
            case["updated_at"] = now
            case["annotation_version"] = int((current or {}).get("annotation_version") or 0) + 1
            serialized = json.dumps(case, ensure_ascii=False, sort_keys=True)
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO annotations(image_id, filename, payload_json, version, annotator_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(image_id) DO UPDATE SET
                        filename=excluded.filename,
                        payload_json=excluded.payload_json,
                        version=excluded.version,
                        annotator_id=excluded.annotator_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        case["image_id"], case["filename"], serialized, case["annotation_version"],
                        case["annotator_id"], case["created_at"], case["updated_at"],
                    ),
                )
                self.conn.execute(
                    "INSERT INTO annotation_revisions(image_id, version, payload_json, saved_at) VALUES (?, ?, ?, ?)",
                    (case["image_id"], case["annotation_version"], serialized, now),
                )
        return case

    def import_cases(self, cases: list[dict[str, Any]], strategy: str = "replace") -> dict[str, int]:
        if strategy not in {"replace", "keep_local"}:
            raise ValueError("strategy must be replace or keep_local")
        # Validate the entire batch before changing any records.
        validated = [validate_case_payload(raw, require_identity=True) for raw in cases]
        imported = skipped = 0
        with self.lock:
            for case in validated:
                if strategy == "keep_local" and self.get(case["image_id"]):
                    skipped += 1
                    continue
                # Imported content becomes a new local revision; source files remain unchanged.
                self.save(case)
                imported += 1
        return {"imported": imported, "skipped": skipped}
