#!/usr/bin/env python3
"""Prepare Bilibili transcripts (fast subtitle lane or offline ASR) and save quality-gated Markdown."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_common import (
    USER_AGENT, EnvironmentBlocked, NoSpeechDetected, _next_acquisition_route, acquisition,
    acquisition_denied, check_runtime as shared_check_runtime, clean_topic_title, default_work_root,
    diarize_existing, executable, finalize_manifest_note, find_existing_work, has_multi_speaker_hint,
    inspect_draft_quality, is_environment_error, media_signature, merge_transcript, probe_media,
    read_json, run, run_asr, safe_error, shared_retry_excerpt as retry_excerpt, transcribe_and_merge, write_json,
)

CUE_TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})")


def resolve_short_url(url: str) -> str:
    res = subprocess.run(
        [executable("curl"), "--disable", "--location", "--silent", "--show-error", "--max-time", "10", "--user-agent", USER_AGENT, "-o", "/dev/null", "-w", "%{url_effective}", url],
        text=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    resolved = res.stdout.strip()
    if res.returncode == 0 and resolved.startswith(("http://", "https://")):
        return resolved
    raise ValueError("b23.tv 短链解析失败，请提供完整 B 站视频链接")


def canonical(url: str) -> tuple[str, str]:
    parsed = urlsplit(str(url).strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme in ("http", "https") and host in ("b23.tv", "bili2233.cn"):
        url = resolve_short_url(url)
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[0-9]+)/?", parsed.path)
    if parsed.scheme not in ("http", "https") or host not in ("www.bilibili.com", "bilibili.com") or not match:
        raise ValueError("只处理 B 站 /video/BV…、/video/av… 或 b23.tv 视频链接")
    part = int(parse_qs(parsed.query).get("p", ["1"])[-1])
    if part < 1:
        raise ValueError("p 必须大于零")
    iid = match[1]
    return f"{iid}-p{part}", f"https://www.bilibili.com/video/{iid}/?p={part}"


def _parse_subtitle_segments(sub_path: Path) -> list[dict]:
    if sub_path.suffix.lower() == ".json3":
        segments = []
        for ev in read_json(sub_path).get("events", []):
            segs = ev.get("segs")
            if not segs or "tStartMs" not in ev:
                continue
            text = "".join(str(s.get("utf8") or "") for s in segs).replace("\n", " ").strip()
            if text:
                start = round(ev["tStartMs"] / 1000.0, 3)
                end = round(start + max(0.2, float(ev.get("dDurationMs") or 1000) / 1000.0), 3)
                segments.append({"start": start, "end": end, "text": text, "words": [{"start": start, "end": end, "word": text}]})
        return segments

    raw_text = sub_path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    segments = []
    for block in re.split(r"\r?\n\s*\r?\n", raw_text):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        hit = next(((idx, m) for idx, ln in enumerate(lines) if (m := CUE_TIME_RE.match(ln))), None)
        if hit is None or hit[0] + 1 >= len(lines):
            continue
        cue_idx, g = hit[0], hit[1].groups()
        start = round(int(g[0] or 0) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0, 3)
        end = round(max(start + 0.2, int(g[4] or 0) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0), 3)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>|\{\\[^}]+\}", "", " ".join(lines[cue_idx + 1 :])))).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text, "words": [{"start": start, "end": end, "word": text}]})
    return segments


def try_bilibili_subtitles(url: str, work: Path) -> tuple[Path, dict, dict] | None:
    """Attempt fast subtitle-only fetch (SRT/JSON3/VTT) without counting against media download budget."""
    sub_dir = work / "sub_probe"
    sub_dir.mkdir(parents=True, exist_ok=True)
    info_file = sub_dir / "sub.info.json"

    def _collect_subs() -> list[Path]:
        found = [p for ext in ("*.srt", "*.json3", "*.vtt") for p in sub_dir.glob(ext) if p.is_file()]
        return sorted(found, key=lambda p: (next((i for i, t in enumerate((".zh-cn.", ".zh-hans.", ".zh.", ".ai-zh.")) if t in p.name.lower()), 9), p.name.lower()))

    sub_files = _collect_subs()
    if not sub_files or not info_file.is_file():
        res = subprocess.run(
            [
                executable("yt-dlp"), "--ignore-config", "--no-playlist", "--skip-download",
                "--write-subs", "--write-auto-subs", "--sub-langs", "zh-CN,zh-Hans,zh,ai-zh",
                "--sub-format", "srt/json3/vtt/best", "--write-info-json",
                "--retries", "0", "--extractor-retries", "0", "--socket-timeout", "15",
                "-o", str(sub_dir / "sub"), url,
            ],
            text=True, capture_output=True, encoding="utf-8", errors="replace",
        )
        sub_files = _collect_subs()
        if res.returncode != 0 and is_environment_error(RuntimeError(res.stderr or "")):
            raise EnvironmentBlocked(f"本地工作目录权限或临时文件清理受限，请改用缓存工作目录或申请本机权限后重试：{safe_error(RuntimeError(res.stderr or 'yt-dlp 写临时文件受限'))}")
        if res.returncode != 0 or not sub_files or not info_file.is_file():
            return None
    try:
        info, segments = read_json(info_file), _parse_subtitle_segments(sub_files[0])
    except Exception:
        return None

    full_text = "".join(s["text"] for s in segments).strip()
    if len(re.sub(r"\s+", "", full_text)) < 20 or not inspect_draft_quality(full_text)["usable"]:
        return None
    asr = {"text": full_text, "segments": segments, "language": "zh", "source": "bilibili_subtitle", "subtitle_file": sub_files[0].name}
    asr_path = work / "asr.json"
    write_json(asr_path, asr)
    return asr_path, asr, info


def _published_date(info: dict) -> str:
    if info.get("timestamp"):
        return dt.datetime.fromtimestamp(info["timestamp"], ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    raw = str(info.get("upload_date") or info.get("published") or info.get("date") or "").strip()
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else ""


def prepare_one(
    url: str, work_root: Path, output_root: Path, speakers: bool = False,
    *, media_override: Path | None = None, subtitle_override: Path | None = None, info_override: Path | None = None,
) -> dict:
    started, stage, timings = time.time(), "input", {}
    try:
        key, url = canonical(url)
        output_root = Path(output_root).expanduser().resolve()
        if existing := find_existing_work(output_root, url):
            return {"status": "existing_needs_format_review", "key": key, "url": url, "output": str(existing), "output_dir": str(output_root)}
        work = work_root / key
        work.mkdir(parents=True, exist_ok=True)
        manifest = work / "manifest.json"
        extra_info = read_json(info_override.expanduser().resolve()) if info_override else None
        if not manifest.exists():
            write_json(manifest, {"status": "acquiring", "key": key, "url": url, "output_dir": str(output_root), **({"source_info": extra_info} if extra_info else {})})
        elif extra_info:
            cur_m = read_json(manifest)
            cur_m["source_info"] = extra_info
            write_json(manifest, cur_m)

        if media_override is not None:
            m_ov = media_override.expanduser().resolve()
            if not m_ov.is_file() or not m_ov.stat().st_size:
                raise ValueError("传入的 --media 文件不存在或为空")
            cur_m = read_json(manifest)
            cur_attempts = (cur_m.get("acquisition") or {}).get("attempts") or []
            if not cur_attempts:
                acquisition(manifest, "begin", route="B")
                acquisition(manifest, "finish", outcome="success", media=m_ov, info=extra_info)
            elif cur_attempts[-1].get("outcome") == "pending":
                acquisition(manifest, "finish", outcome="success", media=m_ov, info=extra_info)
            else:
                cur_m["media"] = str(m_ov)
                write_json(manifest, cur_m)

        old = read_json(manifest)
        local_m = Path(old["media"]).resolve() if old.get("media") and Path(old["media"]).is_file() else None
        has_local_media = local_m is not None
        replacing_media = bool(local_m and old.get("draft") and old.get("media_sig") != media_signature(local_m))
        supplying_sub_dur = bool(extra_info and extra_info.get("duration") and old.get("subtitle_source") and not old.get("duration"))
        replacing_sub = subtitle_override is not None or supplying_sub_dur
        if Path(old.get("output_dir", "")).resolve() != output_root:
            old["output_dir"] = str(output_root)
            if old.get("status") == "saved" and Path(old.get("draft", "")).is_file():
                old["status"] = "prepared"
                old.pop("output", None)
            write_json(manifest, old)
        if not replacing_media and not replacing_sub:
            if old.get("status") == "saved" and Path(old.get("output", "")).is_file():
                return {"status": "saved", "url": url, "output": old["output"], "reused": True}
            if old.get("status") == "prepared" and Path(old.get("draft", "")).is_file() and (not speakers or old.get("diarized")):
                return {"status": "prepared", "url": url, "manifest": str(manifest), "draft": old["draft"], "reused": True}
            if old.get("status") == "no_speech":
                return old

        sub_hit = None
        if subtitle_override is not None and not speakers and not has_local_media:
            sub_file = subtitle_override.expanduser().resolve()
            segs = _parse_subtitle_segments(sub_file)
            full_text = "".join(s["text"] for s in segs).strip()
            if len(re.sub(r"\s+", "", full_text)) < 20 or not inspect_draft_quality(full_text)["usable"]:
                raise ValueError("传入字幕文件有效字数不足或包含异常乱码")
            fallback_info = (
                (read_json(work / "sub_probe/sub.info.json") if (work / "sub_probe/sub.info.json").is_file() else None)
                or (read_json(work / "audio.info.json") if (work / "audio.info.json").is_file() else None)
            )
            s_info = extra_info or old.get("source_info") or fallback_info or {"title": old.get("title") or key}
            asr_obj = {"text": full_text, "segments": segs, "language": "zh", "source": "bilibili_subtitle", "subtitle_file": sub_file.name}
            asr_p = work / "asr.json"
            write_json(asr_p, asr_obj)
            sub_hit = (asr_p, asr_obj, s_info)
        elif supplying_sub_dur and not speakers and not has_local_media and (work / "asr.json").is_file():
            sub_hit = (work / "asr.json", read_json(work / "asr.json"), extra_info)
        elif not speakers and not has_local_media:
            stage, tick = "subtitle_probe", time.perf_counter()
            sub_hit = try_bilibili_subtitles(url, work)
            if sub_hit is not None:
                timings["subtitle_probe"] = round(time.perf_counter() - tick, 3)

        if sub_hit is not None:
            asr_path, asr, info = sub_hit
            duration = float(info.get("duration") or 0) or None
            body, speaker_count = merge_transcript(asr, None, duration, include_timestamps=False)
            draft = work / "draft.txt"
            draft.write_text(body + "\n", encoding="utf-8")
            quality = inspect_draft_quality(body)
            media_str, subtitle_source, asr_str = "", (asr.get("subtitle_file") or "bilibili_subtitle"), str(asr_path)
        else:
            stage, tick = "download", time.perf_counter()
            state = read_json(manifest)
            attempts = state.get("acquisition", {}).get("attempts", [])
            if state.get("acquisition", {}).get("blocked"):
                raise RuntimeError("本条已明确受限，不换路")
            if attempts and attempts[-1]["outcome"] == "pending":
                return {"status": "acquisition_unknown", "manifest": str(manifest), "url": url}
            if state.get("media") and Path(state["media"]).is_file():
                media = Path(state["media"]).resolve()
                info = (
                    state.get("source_info")
                    or (read_json(work / "audio.info.json") if (work / "audio.info.json").is_file() else None)
                    or (read_json(work / "sub_probe/sub.info.json") if (work / "sub_probe/sub.info.json").is_file() else None)
                )
                if not info:
                    probed = probe_media(media, require_audio=True)
                    info = {
                        "title": state.get("raw_title") or state.get("title") or key,
                        "uploader": state.get("author") or "",
                        "published": state.get("published") or "",
                        "like_count": state.get("likes") if "likes" in state else state.get("like_count"),
                        "duration": state.get("duration") or probed.get("duration"),
                        "description": state.get("description") or "",
                    }
            else:
                nxt = _next_acquisition_route(attempts, default_first="A")
                if nxt is None:
                    return {"status": "failed", "manifest": str(manifest), "url": url, "error": "四次预算用尽"}
                if nxt == "B":
                    return {"status": "needs_media", "route": "B", "manifest": str(manifest), "url": url}
                acquisition(manifest, "begin", route="A")
                try:
                    res = run([
                        executable("yt-dlp"), "--ignore-config", "--no-playlist", "-f", "bestaudio",
                        "--retries", "0", "--extractor-retries", "0", "--fragment-retries", "0",
                        "--socket-timeout", "20", "--write-info-json", "--print", "after_move:filepath",
                        "-o", str(work / "audio.%(ext)s"), url,
                    ])
                    if acquisition_denied(res.stderr, unauthenticated_cli=True):
                        raise RuntimeError(res.stderr)
                    media = Path(res.stdout.strip().splitlines()[-1]).resolve()
                    info = read_json(work / "audio.info.json")
                    if extra_info:
                        info = {**info, **{k: v for k, v in extra_info.items() if v not in (None, "")}}
                    acquisition(manifest, "finish", outcome="success", media=media, info=info)
                except Exception as exc:
                    if is_environment_error(exc):
                        cur_m = read_json(manifest)
                        att = (cur_m.get("acquisition") or {}).get("attempts") or []
                        if att and att[-1].get("outcome") == "pending":
                            att.pop()
                            write_json(manifest, cur_m)
                        raise EnvironmentBlocked(f"本地工作目录权限或临时文件清理受限，请改用缓存工作目录或申请本机权限后重试：{safe_error(exc)}") from None
                    denied = acquisition_denied(exc, unauthenticated_cli=True)
                    acquisition(manifest, "finish", outcome="denied" if denied else "failed", detail=safe_error(exc))
                    return {"status": "blocked" if denied else "needs_media", **({} if denied else {"route": "B"}), "manifest": str(manifest), "url": url, "error": safe_error(exc)}
            timings[stage] = round(time.perf_counter() - tick, 3)
            if not media.stat().st_size or info.get("media_incomplete"):
                raise RuntimeError("媒体为空或已知不完整，保留现场")

            stage = "transcribe"
            existing_asr = Path(state.get("asr") or (work / "asr.json"))
            reuse_sub = existing_asr if (speakers and not replacing_media and state.get("subtitle_source") and existing_asr.is_file()) else None
            exp_dur = float(info.get("duration") or 0) or probe_media(media, require_audio=True).get("duration")
            try:
                tx = transcribe_and_merge(media, work, speakers=speakers, expected_duration=exp_dur, replacing=replacing_media, reuse_asr=reuse_sub, runner=run_asr)
            except NoSpeechDetected as exc:
                raw_title = str(info.get("title") or key)
                data = {
                    **read_json(manifest), "status": "no_speech", "key": key, "url": url,
                    "title": clean_topic_title(raw_title) or raw_title, "raw_title": raw_title,
                    "author": info.get("uploader") or info.get("author") or "", "published": _published_date(info),
                    "likes": info.get("like_count") if info.get("like_count") is not None else info.get("likes", ""),
                    "media": str(media), "media_sig": media_signature(media), "output_dir": str(output_root), "note": str(exc), "timings": timings,
                }
                write_json(manifest, data)
                return {"status": "no_speech", "url": url, "manifest": str(manifest), "note": str(exc)}
            timings.update(tx["timings"])
            if tx["replaced_invalid"]:
                return {"status": "invalid_draft", "url": url, "manifest": str(manifest), "attempted_media": str(media), "invalid_draft": tx["invalid_draft"], "draft_quality": tx["draft_quality"], "timings": timings}
            draft, quality, speaker_count, duration, asr_str = Path(tx["draft"]), tx["draft_quality"], tx["speaker_count"], tx["duration"], tx["asr"]
            media_str, subtitle_source = str(media), (str(state["subtitle_source"]) if reuse_sub else "")

        raw_title = str(info.get("title") or key)
        clean = clean_topic_title(raw_title) or raw_title
        timings["prepare_wall"] = round(time.time() - started, 3)
        base_manifest = read_json(manifest)
        if replacing_media:
            for k in ("verified_silence", "verified_silence_sig", "output", "note", "error"):
                base_manifest.pop(k, None)
        data = {
            **base_manifest, "status": "prepared" if quality["usable"] else "invalid_draft",
            "key": key, "url": url, "title": clean, "raw_title": raw_title,
            "author": info.get("uploader") or info.get("author") or "",
            "published": _published_date(info),
            "likes": info.get("like_count") if info.get("like_count") is not None else info.get("likes", ""),
            "duration": duration, "speaker_count": speaker_count, "speaker_limit": 3, "diarized": speakers,
            "multi_speaker_hint": has_multi_speaker_hint(raw_title, info.get("description") or ""),
            "media": media_str, "media_sig": media_signature(Path(media_str)) if media_str else "",
            "subtitle_source": subtitle_source, "draft": str(draft), "draft_quality": quality,
            "asr": asr_str, "output_dir": str(output_root), "started_at_epoch": started, "timings": timings,
        }
        write_json(manifest, data)
        return {"status": data["status"], "url": url, "manifest": str(manifest), "draft": str(draft), "subtitle_source": subtitle_source or None, "multi_speaker_hint": data["multi_speaker_hint"], "draft_quality": quality, "timings": timings}
    except Exception as exc:
        if is_environment_error(exc):
            raise EnvironmentBlocked(safe_error(exc)) from None
        return {"status": "failed", "url": url, "stage": stage, "error": safe_error(exc), "wall_seconds": round(time.time() - started, 3)}


def prepare(
    urls: list[str], work_root: Path | None, output_root: Path, speakers: bool = False,
    *, media_override: Path | None = None, subtitle_override: Path | None = None, info_override: Path | None = None,
) -> dict:
    started = time.time()
    if output_root is None or not str(output_root).strip():
        raise ValueError("保存到哪个文件夹？")
    resolved_out = output_root.expanduser().resolve()
    resolved_work = work_root.expanduser().resolve() if work_root is not None else default_work_root("bilibili")
    if (media_override or subtitle_override or info_override) and len(urls) != 1:
        raise ValueError("--media / --subtitle / --info-json 仅适用于单条链接直接交接")
    items = [
        prepare_one(
            url, resolved_work, resolved_out, speakers=speakers,
            media_override=media_override, subtitle_override=subtitle_override, info_override=info_override,
        )
        for url in urls
    ]
    existing_count = sum(item["status"] == "existing_needs_format_review" for item in items)
    failed = sum(item["status"] not in ("prepared", "saved", "no_speech", "existing_needs_format_review") for item in items)
    status = "failed" if failed == len(items) else "partial" if failed else ("existing_needs_format_review" if existing_count == len(items) else "prepared")
    return {"status": status, "items": items, "input_count": len(urls), "existing_count": existing_count, "failed_count": failed, "wall_seconds": round(time.time() - started, 3)}


def finalize(manifest: Path, reviewed: Path, tags: list[str] | None = None, output_dir: Path | None = None, title_override: str | None = None, verified_silence: bool = False) -> dict:
    data = read_json(manifest)
    if data.get("subtitle_source") and not data.get("media") and not (isinstance(data.get("duration"), (int, float)) and float(data["duration"]) > 0):
        raise ValueError("字幕快车道成稿入库前须提供同篇作品时长（请在 prepare --info-json 提供 duration）以核验覆盖完整性；当前时长未知，已保留候选草稿")
    return finalize_manifest_note(manifest, reviewed, platform="B站", output_dir=output_dir, tags=tags, title_override=title_override, verified_silence=verified_silence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    checker = sub.add_parser("check"); checker.add_argument("--output-dir", type=Path, required=True); checker.add_argument("--speakers", action="store_true")
    prep = sub.add_parser("prepare"); prep.add_argument("--work-dir", type=Path, default=None); prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--media", type=Path); prep.add_argument("--subtitle", type=Path); prep.add_argument("--info-json", type=Path)
    prep.add_argument("--speakers", action="store_true"); prep.add_argument("urls", nargs="+")
    sub.add_parser("diarize").add_argument("--manifest", type=Path, required=True)
    retry = sub.add_parser("retry-excerpt"); retry.add_argument("--manifest", type=Path, required=True); retry.add_argument("--clip", type=float, nargs=2, required=True, metavar=("START", "END"))
    done = sub.add_parser("finalize"); done.add_argument("--manifest", type=Path, required=True); done.add_argument("--reviewed", type=Path, required=True)
    done.add_argument("--output-dir", type=Path); done.add_argument("--tags", nargs="+"); done.add_argument("--title"); done.add_argument("--verified-silence", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "check":
            result = shared_check_runtime([args.output_dir], executable, speakers=args.speakers, downloader=True)
        elif args.action == "prepare":
            result = prepare(args.urls, args.work_dir, args.output_dir, speakers=args.speakers, media_override=args.media, subtitle_override=args.subtitle, info_override=args.info_json)
        elif args.action == "diarize":
            result = diarize_existing(args.manifest)
        elif args.action == "retry-excerpt":
            result = retry_excerpt(args.manifest, *args.clip)
        else:
            result = finalize(args.manifest, args.reviewed, tags=args.tags, output_dir=args.output_dir, title_override=args.title, verified_silence=args.verified_silence)
    except Exception as exc:
        result = {"status": "environment_blocked" if args.action == "check" or is_environment_error(exc) else "failed", "error": safe_error(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get("status") == "environment_blocked" else int(result.get("status") in ("partial", "failed", "invalid_draft", "needs_media"))


if __name__ == "__main__":
    sys.exit(main())
