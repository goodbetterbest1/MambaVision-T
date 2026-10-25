"""Export/import helpers shared by HTTP API and command line tools."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable

from .schema import SCHEMA_VERSION, summarize_evidence, utc_now, validate_export


def export_payload(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = list(cases)
    return {"schema_version": SCHEMA_VERSION, "exported_at": utc_now(), "cases": ordered}


def export_json(cases: Iterable[dict[str, Any]]) -> bytes:
    return (json.dumps(export_payload(cases), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def export_jsonl(cases: Iterable[dict[str, Any]]) -> bytes:
    return ("".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases)).encode("utf-8")


def export_evidence_jsonl(cases: Iterable[dict[str, Any]]) -> bytes:
    return ("".join(json.dumps(summarize_evidence(case), ensure_ascii=False, sort_keys=True) + "\n" for case in cases)).encode("utf-8")


def export_csv(cases: Iterable[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    fields = [
        "image_id", "filename", "width", "height", "image_quality", "case_grade", "review_status",
        "annotator_id", "upper_crest_n", "lower_crest_n", "upper_crest_segments", "lower_crest_segments", "severity_point_count", "severity_counts",
        "explanation_sample", "notes", "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for case in cases:
        counts = {}
        for point in case.get("severity_points", []):
            counts[point.get("severity", "uncertain")] = counts.get(point.get("severity", "uncertain"), 0) + 1
        writer.writerow({
            "image_id": case.get("image_id", ""), "filename": case.get("filename", ""),
            "width": case.get("width", ""), "height": case.get("height", ""),
            "image_quality": case.get("image_quality", ""), "case_grade": case.get("case_grade", ""),
            "review_status": case.get("review_status", ""), "annotator_id": case.get("annotator_id", ""),
            "upper_crest_n": sum(len(segment) for segment in case.get("upper_crest_segments", [])),
            "lower_crest_n": sum(len(segment) for segment in case.get("lower_crest_segments", [])),
            "upper_crest_segments": len(case.get("upper_crest_segments", [])),
            "lower_crest_segments": len(case.get("lower_crest_segments", [])),
            "severity_point_count": len(case.get("severity_points", [])),
            "severity_counts": json.dumps(counts, ensure_ascii=False, sort_keys=True),
            "explanation_sample": json.dumps(case.get("explanation_sample", {}), ensure_ascii=False),
            "notes": case.get("notes", ""), "updated_at": case.get("updated_at", ""),
        })
    return output.getvalue().encode("utf-8-sig")


def parse_import(text: str) -> list[dict[str, Any]]:
    value: Any = json.loads(text)
    if isinstance(value, dict) and "cases" in value:
        return validate_export(value)["cases"]
    if isinstance(value, list):
        return validate_export({"cases": value})["cases"]
    raise ValueError("import file must be an export object or a case array")
