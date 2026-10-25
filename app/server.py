"""Dependency-free local HTTP server for annotation and review."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .db import AnnotationDB
from .import_export import export_csv, export_evidence_jsonl, export_json, export_jsonl, parse_import
from .schema import empty_case, summarize_evidence, validate_case_payload

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def image_dimensions(path: Path) -> tuple[int, int]:
    # Prefer Pillow if it is installed, but do not require it for distribution.
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        pass
    try:
        with path.open("rb") as handle:
            header = handle.read(64 * 1024)
        if header.startswith(b"\x89PNG") and len(header) >= 24:
            return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        if header.startswith(b"GIF") and len(header) >= 10:
            return int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little")
        if header.startswith(b"BM") and len(header) >= 26:
            return abs(int.from_bytes(header[18:22], "little", signed=True)), abs(int.from_bytes(header[22:26], "little", signed=True))
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            kind = header[12:16]
            if kind == b"VP8X" and len(header) >= 30:
                return int.from_bytes(header[24:27], "little") + 1, int.from_bytes(header[27:30], "little") + 1
            if kind == b"VP8 " and header[23:26] == b"\x9d\x01\x2a":
                return int.from_bytes(header[26:28], "little") & 0x3fff, int.from_bytes(header[28:30], "little") & 0x3fff
            if kind == b"VP8L" and len(header) >= 25 and header[20] == 0x2f:
                bits = int.from_bytes(header[21:25], "little")
                return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        if header.startswith(b"\xff\xd8"):
            data = header
            index = 2
            while index + 9 < len(data):
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                index += 2
                if marker in (0xD8, 0xD9):
                    continue
                if index + 2 > len(data):
                    break
                length = int.from_bytes(data[index:index + 2], "big")
                if marker in range(0xC0, 0xC4) or marker in range(0xC5, 0xC8) or marker in range(0xC9, 0xCC) or marker in range(0xCD, 0xD0):
                    if index + 7 <= len(data):
                        return int.from_bytes(data[index + 5:index + 7], "big"), int.from_bytes(data[index + 3:index + 5], "big")
                index += max(length, 2)
    except Exception:
        pass
    raise ValueError("Cannot read image dimensions: " + path.name + "; use PNG/JPEG or install Pillow")


def stable_image_id(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    # Include the relative path so byte-identical files in different dataset folders remain distinct.
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    content_hash = digest.hexdigest()
    return hashlib.sha256((relative + "\0" + content_hash).encode("utf-8")).hexdigest()[:20]


class AppState:
    def __init__(self, data_dir: str | Path, db_path: str | Path, coco_path: str | Path | None = None, autosave_delay_ms: int = 750, undo_depth: int = 100):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = AnnotationDB(db_path)
        self.coco_path = self._resolve_coco_path(coco_path)
        self.autosave_delay_ms = max(100, min(int(autosave_delay_ms), 10000))
        self.undo_depth = max(1, min(int(undo_depth), 500))
        self.lock = threading.RLock()
        self._images: list[dict[str, Any]] | None = None
        self.image_errors: list[dict[str, str]] = []
        self._public_polygons: dict[str, list[dict[str, Any]]] | None = None
        self._public_polygon_stats: dict[str, Any] = {"images": 0, "annotations": 0, "matched_images": 0, "unmatched_annotations": 0}

    def _resolve_coco_path(self, coco_path: str | Path | None) -> Path | None:
        if coco_path:
            candidate = Path(coco_path).expanduser().resolve()
            return candidate if candidate.is_file() else None
        for candidate in (
            self.data_dir.parent / "imports" / "via_export_coco_BL.json",
            self.data_dir.parent / "imports" / "via_export_coco_BL.jsonl",
            self.data_dir / "via_export_coco_BL.json",
        ):
            candidate = candidate.resolve()
            if candidate.is_file():
                return candidate
        return None

    def close(self) -> None:
        self.db.close()

    def images(self) -> list[dict[str, Any]]:
        with self.lock:
            if self._images is not None:
                return self._images
            rows = []
            self.image_errors = []
            for path in sorted(self.data_dir.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS or self.data_dir not in path.resolve().parents:
                    continue
                relative = path.relative_to(self.data_dir).as_posix()
                try:
                    width, height = image_dimensions(path)
                except ValueError as exc:
                    self.image_errors.append({"filename": relative, "error": str(exc)})
                    continue
                image_id = stable_image_id(path, self.data_dir)
                rows.append({
                    "image_id": image_id, "filename": relative, "width": width, "height": height,
                    "url": "/images/" + urllib.parse.quote(relative), "bytes": path.stat().st_size,
                })
            self._images = rows
            return rows

    def refresh_images(self) -> list[dict[str, Any]]:
        with self.lock:
            self._images = None
            return self.images()

    def image_by_id(self, image_id: str) -> dict[str, Any] | None:
        return next((item for item in self.images() if item["image_id"] == image_id), None)

    def path_for_filename(self, filename: str) -> Path:
        candidate = (self.data_dir / filename).resolve()
        if candidate != self.data_dir and self.data_dir not in candidate.parents:
            raise ValueError("invalid image path")
        if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            raise FileNotFoundError(filename)
        return candidate

    def public_polygons(self) -> dict[str, list[dict[str, Any]]]:
        if self._public_polygons is not None:
            return self._public_polygons
        result: dict[str, list[dict[str, Any]]] = {}
        self._public_polygon_stats = {"images": 0, "annotations": 0, "matched_images": 0, "unmatched_annotations": 0}
        if not self.coco_path or not self.coco_path.is_file():
            self._public_polygons = result
            return result
        try:
            value = json.loads(self.coco_path.read_text(encoding="utf-8"))
            images = {int(item["id"]): item for item in value.get("images", [])}
            self._public_polygon_stats["images"] = len(images)
            categories = {int(item["id"]): item.get("name", "unknown") for item in value.get("categories", [])}
            known_names = {self._normalize_filename(item["filename"]): item for item in self.images()}
            basename_names: dict[str, dict[str, Any]] = {}
            for item in self.images():
                basename_names.setdefault(Path(item["filename"]).name.casefold(), item)
            matched_keys: set[str] = set()
            for annotation in value.get("annotations", []):
                self._public_polygon_stats["annotations"] += 1
                image = images.get(int(annotation.get("image_id")))
                if not image:
                    continue
                source_name = self._normalize_filename(image.get("file_name", ""))
                local_image = known_names.get(source_name)
                if local_image is None:
                    local_image = basename_names.get(Path(source_name).name.casefold())
                if local_image is None:
                    self._public_polygon_stats["unmatched_annotations"] += 1
                    continue
                key = local_image["filename"]
                matched_keys.add(key)
                result.setdefault(key, []).append({
                    "category": categories.get(int(annotation.get("category_id", -1)), "unknown"),
                    "segmentation": annotation.get("segmentation", []),
                    "bbox": annotation.get("bbox"),
                    "source_width": int(image.get("width") or 0),
                    "source_height": int(image.get("height") or 0),
                })
            self._public_polygon_stats["matched_images"] = len(matched_keys)
        except Exception:
            result = {}
        self._public_polygons = result
        return result

    def public_for_image(self, filename: str) -> list[dict[str, Any]]:
        return self.public_polygons().get(filename, [])

    @staticmethod
    def _normalize_filename(filename: Any) -> str:
        value = urllib.parse.unquote(str(filename or "")).replace("\\", "/")
        parts = [part for part in value.split("/") if part not in ("", ".")]
        return "/".join(parts).casefold()

    def public_status(self) -> dict[str, Any]:
        self.public_polygons()
        return {
            "loaded": bool(self.coco_path and self.coco_path.is_file()),
            "source": str(self.coco_path) if self.coco_path else None,
            **self._public_polygon_stats,
        }

    def annotation_config(self) -> dict[str, Any]:
        return {
            "autosave_delay_ms": self.autosave_delay_ms,
            "undo_depth": self.undo_depth,
            "undo_scope": "geometry_and_points",
            "save_backend": "sqlite_plus_case_json",
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "DentalAnnotation/1.0"

    @property
    def state(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep local usage quiet while retaining errors in the terminal.
        if self.path.startswith("/api") and self.command not in {"PUT", "POST"}:
            return
        super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: Any, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 25 * 1024 * 1024:
            raise ValueError("invalid request size")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8")) if body else {}

    def _trusted_request(self) -> bool:
        host = self.headers.get("Host", "")
        parsed = urllib.parse.urlsplit("http://" + host)
        allowed = {"127.0.0.1", "localhost", "::1", self.server.server_address[0]}
        if parsed.hostname not in allowed:
            self._error("untrusted Host", 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host, "https://" + host}:
            self._error("cross-origin requests are not allowed", 403)
            return False
        return True

    def do_GET(self) -> None:
        if not self._trusted_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._serve_static(path.removeprefix("/static/"))
            if path.startswith("/images/"):
                return self._serve_image(urllib.parse.unquote(path.removeprefix("/images/")))
            if path == "/api/config":
                return self._json({"schema_version": "dent-alveolar-annotation-v2", "data_dir": str(self.state.data_dir), "has_public_polygons": bool(self.state.coco_path), "public_polygons": self.state.public_status(), "annotation_config": self.state.annotation_config(), "storage": self.state.db.storage_info()})
            if path == "/api/images":
                records = []
                saved = {case["image_id"]: case for case in self.state.db.list()}
                for image in self.state.images():
                    case = saved.get(image["image_id"])
                    records.append({**image, "saved": bool(case), "review_status": case.get("review_status", "unreviewed") if case else "unreviewed", "case_grade": case.get("case_grade", "unreviewed") if case else "unreviewed"})
                return self._json({"images": records, "image_errors": self.state.image_errors, "public_polygons": self.state.public_status(), "annotation_config": self.state.annotation_config(), "storage": self.state.db.storage_info()})
            match = re.fullmatch(r"/api/annotations/([^/]+)", path)
            if match:
                image_id = urllib.parse.unquote(match.group(1))
                image = self.state.image_by_id(image_id)
                if not image:
                    return self._error("image not found", 404)
                case = self.state.db.get(image_id) or empty_case(image)
                return self._json({"case": case, "public_polygons": self.state.public_for_image(image["filename"]), "public_status": self.state.public_status(), "annotation_config": self.state.annotation_config()})
            match = re.fullmatch(r"/api/evidence/([^/]+)", path)
            if match:
                image_id = urllib.parse.unquote(match.group(1))
                image = self.state.image_by_id(image_id)
                if not image:
                    return self._error("image not found", 404)
                case = self.state.db.get(image_id) or empty_case(image)
                return self._json({"evidence": summarize_evidence(case)})
            if path == "/api/export":
                fmt = urllib.parse.parse_qs(parsed.query).get("format", ["json"])[0]
                cases = self.state.db.list()
                if fmt == "json":
                    return self._download(export_json(cases), "annotations.json", "application/json; charset=utf-8")
                if fmt == "jsonl":
                    return self._download(export_jsonl(cases), "annotations.jsonl", "application/x-ndjson; charset=utf-8")
                if fmt == "evidence":
                    return self._download(export_evidence_jsonl(cases), "evidence.jsonl", "application/x-ndjson; charset=utf-8")
                if fmt == "csv":
                    return self._download(export_csv(cases), "annotations.csv", "text/csv; charset=utf-8")
                return self._error("unsupported export format", 400)
            return self._error("not found", 404)
        except (FileNotFoundError, ValueError):
            self._error("file not found", 404)
        except Exception as exc:
            self._error(str(exc), 500)

    def do_PUT(self) -> None:
        if not self._trusted_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        match = re.fullmatch(r"/api/annotations/([^/]+)", parsed.path)
        if not match:
            return self._error("not found", 404)
        try:
            image_id = urllib.parse.unquote(match.group(1))
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("case must be an object")
            image = self.state.image_by_id(image_id)
            if not image:
                return self._error("image not found", 404)
            payload = {**image, **payload, "image_id": image_id, "filename": image["filename"], "width": image["width"], "height": image["height"]}
            saved = self.state.db.save(validate_case_payload(payload, require_identity=True))
            self._json({"case": saved, "storage": self.state.db.storage_info(), "annotation_config": self.state.annotation_config()})
        except ValueError as exc:
            self._error(str(exc), 400)
        except Exception as exc:
            self._error(str(exc), 500)

    def do_POST(self) -> None:
        if not self._trusted_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/import":
                body = self._read_json()
                strategy = str(body.get("strategy", "keep_local")) if isinstance(body, dict) else "keep_local"
                text = json.dumps(body.get("payload"), ensure_ascii=False) if isinstance(body, dict) and "payload" in body else json.dumps(body, ensure_ascii=False)
                incoming = parse_import(text)
                known = {image["image_id"]: image for image in self.state.images()}
                matched = []
                skipped_unknown = []
                for case in incoming:
                    image = known.get(case["image_id"])
                    if not image:
                        skipped_unknown.append(case["image_id"])
                        continue
                    # Use the local file identity/shape as the source of truth; do not import a stale filename.
                    matched.append({**case, "filename": image["filename"], "width": image["width"], "height": image["height"]})
                result = self.state.db.import_cases(matched, strategy=strategy)
                result["storage"] = self.state.db.storage_info()
                result["annotation_config"] = self.state.annotation_config()
                result["skipped_unknown"] = len(skipped_unknown)
                result["unknown_image_ids"] = skipped_unknown[:20]
                return self._json(result)
            if parsed.path == "/api/refresh":
                return self._json({"images": self.state.refresh_images()})
            return self._error("not found", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except Exception as exc:
            self._error(str(exc), 500)

    def _download(self, body: bytes, filename: str, content_type: str) -> None:
        self._send(200, body, content_type, {"Content-Disposition": f'attachment; filename="{filename}"'})

    def _serve_static(self, name: str, content_type: str | None = None) -> None:
        root = Path(__file__).resolve().parent.parent / "web"
        target = (root / name).resolve()
        if target != root and root not in target.parents or not target.is_file():
            return self._error("not found", 404)
        content_type = content_type or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type)

    def _serve_image(self, filename: str) -> None:
        target = self.state.path_for_filename(filename)
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type, {"Cache-Control": "private, max-age=3600"})


def make_server(host: str, port: int, state: AppState) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.app_state = state  # type: ignore[attr-defined]
    return server


def serve(host: str, port: int, state: AppState) -> None:
    server = make_server(host, port, state)
    try:
        print(f"Dental annotation tool: http://{host}:{port}/")
        print(f"Image directory: {state.data_dir}")
        print(f"Autosave database: {state.db.path}")
        print(f"Automatic JSON mirror: {state.db.json_dir}")
        print("Keep this service running while annotating. No image/annotation upload is performed.")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()
