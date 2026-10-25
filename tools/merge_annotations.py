#!/usr/bin/env python3
"""Merge independent annotator JSON/JSONL exports without overwriting source files.

The tool keeps every annotator case and writes a deterministic consensus template.
It does not make clinical decisions or average polylines automatically.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    return value.get("cases", []) if isinstance(value, dict) else value


def read_all(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        for case in load_file(path):
            image_id = str(case.get("image_id", ""))
            if not image_id:
                raise ValueError(f"missing image_id in {path}")
            case = dict(case)
            case["_source_file"] = str(path)
            case["_annotator"] = case.get("annotator_id") or path.stem
            grouped[image_id].append(case)
    return dict(grouped)


def majority(values: list[str], default: str = "unreviewed") -> str:
    if not values:
        return default
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    top = max(counts.values())
    winners = [value for value, count in counts.items() if count == top]
    return winners[0] if len(winners) == 1 else "requires_review"


def make_consensus(image_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    first = cases[0]
    return {
        "image_id": image_id,
        "filename": first.get("filename", ""),
        "width": first.get("width", 1),
        "height": first.get("height", 1),
        "annotator_count": len({case.get("_annotator", "") for case in cases}),
        "source_record_count": len(cases),
        "duplicate_annotator_exports": len({case.get("_annotator", "") for case in cases}) != len(cases),
        "annotators": [case.get("_annotator", "") for case in cases],
        "agreement_template": {
            "image_quality_majority": ("requires_review" if len({case.get("_annotator", "") for case in cases}) != len(cases) else majority([case.get("image_quality", "unknown") for case in cases], "unknown")),
            "case_grade_majority": ("requires_review" if len({case.get("_annotator", "") for case in cases}) != len(cases) else majority([case.get("case_grade", "unreviewed") for case in cases], "unreviewed")),
            "review_statuses": [case.get("review_status", "in_progress") for case in cases],
            "upper_crest_segment_counts": [len(case.get("upper_crest_segments", [])) for case in cases],
            "lower_crest_segment_counts": [len(case.get("lower_crest_segments", [])) for case in cases],
            "upper_crest_point_counts": [sum(len(segment) for segment in case.get("upper_crest_segments", [])) for case in cases],
            "lower_crest_point_counts": [sum(len(segment) for segment in case.get("lower_crest_segments", [])) for case in cases],
            "severity_point_counts": [len(case.get("severity_points", [])) for case in cases],
        },
        "requires_expert_adjudication": len(cases) > 1,
        "source_cases": cases,
        "note": "This is an agreement template only. Review the source lines and points before using it as training ground truth.",
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_summary(path: Path, groups: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["image_id", "filename", "annotator_count", "annotators", "majority_grade", "majority_quality", "requires_expert_adjudication"])
        writer.writeheader()
        for image_id, cases in sorted(groups.items()):
            consensus = make_consensus(image_id, cases)
            agreement = consensus["agreement_template"]
            writer.writerow({
                "image_id": image_id, "filename": consensus["filename"], "annotator_count": consensus["annotator_count"],
                "annotators": ";".join(consensus["annotators"]), "majority_grade": agreement["case_grade_majority"],
                "majority_quality": agreement["image_quality_majority"], "requires_expert_adjudication": consensus["requires_expert_adjudication"],
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge independent dental annotation exports")
    parser.add_argument("inputs", nargs="+", type=Path, help="JSON or JSONL exports")
    parser.add_argument("--out-dir", type=Path, default=Path("exports/merged"))
    args = parser.parse_args()
    groups = read_all(args.inputs)
    all_cases = [case for image_cases in groups.values() for case in image_cases]
    # Strip private merge-only fields from the preserved original copies.
    original_cases = [{key: value for key, value in case.items() if not key.startswith("_")} for case in all_cases]
    consensus = [make_consensus(image_id, cases) for image_id, cases in sorted(groups.items())]
    write_jsonl(args.out_dir / "all_annotator_cases.jsonl", original_cases)
    write_jsonl(args.out_dir / "consensus_review_queue.jsonl", consensus)
    write_summary(args.out_dir / "agreement_summary.csv", groups)
    print(f"cases={len(all_cases)} images={len(groups)} out={args.out_dir}")


if __name__ == "__main__":
    main()
