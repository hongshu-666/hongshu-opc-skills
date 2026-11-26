#!/usr/bin/env python3
"""Recalculate topic statistics from complete source and classification CSVs.

Usage: python validate_outputs.py --source titles.csv --classification classification.csv
Source columns: id,title,likes. Classification columns: id,theme.
Use reliable nonnegative integer likes; retain every original source row.
This validates supplied rows and arithmetic, not source authenticity or themes.
"""

import argparse
import csv
import json
from pathlib import Path
from statistics import median


def read_rows(path: Path, fields: list[str]) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != fields:
            raise ValueError(f"{path}: expected columns {fields}")
        rows = list(reader)
    if not rows or any(len(row) != len(fields) for row in rows):
        raise ValueError(f"{path}: empty data or malformed row")
    return rows


def check_topic_statistics(source: Path, classification: Path) -> dict:
    likes = {}
    for raw_id, title, raw_likes in read_rows(source, ["id", "title", "likes"]):
        item_id, value = int(raw_id), int(raw_likes)
        if item_id <= 0 or item_id in likes or not title.strip() or value < 0:
            raise ValueError("source requires unique positive ids, titles and nonnegative integer likes")
        likes[item_id] = value
    rows = read_rows(classification, ["id", "theme"])
    ids = [int(row[0]) for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(likes):
        raise ValueError("classification must cover each source title exactly once")
    groups = {}
    for raw_id, theme in rows:
        theme = theme.strip()
        if not theme:
            raise ValueError("empty theme")
        groups.setdefault(theme, []).append(likes[int(raw_id)])
    return {name: {"count": len(values), "percent": round(len(values) / len(likes) * 100, 2), "median_likes": median(values)} for name, values in groups.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--classification", type=Path, required=True)
    args = parser.parse_args()
    result = check_topic_statistics(args.source, args.classification)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
