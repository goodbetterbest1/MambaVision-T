from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import AnnotationDB
from app.import_export import export_json, export_jsonl, parse_import
from app.schema import validate_case_payload, summarize_evidence
from app.server import AppState, make_server

# 2x1 transparent PNG; the server's header parser can read its dimensions without Pillow.
PNG_2X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAADUlEQVR42mNk+M/wHwAF/gL+4wXzGAAAAABJRU5ErkJggg==")


def get_json(url: str):
    with urllib.request.urlopen(url) as response:
        return response.status, json.loads(response.read().decode())


def request_json(url: str, method: str, value):
    body = json.dumps(value, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read().decode())


class SchemaAndDBTests(unittest.TestCase):
    def test_validation_and_evidence(self):
        case = validate_case_payload({
            "image_id": "abc", "filename": "a.png", "width": 2, "height": 1,
            "upper_crest_segments": [[[0.1, 0.2], [0.8, 0.25]], [[0.85, 0.25], [0.95, 0.3]]], "lower_crest_segments": [],
            "severity_points": [{"x": .5, "y": .6, "jaw": "upper", "severity": "severe"}],
        }, require_identity=True)
        self.assertEqual(case["severity_points"][0]["id"], "p0001")
        self.assertEqual(summarize_evidence(case)["severity_counts"]["severe"], 1)
        self.assertEqual(summarize_evidence(case)["crest_lines"]["upper"]["n_segments"], 2)
        with self.assertRaises(ValueError):
            validate_case_payload({**case, "upper_crest_segments": [[[1.2, 0.1], [0.9, 0.2]]]}, require_identity=True)

    def test_sqlite_revisions_and_import_export(self):
        with TemporaryDirectory() as directory:
            db = AnnotationDB(Path(directory) / "a.sqlite3")
            case = validate_case_payload({"image_id": "abc", "filename": "a.png", "width": 2, "height": 1}, require_identity=True)
            saved = db.save(case)
            saved2 = db.save({**saved, "case_grade": "moderate"})
            self.assertEqual(saved2["annotation_version"], 2)
            self.assertEqual(len(db.list()), 1)
            exported = export_json(db.list())
            self.assertEqual(len(parse_import(exported.decode())), 1)
            self.assertEqual(len(export_jsonl(db.list()).splitlines()), 1)
            db.close()


class HTTPTests(unittest.TestCase):
    def test_full_http_flow_and_path_guard(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "images" / "nested").mkdir(parents=True)
            (root / "images" / "nested" / "case.png").write_bytes(PNG_2X1)
            state = AppState(root / "images", root / "annotations.sqlite3")
            server = make_server("127.0.0.1", 0, state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, listing = get_json(base + "/api/images")
                self.assertEqual(status, 200)
                self.assertEqual(len(listing["images"]), 1)
                self.assertEqual(listing["storage"]["database_path"], str((root / "annotations.sqlite3").resolve()))
                self.assertEqual(listing["storage"]["json_directory"], str((root / "annotations_json").resolve()))
                image = listing["images"][0]
                self.assertEqual((image["width"], image["height"]), (2, 1))
                payload = {"annotator_id": "test", "upper_crest_segments": [[[.1, .2], [.8, .25]]], "severity_points": [{"x": .4, "y": .3, "jaw": "upper", "severity": "moderate", "confidence": "high"}], "case_grade": "moderate", "review_status": "complete"}
                status, saved = request_json(base + "/api/annotations/" + image["image_id"], "PUT", payload)
                self.assertEqual(status, 200)
                self.assertEqual(saved["case"]["annotation_version"], 1)
                self.assertEqual(saved["storage"]["snapshot_warning"], None)
                snapshot = root / "annotations_json" / f"{image['image_id']}.json"
                self.assertEqual(json.loads(snapshot.read_text())["case_grade"], "moderate")
                status, fetched = get_json(base + "/api/annotations/" + image["image_id"])
                self.assertEqual(fetched["case"]["case_grade"], "moderate")
                status, evidence = get_json(base + "/api/evidence/" + image["image_id"])
                self.assertEqual(evidence["evidence"]["severity_counts"]["moderate"], 1)
                with urllib.request.urlopen(base + "/api/export?format=json") as response:
                    exported = response.read()
                    self.assertIn(b"dent-alveolar-annotation-v2", exported)
                with urllib.request.urlopen(base + "/api/export?format=jsonl") as response:
                    self.assertEqual(len(response.read().splitlines()), 1)
                with urllib.request.urlopen(base + "/api/export?format=csv") as response:
                    self.assertIn(b"image_id", response.read())
                with urllib.request.urlopen(base + "/api/export?format=evidence") as response:
                    self.assertIn(b"dent-alveolar-evidence-v1", response.read())
                status, imported = request_json(base + "/api/import", "POST", {"payload": json.loads(exported.decode()), "strategy": "replace"})
                self.assertEqual((status, imported["imported"], imported["skipped_unknown"]), (200, 1, 0))
                status, fetched_after_import = get_json(base + "/api/annotations/" + image["image_id"])
                self.assertEqual(fetched_after_import["case"]["upper_crest_segments"], [[[0.1, 0.2], [0.8, 0.25]]])
                try:
                    urllib.request.urlopen(base + "/images/../annotations.sqlite3")
                    self.fail("path traversal should fail")
                except urllib.error.HTTPError as error:
                    self.assertEqual(error.code, 404)
            finally:
                server.shutdown(); server.server_close(); state.close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
