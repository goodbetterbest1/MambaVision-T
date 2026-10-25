"""Schema and validation helpers for the local dental annotation tool."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "dent-alveolar-annotation-v2"
SEVERITIES = ("none", "mild", "moderate", "severe", "uncertain", "ungradable")
QUALITY = ("good", "limited", "ungradable", "unknown")
CASE_GRADES = ("none", "mild", "moderate", "severe", "uncertain", "ungradable", "unreviewed")
REVIEW_STATUS = ("in_progress", "complete", "needs_review")
CONFIDENCE = ("high", "medium", "low", "unknown")
JAWS = ("upper", "lower", "unknown")
MODALITIES = ("panoramic", "periapical", "bitewing", "other", "unknown")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp01(value: Any) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError("coordinate must be between 0 and 1")
    return value


def point(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("point must be [x, y]")
    return [clamp01(value[0]), clamp01(value[1])]


def polyline(value: Any, name: str) -> list[list[float]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [point(item) for item in value]


def polyline_segments(value: Any, name: str) -> list[list[list[float]]]:
    """Validate multiple independent visible line segments for one jaw."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of polylines")
    segments = []
    for index, segment in enumerate(value):
        clean_segment = polyline(segment, f"{name}[{index}]")
        if len(clean_segment) < 2:
            raise ValueError(f"{name}[{index}] must contain at least two points")
        segments.append(clean_segment)
    return segments


def clean_text(value: Any, max_len: int = 4000) -> str:
    text = "" if value is None else str(value)
    return text[:max_len]


def validate_severity_point(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("severity point must be an object")
    severity = item.get("severity", "uncertain")
    jaw = item.get("jaw", "unknown")
    confidence = item.get("confidence", "unknown")
    if severity not in SEVERITIES:
        raise ValueError(f"invalid severity: {severity}")
    if jaw not in JAWS:
        raise ValueError(f"invalid jaw: {jaw}")
    if confidence not in CONFIDENCE:
        raise ValueError(f"invalid confidence: {confidence}")
    return {
        "id": clean_text(item.get("id") or "", 80),
        "x": clamp01(item.get("x", 0)),
        "y": clamp01(item.get("y", 0)),
        "jaw": jaw,
        "severity": severity,
        "confidence": confidence,
        "note": clean_text(item.get("note", "")),
    }


def validate_case_payload(payload: Any, *, require_identity: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("case must be an object")
    image_id = clean_text(payload.get("image_id"), 255)
    filename = clean_text(payload.get("filename"), 1000)
    if require_identity and (not image_id or not filename):
        raise ValueError("image_id and filename are required")
    width = int(payload.get("width", 1))
    height = int(payload.get("height", 1))
    if width < 1 or height < 1:
        raise ValueError("width and height must be positive")
    image_quality = payload.get("image_quality", "unknown")
    modality = payload.get("modality", "panoramic")
    case_grade = payload.get("case_grade", "unreviewed")
    review_status = payload.get("review_status", "in_progress")
    if modality not in MODALITIES:
        raise ValueError(f"invalid modality: {modality}")
    if image_quality not in QUALITY:
        raise ValueError(f"invalid image_quality: {image_quality}")
    if case_grade not in CASE_GRADES:
        raise ValueError(f"invalid case_grade: {case_grade}")
    if review_status not in REVIEW_STATUS:
        raise ValueError(f"invalid review_status: {review_status}")
    version = int(payload.get("annotation_version", 0))
    if version < 0:
        raise ValueError("annotation_version must not be negative")
    points = payload.get("severity_points") or []
    if not isinstance(points, list):
        raise ValueError("severity_points must be a list")
    clean_points = [validate_severity_point(item) for item in points]
    # Stable point ids make revisions and merges easier without requiring tooth numbering.
    for index, item in enumerate(clean_points, 1):
        if not item["id"]:
            item["id"] = f"p{index:04d}"
    explanation = payload.get("explanation_sample") or {}
    if not isinstance(explanation, dict):
        raise ValueError("explanation_sample must be an object")
    upper_raw = payload.get("upper_crest_segments")
    lower_raw = payload.get("lower_crest_segments")
    # Read the pre-v2 single-polyline field so an older local SQLite/export can be upgraded safely.
    if upper_raw is None and payload.get("upper_crest"):
        upper_raw = [payload.get("upper_crest")]
    if lower_raw is None and payload.get("lower_crest"):
        lower_raw = [payload.get("lower_crest")]
    return {
        "schema_version": SCHEMA_VERSION,
        "image_id": image_id,
        "filename": filename,
        "width": width,
        "height": height,
        "modality": modality,
        "image_quality": image_quality,
        "case_grade": case_grade,
        "review_status": review_status,
        "annotator_id": clean_text(payload.get("annotator_id", ""), 120),
        "annotation_version": version,
        "upper_crest_segments": polyline_segments(upper_raw or [], "upper_crest_segments"),
        "lower_crest_segments": polyline_segments(lower_raw or [], "lower_crest_segments"),
        "severity_points": clean_points,
        "notes": clean_text(payload.get("notes", "")),
        "explanation_sample": {
            "enabled": bool(explanation.get("enabled", False)),
            "finding": clean_text(explanation.get("finding", "")),
            "evidence": clean_text(explanation.get("evidence", "")),
            "desired_explanation": clean_text(explanation.get("desired_explanation", "")),
            "uncertainty": clean_text(explanation.get("uncertainty", "")),
            "review_status": clean_text(explanation.get("review_status", "pending"), 40),
        },
        "created_at": clean_text(payload.get("created_at", ""), 80) or utc_now(),
        "updated_at": clean_text(payload.get("updated_at", ""), 80) or utc_now(),
    }


def empty_case(image: dict[str, Any], annotator_id: str = "") -> dict[str, Any]:
    return validate_case_payload(
        {
            **image,
            "annotator_id": annotator_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
        require_identity=True,
    )


def validate_export(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("export must be an object")
    if payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version; use a v2 export")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("export.cases must be a list")
    return {
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "exported_at": payload.get("exported_at") or utc_now(),
        "cases": [validate_case_payload(case, require_identity=True) for case in cases],
    }


def summarize_evidence(case: dict[str, Any]) -> dict[str, Any]:
    """Create auditable, deterministic evidence for a future VLM prompt.

    This is not a diagnosis and it intentionally does not infer a clinical stage.
    """
    clean = validate_case_payload(case, require_identity=True)
    points = clean["severity_points"]
    counts = {severity: sum(p["severity"] == severity for p in points) for severity in SEVERITIES}

    def line_summary(segments: list[list[list[float]]]) -> dict[str, Any]:
        points = [point for segment in segments for point in segment]
        length = 0.0
        for segment in segments:
            for a, b in zip(segment, segment[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length += (dx * dx + dy * dy) ** 0.5
        return {
            "n_segments": len(segments),
            "n_points": len(points),
            "segments": [{"start": segment[0], "end": segment[-1], "n_points": len(segment)} for segment in segments],
            "mean_y": round(sum(p[1] for p in points) / len(points), 6) if points else None,
            "normalized_length": round(length, 6),
        }

    return {
        "schema_version": "dent-alveolar-evidence-v1",
        "image_id": clean["image_id"],
        "filename": clean["filename"],
        "modality": clean["modality"],
        "image_quality": clean["image_quality"],
        "case_grade": clean["case_grade"],
        "review_status": clean["review_status"],
        "annotator_id": clean["annotator_id"],
        "crest_lines": {"upper": line_summary(clean["upper_crest_segments"]), "lower": line_summary(clean["lower_crest_segments"])},
        "severity_point_count": len(points),
        "severity_counts": counts,
        "severity_points": points,
        "explanation_sample": clean["explanation_sample"],
        "limitations": [
            "坐标和等级来自人工标注或规则汇总，不等同于临床诊断。",
            "未提供 CEJ、根尖和比例测量时，不输出标准化 RBL 百分比。",
            "VLM 只能基于这些结构化证据生成可审计解释，不应输出隐藏推理过程。",
        ],
    }
