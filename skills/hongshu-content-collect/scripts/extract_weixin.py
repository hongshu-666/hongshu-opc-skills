#!/usr/bin/env python3
"""Extract structured text from a saved WeChat MP article HTML page."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {"article", "blockquote", "div", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "table", "td", "th", "tr", "ul", "ol"}
CAPTURE_IDS = {"activity-name": "title", "js_name": "account", "js_author_name": "author", "publish_time": "published_at"}
BLOCKED_MARKERS = ("环境异常", "完成验证", "访问过于频繁", "请在微信客户端打开", "当前环境异常")
NOISE_LINE_PATTERNS = (
    re.compile(r"^(来源|本文来源)[:：]\s*.+$"),
    re.compile(r"^[（(]?(编辑|制作|审核|校对|责编|责任编辑|策划)[:：]\s*.+[）)]?$"),
    re.compile(r"^(点赞|赞|分享|在看|写留言|赞赏)$"),
    re.compile(r"^(关注公众号|长按识别二维码|扫码关注).*$"),
    re.compile(r"^.*(本文内容系原创|转载请注明来源|如需转载请).*$"),
)
KNOWN_FOOTER_PATTERNS = (
    re.compile(r"^这是.{1,20}公众号第\d+篇原创文章[。！!]?.*$"),
    re.compile(r"^品牌推广\s*\|.*转载开白\s*$"),
    re.compile(r"^请在公众号后台回复\s*合作\s*$"),
)
ERRATA_SIGNAL = re.compile(r"勘误|更正|笔误|订正|勘正")
TAIL_PROMO_ACTION_RE = re.compile(
    r"^亲爱的朋友[，,]\s*我有一个私域社群[“\"][^”\"]+[”\"]|"
    r"长按(?:识别|扫描|下方)?(?:二维码|海报|关注|报名|进群|加群|入群|购买|购票)|"
    r"扫码(?:关注|报名|加群|进群|入群|添加|购买|购票|领取|预约|上岛|加入)|"
    r"(?:点击|立即|欢迎|免费|私信|后台回复|文末|下方|开放|火热).{0,12}(?:报名|购票|购买|加群|进群|入群|上岛|加入社群|领取(?:资料|讲义)|报名(?:链接|通道|入口))|"
    r"(?:添加|加)(?:助教|小助手|客服|老师).{0,10}(?:微信|领取|进群|入群|报名|咨询)|"
    r"早鸟价|抢先购买|无理由退全款|欢迎上岛"
)
RELATED_ARTICLE_TAIL_PATTERN = re.compile(r"^更多(?:精彩)?内容(?:，|,)?(?:请)?(?:详见|参见|请见)\s*[:：]?\s*(.*)$")
BARE_RELATED_ARTICLE_TAIL_PATTERN = re.compile(r"^(?:详见|参见|请见)\s*[:：]?\s*.*(?:文章|专访|评论|报道).*《[^》]+》.*$")
ARTICLE_TITLE_PATTERN = re.compile(r"《[^》]+》")
AUTHOR_ROLE_PATTERN = re.compile(r"教授|研究员|主任|书记|所长|院长|主编|记者|评论员|作者")
INVALID_AUTHOR_PATTERNS = (re.compile(r"点这里关注"), re.compile(r"点击关注"), re.compile(r"关注[→》>]"), re.compile(r"微信扫一扫"))


class WeixinHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.fields: dict[str, list[str]] = {"title": [], "account": [], "author": [], "published_at": []}
        self.capture_field: str | None = None
        self.capture_depth = 0
        self.in_content = False
        self.content_depth = 0
        self.content_container_found = False
        self.content_container_closed = False
        self.skip_depth = 0
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            meta_key = attr.get("property") or attr.get("name") or attr.get("itemprop")
            key = meta_key.lower() if meta_key else ""
            content = attr.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content

        element_id = attr.get("id", "")
        if self.capture_field is None and element_id in CAPTURE_IDS:
            self.capture_field, self.capture_depth = CAPTURE_IDS[element_id], 1
        elif self.capture_field is not None and tag not in VOID_TAGS:
            self.capture_depth += 1

        if not self.in_content and element_id == "js_content":
            self.in_content, self.content_depth, self.content_container_found = True, 1, True
        elif self.in_content and tag not in VOID_TAGS:
            self.content_depth += 1
        if not self.in_content:
            return
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            if tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        if tag in BLOCK_TAGS or tag in {"br", "hr"}:
            self.body_parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.capture_field is not None:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self.capture_field, self.capture_depth = None, 0
        if not self.in_content:
            return
        if self.skip_depth:
            self.skip_depth -= 1
        elif tag in BLOCK_TAGS:
            self.body_parts.append("\n")
        if tag not in VOID_TAGS:
            self.content_depth -= 1
            if self.content_depth <= 0:
                self.in_content, self.content_depth = False, 0
                self.content_container_closed, self.skip_depth = True, 0

    def handle_data(self, data: str) -> None:
        if self.capture_field is not None:
            self.fields[self.capture_field].append(data)
        if self.in_content and not self.skip_depth:
            self.body_parts.append(data)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def canonical_body(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def clean_author(author: str, account: str) -> str:
    candidate = compact(author)
    if not candidate or any(p.search(candidate) for p in INVALID_AUTHOR_PATTERNS):
        return compact(account)
    return candidate


def identity_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value)


def title_variants(title: str, author: str) -> set[str]:
    variants = {compact(title)} if compact(title) else set()
    parts = re.split(r"[:：]", compact(title), maxsplit=1)
    if len(parts) == 2 and identity_text(parts[0]) == identity_text(author):
        variants.add(compact(parts[1]))
    return variants


def is_edge_author_line(line: str, author: str) -> bool:
    compact_author = compact(author)
    if len(line) > 140 or not compact_author:
        return False
    spaced = [p for p in re.split(r"\s+", compact_author) if p]
    parts = spaced if len(spaced) > 1 and all(len(p) >= 2 for p in spaced) else [re.sub(r"\s+", "", compact_author)]
    norm_line = identity_text(line)
    norm_parts = [identity_text(p) for p in parts if p]
    if not norm_parts:
        return False
    return norm_line == "".join(norm_parts) or (bool(AUTHOR_ROLE_PATTERN.search(line)) and all(p in norm_line for p in norm_parts))


def strip_known_footer(body: str, author: str = "") -> tuple[str, list[str]]:
    lines = [compact(line) for line in body.splitlines() if compact(line)]
    kept, removed = [], []
    related_tail_indexes: set[int] = set()

    for index in range(max(0, len(lines) - 3), len(lines)):
        if RELATED_ARTICLE_TAIL_PATTERN.fullmatch(lines[index]) or BARE_RELATED_ARTICLE_TAIL_PATTERN.fullmatch(lines[index]):
            block = lines[index:]
            if any(ARTICLE_TITLE_PATTERN.search(t) for t in block) and all(len(t) <= 160 for t in block):
                related_tail_indexes.update(range(index, len(lines)))

    footer_start = max(0, len(lines) - 12)
    tail_start = max(0, len(lines) - 8)
    ps_idx = next((i for i in range(max(0, len(lines) - 16), len(lines)) if re.match(r"^PS\s*(?:[：:].*)?$", lines[i], re.IGNORECASE)), None)
    promo_start = min(tail_start, ps_idx) if ps_idx is not None else tail_start

    drop_flags = [
        False if ERRATA_SIGNAL.search(line) else (
            (idx >= footer_start and any(p.match(line) for p in KNOWN_FOOTER_PATTERNS))
            or (idx >= promo_start and bool(TAIL_PROMO_ACTION_RE.search(line)))
            or (idx in related_tail_indexes)
        )
        for idx, line in enumerate(lines)
    ]
    if (
        ps_idx is not None
        and re.fullmatch(r"PS\s*[：:]?", lines[ps_idx], re.IGNORECASE) is not None
        and ps_idx + 1 < len(lines)
        and all(drop_flags[j] for j in range(ps_idx + 1, len(lines)))
    ):
        drop_flags[ps_idx] = True

    for index, line in enumerate(lines):
        is_byline = is_edge_author_line(line, author) or bool(re.match(r"^(?:[（(]?(?:作者|撰文|供稿|执笔|主笔|文)[:：/]|观点\s*/.+主笔\s*/)", line))
        if not is_byline and drop_flags[index]:
            removed.append(line)
        else:
            kept.append(line)
    return canonical_body("\n\n".join(kept)), removed


def body_metrics(value: str) -> dict[str, Any]:
    value = canonical_body(value)
    paragraphs = [part for part in value.split("\n\n") if part.strip()]
    return {
        "character_count": len(re.sub(r"\s+", "", value)),
        "paragraph_count": len(paragraphs),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "first_excerpt": compact(value[:160]),
        "last_excerpt": compact(value[-160:]),
    }


def first_nonempty(*values: str | None) -> str:
    return next((compact(v) for v in values if v and compact(v)), "")


def regex_value(html: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return compact(match.group(1).replace("\\x26", "&"))
    return ""


def normalize_date(value: str, html: str) -> str:
    candidates = [value, *(
        m.group(1)
        for pat in (r"(?:publish_time|create_time|ori_create_time)[\"']?\s*[:=]\s*[\"']?(\d{10})", r"\bct\s*=\s*[\"'](\d{10})[\"']")
        for m in re.finditer(pat, html, flags=re.IGNORECASE)
    )]
    for cand in candidates:
        cand = compact(cand)
        if not cand:
            continue
        if re.fullmatch(r"\d{10}", cand):
            return datetime.fromtimestamp(int(cand), tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", cand)
        if m:
            try:
                return datetime(*map(int, m.groups())).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return ""


def normalize_body(raw: str, title: str, author: str = "") -> tuple[str, str, list[str], list[str]]:
    raw_lines: list[str] = []
    for raw_line in raw.splitlines():
        line = compact(raw_line)
        if line and (not raw_lines or line != raw_lines[-1]):
            raw_lines.append(line)

    lines, sources, removed_lines = [], [], []
    variants = title_variants(title, author)
    for index, line in enumerate(raw_lines):
        src_m = re.search(r"(?:来源|本文来源)[:：]\s*([^）)]+)", line)
        if src_m and (src := compact(src_m.group(1))) and src not in sources:
            sources.append(src)
        if (index < 2 and line in variants) or (any(p.match(line) for p in NOISE_LINE_PATTERNS) and not re.search(r"(?:作者|撰文|供稿|执笔|主笔)[:：/]", line)):
            removed_lines.append(line)
            continue
        if not lines or line != lines[-1]:
            lines.append(line)

    raw_body = "\n\n".join(raw_lines).strip()
    clean_body, footer_removed = strip_known_footer("\n\n".join(lines).strip(), author)
    removed_lines.extend(footer_removed)
    return raw_body, clean_body, sources, removed_lines


def extract(html: str) -> dict[str, Any]:
    parser = WeixinHTMLParser()
    parser.feed(html)
    parser.close()

    title = first_nonempty(parser.meta.get("og:title"), "".join(parser.fields["title"]), parser.meta.get("twitter:title"))
    account = first_nonempty("".join(parser.fields["account"]), regex_value(html, (r"\bnickname\s*[:=]\s*[\"']([^\"']+)[\"']", r"\baccount_name\s*[:=]\s*[\"']([^\"']+)[\"']")))
    author = first_nonempty(parser.meta.get("author"), "".join(parser.fields["author"]), regex_value(html, (r"\bauthor\s*[:=]\s*[\"']([^\"']+)[\"']", r"\bauthor_name\s*[:=]\s*[\"']([^\"']+)[\"']")))
    published_at = normalize_date(first_nonempty(parser.meta.get("article:published_time"), parser.meta.get("publishdate"), "".join(parser.fields["published_at"])), html)
    raw_body, body, sources, removed_lines = normalize_body("".join(parser.body_parts), title, author)
    canonical_url = first_nonempty(parser.meta.get("og:url"), parser.meta.get("twitter:url"), regex_value(html, (r"\bmsg_link\s*=\s*[\"']([^\"']+)[\"']",)))

    blocked_hits = [m for m in BLOCKED_MARKERS if m in html]
    raw_metrics, clean_metrics = body_metrics(raw_body), body_metrics(body)
    reasons: list[str] = []
    if not title:
        reasons.append("missing_title")
    if not parser.content_container_found:
        reasons.append("missing_content_container")
    if not body.replace("\ufffd", "").strip():
        reasons.append("empty_or_garbled_body")
    if blocked_hits:
        rem = body
        for marker in sorted(BLOCKED_MARKERS, key=len, reverse=True):
            rem = rem.replace(marker, "")
        if not parser.content_container_found or not re.sub(r"[\s请您，。！!：:,、]+", "", rem):
            reasons.append("wechat_verification_page")

    return {
        "is_article": not reasons, "reasons": reasons, "blocked_markers": blocked_hits,
        "title": title, "account": account, "author": clean_author(author, account),
        "published_at": published_at, "source": sources[0] if sources else "", "source_candidates": sources,
        "canonical_url": canonical_url, "body": body,
        "raw_body_character_count": raw_metrics["character_count"], "raw_body_paragraph_count": raw_metrics["paragraph_count"],
        "raw_body_sha256": raw_metrics["sha256"], "body_character_count": clean_metrics["character_count"],
        "body_paragraph_count": clean_metrics["paragraph_count"], "body_sha256": clean_metrics["sha256"],
        "body_first_excerpt": clean_metrics["first_excerpt"], "body_last_excerpt": clean_metrics["last_excerpt"],
        "cleaning_removed_lines": removed_lines, "cleaning_version": 8,
        "content_container_found": parser.content_container_found, "content_container_closed": parser.content_container_closed,
    }
