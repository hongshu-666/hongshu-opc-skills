#!/usr/bin/env python3
"""Update only the explicitly selected source Markdown table after verified intake."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_common import same_work, work_identity as identity


def cells(line):
    text = line.rstrip("\r\n")
    pieces = re.split(r"(?<!\\)\|", text)
    left, right = pieces[0].strip() == "", pieces[-1].strip() == ""
    return pieces, int(left), len(pieces) - int(right)


def table(lines):
    matches = []
    for i in range(len(lines) - 1):
        parts, start, end = cells(lines[i])
        labels = [s.strip() for s in parts[start:end]]
        sep, a, b = cells(lines[i + 1])
        if (
            len(labels) > 1
            and len(sep[a:b]) == len(labels)
            and all(re.fullmatch(r":?-{3,}:?", s.strip()) for s in sep[a:b])
        ):
            links = [j for j, s in enumerate(labels) if s in ("链接", "原文链接")]
            if links:
                matches.append((i, labels, links))
    if len(matches) != 1:
        raise ValueError("须有且只有一份含链接列的作品表；不猜选多个表")
    i, labels, links = matches[0]
    if len(links) != 1 or labels.count("录入状态") > 1:
        raise ValueError("链接列或状态列冲突")
    end = i + 2
    while end < len(lines) and "|" in lines[end] and lines[end].strip():
        p, a, b = cells(lines[end])
        if b - a != len(labels):
            raise ValueError("表行列数不一致，未修改")
        end += 1
    return i, end, labels, links[0]


def note_url(path):
    text = Path(path).read_text(encoding="utf-8")
    m = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", text, re.S)
    if not m or not m[2].strip():
        raise ValueError("成稿缺少属性或正文，不能标记")
    urls = re.findall(r"^原文链接:[ \t]*(.+)$", m[1], re.M)
    if len(urls) != 1:
        raise ValueError("成稿原文链接缺失或冲突")
    raw = urls[0].strip()
    return json.loads(raw) if raw.startswith('"') else raw.strip("'")


def update(path, source=None):
    original = path.read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    first, last, labels, link = table(lines)
    state = labels.index("录入状态") if "录入状态" in labels else None
    target = None
    if source is not None:
        parsed = urlsplit(source)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("成稿原文链接无效")
        found = []
        for i in range(first + 2, last):
            p, a, b = cells(lines[i])
            urls = re.findall(r"https?://[^\s<>\[\])]+", p[a + link])
            if any(same_work(url, source) for url in urls):
                if len(urls) != 1:
                    raise ValueError("目标行有多个链接，未猜配")
                found.append(i)
        if len(found) != 1:
            raise ValueError("目标作品未找到或身份重复，未修改")
        target = found[0]
    for i in range(first, last):
        p, a, b = cells(lines[i])
        row = p[a:b]
        status = (
            row.pop(state)
            if state is not None
            else (" 录入状态 " if i == first else " --- " if i == first + 1 else " ")
        )
        if i == target:
            if status.strip() not in ("", "已录入"):
                raise ValueError("目标行已有不同状态，未覆盖")
            status = " 已录入 "
        row.append(status)
        ending = "\r\n" if lines[i].endswith("\r\n") else "\n" if lines[i].endswith("\n") else ""
        lines[i] = "|".join(p[:a] + row + p[b:]) + ending
    result = "".join(lines).encode("utf-8")
    if result != original:
        if path.read_bytes() != original:
            raise RuntimeError("清单已被其他窗口修改，停止写入")
        with path.open("wb") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != result:
            raise RuntimeError("清单回读不一致")
    return {"status": "marked" if source else "initialized", "path": str(path), "changed": result != original}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "mark"))
    parser.add_argument("path", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--manifest", type=Path)
    group.add_argument("--verified-note", type=Path, help="仅在执行者已核实完整后使用；文件存在不代表完整")
    args = parser.parse_args()
    source = None
    if args.action == "mark":
        if args.manifest:
            data = json.loads(args.manifest.read_text(encoding="utf-8"))
            if data.get("status") != "saved":
                parser.error("仅接受保存回读成功的 saved 状态")
            source = note_url(data["output"])
            if not same_work(source, data["url"]):
                parser.error("manifest与成稿作品身份不一致")
        elif args.verified_note:
            source = note_url(args.verified_note)
        else:
            parser.error("mark需要saved manifest或明确已核完整稿")
    elif args.manifest or args.verified_note:
        parser.error("init不接受成稿参数")
    print(json.dumps(update(args.path.resolve(), source), ensure_ascii=False))
