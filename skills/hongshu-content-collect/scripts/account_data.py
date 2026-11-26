#!/usr/bin/env python3
"""Local batches, checkpoints, and clean work-list export (Markdown/CSV); no browser/network."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_common import clean_topic_title

FIELDS = {"title": "title", "likes": "likes_display"}
PLATFORMS = {"douyin": "抖音", "bilibili": "B站", "xiaohongshu": "小红书"}


def raw(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path: Path, content: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != content:
        raise ValueError("readback mismatch; preserve file")
    return {"path": str(path), "bytes": len(content), "sha256": sha(content)}


def url_check(value: str, platform: str, identifier: str | None = None) -> None:
    part = urlsplit(str(value))
    host = (part.hostname or "").lower()
    domains = {"douyin": ("douyin.com",), "bilibili": ("bilibili.com", "b23.tv"), "xiaohongshu": ("xiaohongshu.com", "xhslink.com", "xhslink.cn")}[platform]
    if part.scheme not in ("http", "https") or not any(host == x or host.endswith("." + x) for x in domains) or host == "creator.douyin.com":
        raise ValueError("normal platform URL required")
    if identifier:
        pattern = {
            "douyin": r"/(?:video|note)/" + re.escape(identifier) + r"/?",
            "bilibili": r"/video/" + re.escape(identifier) + r"/?",
            "xiaohongshu": r"/(?:explore|discovery/item|user/profile/[0-9a-fA-F]{24})/" + re.escape(identifier) + r"/?",
        }[platform]
        if not re.fullmatch(pattern, part.path, flags=re.I if platform == "xiaohongshu" else 0):
            raise ValueError("work URL path/ID mismatch")


def date(row: dict, normalized: bool = True) -> str:
    value = str(row.get("published_display") or row.get("date_display") or "").strip()
    kind = row.get("date_kind")
    if not value or kind not in ("published", "edited") or (kind == "published" and re.search("编辑|更新", value)):
        return ""
    if not normalized:
        return value
    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", value)
    if not match:
        return ""
    try:
        return dt.date(*map(int, match.groups())).isoformat()
    except ValueError:
        return ""


def likes(value) -> tuple[float | None, bool]:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万亿kKwW]?)", str(value if value is not None else "").replace(",", "").strip())
    if not match:
        return (None, False)
    scale = {"": 1, "万": 10000, "亿": 100000000, "k": 1000, "w": 10000}[match[2].lower()]
    return (float(match[1]) * scale, bool(match[2]))


def merge(old: dict, update: dict) -> dict:
    row = {**old, **update}
    for key in ("evidence", "notes"):
        incoming = update.get(key, {})
        if key == "notes" and isinstance(incoming, str):
            incoming = {"general": incoming} if incoming.strip() else {}
        row[key] = {**old.get(key, {}), **incoming}
    if update.get("date_display") and not update.get("published_display"):
        row["published_display"] = update["date_display"]
    if old.get("date_kind") == "published" and date(old) and (update.get("date_kind") != "published" or not date(update)):
        row["published_display"], row["date_kind"] = old["published_display"], old["date_kind"]
        if old.get("evidence", {}).get("published"):
            row["evidence"]["published"] = old["evidence"]["published"]
    return row


def validate(row: dict, platform: str) -> None:
    pattern = {"douyin": r"\d{15,22}", "bilibili": r"BV[A-Za-z0-9]{10}", "xiaohongshu": r"[0-9a-fA-F]{24}"}[platform]
    if not re.fullmatch(pattern, str(row["id"])):
        raise ValueError("invalid platform work ID")
    url_check(row["url"], platform, str(row["id"]))


def view(directory: Path) -> tuple[dict, dict, dict, list, list]:
    meta, rows, profile, batches, invalid = load(directory / "run.json"), {}, {}, [], []
    for path in sorted((directory / "batches").glob("*.json")):
        try:
            saved = load(path)
            payload = saved["payload"]
            if (saved.get("payload_sha256") and sha(raw(payload)) != saved["payload_sha256"]) or not isinstance(payload["source"], dict):
                raise ValueError("invalid batch")
            pending = dict(rows)
            for item in payload.get("records", []):
                row = merge(pending.get(str(item["id"]), {}), item)
                validate(row, meta["platform"])
                pending[str(item["id"])] = row
            updated_profile = {**profile, **payload.get("profile", {})}
            rows, profile = pending, updated_profile
            batches.append((path, saved))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            invalid.append({"path": str(path), "error": str(exc)})
    return meta, rows, profile, batches, invalid


def stamp(value):
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(dt.timezone.utc) if result.utcoffset() is not None else None
    except ValueError:
        return None


def times(batches: list) -> list[dict]:
    result = []
    for path, saved in batches:
        source = saved["payload"]["source"]
        observed, stored = stamp(source.get("observed_at")), stamp(saved.get("saved_at"))
        state = (
            "unknown" if source.get("observed_at") in (None, "", "未知", "unknown")
            else "invalid" if not observed or not stored
            else "after_save" if observed > stored
            else "host_clock_reported" if source.get("observed_at_source") == "host_clock"
            else "unverified"
        )
        result.append({"batch": path.name, "observed_at_raw": source.get("observed_at"), "saved_at": saved.get("saved_at"), "status": state})
    return result


def gaps(row: dict) -> list[str]:
    return [key for key, bad in (("title", not row.get("title")), ("likes", likes(row.get("likes_display"))[0] is None)) if bad]


def has_published_date(row: dict) -> bool:
    return row.get("date_kind") == "published" and bool(date(row))


def likes_key(row: dict) -> tuple[int, float]:
    val = likes(row.get("likes_display"))[0]
    return (1, val) if val is not None else (0, 0.0)


def ordered(rows) -> list[dict]:
    rows = list(rows)
    if any(not has_published_date(r) for r in rows):
        return rows
    groups: dict[str, list[dict]] = {}
    for row in sorted(rows, key=date, reverse=True):
        groups.setdefault(date(row), []).append(row)
    result = []
    for day, group in groups.items():
        clocks = [re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)", str(r.get("published_display") or "")) for r in group]
        try:
            if day and all(clocks):
                group = [r for _t, r in sorted(zip([dt.time(*map(int, (m[1] + ":0").split(":")[:3])) for m in clocks], group), key=lambda pair: pair[0], reverse=True)]
        except ValueError:
            pass
        result.extend(group)
    return result


def choose(meta: dict, rows: dict, explicit: list[str] | None, sort_mode: str = "order", select_mode: str | None = None) -> list[dict]:
    count = meta.get("count")
    if meta.get("since") or meta.get("until"):
        if any(not has_published_date(r) for r in rows.values()):
            raise ValueError("publication dates required to select time range")
        rows = {k: r for k, r in rows.items() if (not meta.get("since") or date(r) >= meta["since"]) and (not meta.get("until") or date(r) <= meta["until"])}
    if explicit is not None:
        if select_mode is not None:
            raise ValueError("cannot combine selected_ids with select mode")
        if len(explicit) != len(set(explicit)) or any(x not in rows for x in explicit) or (count and len(explicit) > count):
            raise ValueError("selected_ids duplicate, unknown or over count")
        chosen = [rows[x] for x in explicit]
    else:
        items = list(rows.values())
        mode = select_mode or sort_mode
        if mode == "likes":
            if count and len(items) > count and any(likes(r.get("likes_display"))[0] is None for r in items):
                raise ValueError("candidate likes unproven: confirm the ranking or explicitly select verified IDs")
            chosen = sorted(ordered(items), key=likes_key, reverse=True)[:count]
        elif mode == "order":
            chosen = items[:count]
        else:
            if any(not has_published_date(r) for r in items):
                raise ValueError("candidate publication dates unproven: use --select order or provide evidence-based selected_ids")
            chosen = ordered(items)[:count]
    if sort_mode == "likes":
        return sorted(ordered(chosen), key=likes_key, reverse=True)
    if sort_mode == "date":
        if any(not has_published_date(r) for r in chosen):
            raise ValueError("selected publication dates unproven for date sort: use --sort order or --sort likes")
        return ordered(chosen)
    return chosen


def summary(meta: dict, rows: dict, config: dict, sort_mode: str = "order", select_mode: str | None = None) -> dict:
    effective_sort = config.get("sort") or sort_mode
    effective_select = config.get("select") or select_mode
    selected = choose(meta, rows, config.get("selected_ids"), sort_mode=effective_sort, select_mode=effective_select)
    if any(not r.get("title_reviewed") for r in selected):
        raise ValueError("read every final topic against its source before marking title_reviewed=true")
    return {"selected": len(selected), "selected_records": selected, "selected_field_complete": sum(not gaps(r) for r in selected)}


def md_cell(value) -> str:
    return str(value if value is not None and value != "" else "未知").replace("|", "\\|").replace("\n", " ")


def render_list(meta: dict, profile: dict, result: dict, config: dict, fmt: str = "md", with_date: bool = False, clean_titles: bool = False) -> tuple[bytes, list[dict]]:
    rows = result["selected_records"]
    default_fields = ["序号", "选题"]
    if with_date:
        default_fields.append("日期")
    if any(likes(row.get("likes_display"))[0] is not None for row in rows):
        default_fields.append("点赞数")
    fields = config.get("works_fields") or [*default_fields, "链接"]
    title_warnings, prepared_rows = [], []
    for i, row in enumerate(rows, 1):
        raw_title = str(row.get("title") or "未知")
        cleaned = clean_topic_title(raw_title)
        display_title = cleaned if (clean_titles and cleaned) else raw_title
        if not clean_titles and cleaned and cleaned != raw_title:
            title_warnings.append({"id": row["id"], "raw": raw_title, "suggested": cleaned})
        source = "〔生成〕" if row.get("title_generated") else ""
        display_date = date(row, False) or "未知"
        cells = {
            "序号": str(i), "选题": display_title + source,
            "日期": display_date, "发布日期": display_date if row.get("date_kind") == "published" else "未知",
            "点赞数": str(row.get("likes_display") if row.get("likes_display") not in (None, "") else "未知"),
            "链接": row["url"] if fmt == "csv" else f'[链接](<{row["url"]}>)',
        }
        prepared_rows.append({f: str(cells.get(f, row.get(f, "未知"))) for f in fields})

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(prepared_rows)
        return buf.getvalue().encode("utf-8"), title_warnings

    lines = []
    if profile:
        lines.extend(["## 账号基础信息", "", *(f"- {k}：{v}" for k, v in profile.items()), ""])
    lines.extend(["## 作品清单", "", "|" + "|".join(map(md_cell, fields)) + "|", "|" + "|".join("---" for _ in fields) + "|"])
    lines.extend("|" + "|".join(md_cell(item[f]) for f in fields) + "|" for item in prepared_rows)
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8"), title_warnings


def _list_index_path() -> Path:
    return Path.home() / ".cache/reach-tools/work/list-index.json"


def _record_list_index(list_path: Path, work_dir: Path, meta: dict, exported_ids: list[str] | None = None) -> None:
    try:
        idx_path = _list_index_path()
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
        data[str(list_path.resolve())] = {
            "work_dir": str(work_dir.resolve()),
            "platform": meta.get("platform", ""),
            "homepage": meta.get("homepage", ""),
            **({"exported_ids": exported_ids} if exported_ids is not None else {}),
            "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        idx_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _extract_list_entries(list_path: Path, platform: str) -> list[tuple[str, str]]:
    """Parse exact ordered (work_id, url) entries from a Markdown (or CSV) list file."""
    path = list_path.resolve()
    if not path.is_file():
        raise ValueError(f"指定的清单文件不存在：{path}")
    id_re = {
        "douyin": re.compile(r"/(?:video|note)/(\d{15,22})(?:[/?#]|$)"),
        "bilibili": re.compile(r"/video/(BV[A-Za-z0-9]{10})(?:[/?#]|$)"),
        "xiaohongshu": re.compile(r"/(?:explore|discovery/item|user/profile/[0-9a-fA-F]{24})/([0-9a-fA-F]{24})(?:[/?#]|$)"),
    }[platform]
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                url = str(row.get("链接") or row.get("原文链接") or "").strip()
                m = id_re.search(url)
                if m and m.group(1) not in seen:
                    seen.add(m.group(1))
                    entries.append((m.group(1), url))
        return entries
    import sys
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import source_list
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    first, last, _labels, link_col = source_list.table(lines)
    for i in range(first + 2, last):
        parts, a, _b = source_list.cells(lines[i])
        urls = re.findall(r"https?://[^\s<>\[\])]+", parts[a + link_col])
        for url in urls:
            m = id_re.search(url)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                entries.append((m.group(1), url))
                break
    return entries


def _lookup_list_work_dir(list_path: Path) -> Path:
    idx_path = _list_index_path()
    if idx_path.is_file():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            entry = data.get(str(list_path.resolve())) if isinstance(data, dict) else None
            if isinstance(entry, dict) and entry.get("work_dir"):
                wd = Path(entry["work_dir"]).resolve()
                if (wd / "run.json").is_file():
                    return wd
        except Exception:
            pass
    if (list_path.resolve().parent / "run.json").is_file():
        return list_path.resolve().parent
    raise ValueError("未找到该清单对应的过程缓存目录，请显式传入 --dir")


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "save", "status", "export", "write-report"))
    parser.add_argument("--dir")
    for option in ("homepage", "input", "config", "output", "for-list"):
        parser.add_argument("--" + option)
    parser.add_argument("--count", type=int)
    parser.add_argument("--platform", choices=tuple(PLATFORMS))
    parser.add_argument("--task", choices=("list",), default="list")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--format", choices=("md", "csv"), default="md")
    parser.add_argument("--select", choices=("date", "likes", "order"))
    parser.add_argument("--sort", choices=("likes", "date", "order"), default="order")
    parser.add_argument("--with-date", action="store_true")
    parser.add_argument("--clean-titles", action="store_true")
    parser.add_argument("--records", action="store_true")
    args = parser.parse_args()
    if args.dir:
        directory = Path(args.dir).expanduser().resolve()
    elif args.for_list:
        directory = _lookup_list_work_dir(Path(args.for_list).expanduser())
    else:
        raise ValueError("请提供 --dir（或用 --for-list 指定已导出的清单路径）")

    if args.command == "write-report":
        content = Path(args.input).read_bytes()
        if not content.decode("utf-8").strip():
            raise ValueError("nonempty UTF-8 report required")
        path = Path(args.output).resolve()
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("report exists with different content; choose a new name")
            return {"path": str(path), "bytes": len(content), "sha256": sha(content), "already_saved": True}
        return write_new(path, content)

    if args.command == "init":
        if not args.platform:
            raise ValueError("--platform required for init")
        url_check(args.homepage, args.platform)
        if args.count is not None and args.count < 1:
            raise ValueError("positive count required")
        for bound in (args.since, args.until):
            if bound:
                dt.date.fromisoformat(bound)
        if args.since and args.until and args.since > args.until:
            raise ValueError("since follows until")
        meta = {"platform": args.platform, "task": "list", "homepage": args.homepage, "count": args.count, "since": args.since, "until": args.until, "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        path = directory / "run.json"
        if path.exists():
            if any(load(path).get(k) != meta[k] for k in ("platform", "homepage", "count", "since", "until")):
                raise ValueError("existing run differs; use a fresh authorized directory")
            return {"path": str(path), "already_initialized": True}
        return write_new(path, raw(meta))

    meta, rows, profile, batches, invalid = view(directory)
    if args.command == "save":
        payload = load(args.input)
        source, records = payload.get("source", {}), payload.get("records", [])
        if not isinstance(records, list) or (not records and not payload.get("profile")) or not all(source.get(k) for k in ("url", "column", "evidence")) or "observed_at" not in source:
            raise ValueError("source metadata and records/profile required")
        url_check(source["url"], meta["platform"])
        if any(b["payload"] == payload for _p, b in batches):
            return {"already_saved": True, "durable_unique": len(rows)}
        proposed = dict(rows)
        for item in records:
            identifier = str(item["id"])
            proposed[identifier] = merge(proposed.get(identifier, {}), item)
            validate(proposed[identifier], meta["platform"])
        merged_profile = {**profile, **payload.get("profile", {})}
        saved_at = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        saved = {"saved_at": saved_at, "payload_sha256": sha(raw(payload)), "payload": payload}
        path = directory / "batches" / (saved_at + ".json")
        receipt = write_new(path, raw(saved))
        actual = view(directory)
        if actual[1] != proposed or actual[2] != merged_profile:
            raise ValueError("merged readback mismatch; preserve files")
        return {**receipt, "added_unique": len(proposed) - len(rows), "durable_unique": len(actual[1]), "source_times": times([(path, saved)])}

    unresolved = []
    for identifier, row in rows.items():
        missing = gaps(row)
        if missing:
            notes = row.get("notes", {})
            unresolved.append({"id": identifier, "unread": [k for k in missing if not row.get(FIELDS[k]) and not notes.get(k)], "attempted_gaps": {k: notes.get(k) or "已读值不完整／不能解析" for k in missing if row.get(FIELDS[k]) or notes.get(k)}})
    result: dict = {"durable_unique": len(rows), "field_complete": sum(not gaps(r) for r in rows.values()), "profile": profile, "unresolved": unresolved, "invalid_batches": invalid}

    if args.command == "export":
        if invalid:
            raise ValueError("invalid saved batches: inspect status before producing results")
        config = load(args.config) if args.config else {}
        result.update(summary(meta, rows, config, sort_mode=args.sort, select_mode=args.select))
        if not args.output:
            raise ValueError("--output explicit destination required")
        content, title_warnings = render_list(meta, profile, result, config, fmt=args.format, with_date=args.with_date, clean_titles=args.clean_titles)
        path = Path(args.output).resolve()
        if path.exists() and path.read_bytes() == content:
            result["report"] = {"path": str(path), "already_saved": True, "sha256": sha(content)}
        else:
            result["report"] = write_new(path, content)
        _record_list_index(path, directory, meta, exported_ids=[str(r["id"]) for r in result.get("selected_records", [])])
        result["work_dir"] = str(directory)
        result["title_warnings"] = title_warnings
        result["source_times"] = times(batches)
    else:
        result.update(requested_count=meta.get("count"), work_dir=str(directory), source_times=times(batches))
        if args.for_list:
            list_file = Path(args.for_list).expanduser().resolve()
            entries = _extract_list_entries(list_file, meta["platform"])
            scoped_rows = [rows[wid] if wid in rows else {"id": wid, "url": u, "notes": {"cache": "清单该项未在当前缓存批次命中"}} for wid, u in entries]
            scoped_ids = {wid for wid, _u in entries}
            result["list_path"] = str(list_file)
            result["list_count"] = len(scoped_rows)
            result["unresolved"] = [u for u in unresolved if u["id"] in scoped_ids]
            if args.records:
                result["records"] = scoped_rows
        elif args.records:
            result["records"] = list(rows.values())
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as error:
        raise SystemExit(str(error))
