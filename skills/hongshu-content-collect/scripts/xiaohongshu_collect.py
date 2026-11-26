#!/usr/bin/env python3
"""Prepare Xiaohongshu video/image-text drafts and save quality-gated Markdown notes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_common import (
    EnvironmentBlocked, NoSpeechDetected, _next_acquisition_route, acquisition, acquisition_denied,
    check_runtime as shared_check_runtime, clean_topic_title, default_work_root, diarize_existing,
    executable, fetch_verified_media, finalize_manifest_note, find_existing_work, has_multi_speaker_hint,
    inspect_draft_quality, is_environment_error, media_signature, probe_media, read_json, run,
    run_asr, safe_error, shared_retry_excerpt as retry_excerpt, transcribe_and_merge, write_json,
)

ID_RE = re.compile(r"/(?:explore|discovery/item|user/profile/[0-9a-f]{24})/([0-9a-f]{24})(?:[/?#]|$)", re.I)


def note_id(url: str) -> str:
    match = ID_RE.search(str(url))
    if not match:
        raise ValueError("source.url 必须是已解析的笔记链接")
    return match.group(1)


def replacement(data: dict, existing: Path | None) -> Path | None:
    target = Path(data["replace"]).resolve() if data.get("replace") else None
    if target and (existing is None or target != existing.resolve() or target.parent != Path(data["output_dir"]).resolve()):
        raise ValueError("replace 必须是输出目录内同一原文链接的现有笔记")
    return target


def _resolve_work_dir(source_path: Path, output_dir: Path, iid: str, work_dir: Path | None, data: dict) -> Path:
    raw = work_dir or (Path(data["work_dir"]) if data.get("work_dir") else None)
    if raw is not None:
        cand = Path(raw).expanduser().resolve()
        if cand != output_dir:
            cand.mkdir(parents=True, exist_ok=True)
            return cand
    if source_path.parent != output_dir:
        return source_path.parent
    return default_work_root("xiaohongshu", iid)


def prepare(source_path: Path, speakers: bool = False, work_dir: Path | None = None) -> dict:
    started = time.perf_counter()
    source_path = source_path.resolve()
    data = read_json(source_path)
    data["id"] = note_id(data["url"])
    data.setdefault("started_at_epoch", time.time())
    if not data.get("output_dir"):
        raise ValueError("保存到哪个文件夹？")
    output_dir = Path(data["output_dir"]).expanduser().resolve()
    data["output_dir"] = str(output_dir)
    work = _resolve_work_dir(source_path, output_dir, data["id"], work_dir, data)
    raw_pub_disp = str(data.get("published_display") or data.get("published") or "").strip()
    if raw_pub_disp:
        data.setdefault("published_display", raw_pub_disp)
        if data.get("date_kind") == "edited" or re.match(r"^编辑于(?:\s|$)", raw_pub_disp):
            data["date_kind"] = "edited"
        if not str(data.get("published") or "").strip() or re.match(r"^(?:编辑于|发布于)(?:\s|$)", str(data.get("published") or "").strip()):
            stripped = re.sub(r"^(?:编辑于|发布于)\s*", "", raw_pub_disp).strip()
            m_d = re.match(r"^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}-\d{1,2})(?:\s+[\u4e00-\u9fa5A-Za-z]+)?$", stripped)
            if m_d:
                data["published"] = m_d.group(1)
    existing = find_existing_work(output_dir, data["url"])
    replace = replacement(data, existing)
    if existing and not replace:
        return {"status": "existing_needs_format_review", "output": str(existing), "id": data["id"]}

    manifest = work / "manifest.json"
    explicit_media = Path(data["media"]).expanduser().resolve() if data.get("media") else None
    replacing_media = False
    if manifest.exists():
        previous = read_json(manifest)
        if previous.get("url") != data["url"]:
            raise ValueError("现有状态与作品不匹配")
        if explicit_media is not None:
            old_media = Path(previous["media"]).resolve() if previous.get("media") else None
            new_sig = media_signature(explicit_media) if (explicit_media.is_file() and explicit_media.stat().st_size) else None
            replacing_media = (old_media != explicit_media) or bool(new_sig and previous.get("media_sig") and previous["media_sig"] != new_sig)
        if Path(previous.get("output_dir", "")).resolve() != output_dir:
            previous["output_dir"] = str(output_dir)
            if previous.get("status") == "saved" and Path(previous.get("draft", "")).is_file():
                previous["status"] = "prepared"
                previous.pop("output", None)
            write_json(manifest, previous)
        if not replacing_media:
            if previous.get("status") == "saved" and Path(previous.get("output", "")).is_file():
                return {"status": "existing_needs_format_review", "output": previous["output"]}
            if previous.get("status") == "prepared" and Path(previous.get("draft", "")).is_file():
                return {"status": "prepared", "manifest": str(manifest), "draft": previous["draft"], "reused": True}
            if previous.get("status") == "no_speech":
                return previous

    raw_title = str(data.get("raw_title") or data.get("title") or "")
    chosen_title = str(data.get("title") or raw_title)
    clean_title = clean_topic_title(chosen_title) or chosen_title.strip() or data["id"]
    hint = has_multi_speaker_hint(raw_title, chosen_title, data.get("text") or "")
    data.update(title=clean_title, multi_speaker_hint=hint)
    use_speakers = bool(speakers or data.get("speakers"))
    timings, extra_warnings = {}, []

    if data["content_type"] == "视频":
        if data.get("acquisition", {}).get("blocked") or data.get("media_incomplete"):
            raise RuntimeError("来源已受限或媒体已知不完整，停止该条")
        stage = time.perf_counter()
        raw_exp = data.get("duration") if isinstance(data.get("duration"), (int, float)) and data["duration"] > 0 else None
        media: Path | None = None
        if data.get("media"):
            media = Path(data["media"]).expanduser().resolve()
            if not media.is_file() or not media.stat().st_size:
                raise ValueError("media 文件不存在或为空")
            probe_media(media, require_audio=True, expected_duration=float(raw_exp) if raw_exp else None)
        else:
            attempts = data.get("acquisition", {}).get("attempts", [])
            if attempts and attempts[-1]["outcome"] == "pending":
                return {"status": "acquisition_unknown", "source": str(source_path)}
            if len(attempts) >= 4:
                return {"status": "failed", "source": str(source_path), "error": "四次预算用尽"}
            raw_streams = data.get("stream_urls") or data.get("streamUrls") or ([data["video_url"]] if data.get("video_url") else [])
            if raw_streams and (not attempts or _next_acquisition_route(attempts) == "B"):
                try:
                    dl = fetch_verified_media(
                        raw_streams, "xiaohongshu", work / "media.mp4", state_path=source_path,
                        route="B", require_audio=True, expected_duration=float(raw_exp) if raw_exp else None,
                    )
                    data = read_json(source_path)
                    media = Path(dl["media"]).resolve()
                except Exception as exc:
                    if is_environment_error(exc):
                        raise
                    data = read_json(source_path)
                    attempts = data.get("acquisition", {}).get("attempts", [])
            if media is None:
                nxt = _next_acquisition_route(attempts, default_first="A")
                if nxt is None:
                    return {"status": "failed", "source": str(source_path), "error": "四次预算用尽"}
                if nxt == "B":
                    return {"status": "needs_media", "route": "B", "source": str(source_path)}
                data = acquisition(source_path, "begin", route="A")
                try:
                    res = run([
                        executable("yt-dlp"), "--ignore-config", "--retries", "0", "--extractor-retries", "0",
                        "--fragment-retries", "0", "--socket-timeout", "20", "--no-playlist",
                        "--print", "after_move:filepath", "-P", str(work), "-o", "source.%(ext)s", data["url"],
                    ])
                    if acquisition_denied(res.stderr, unauthenticated_cli=True):
                        raise RuntimeError(res.stderr)
                    lines = [ln for ln in res.stdout.strip().splitlines() if ln.strip()]
                    if not lines:
                        raise RuntimeError(res.stderr or "yt-dlp 未产出媒体文件")
                    media = Path(lines[-1]).resolve()
                    data = acquisition(source_path, "finish", outcome="success", media=media)
                except Exception as exc:
                    if is_environment_error(exc):
                        cur_d = read_json(source_path)
                        att = (cur_d.get("acquisition") or {}).get("attempts") or []
                        if att and att[-1].get("outcome") == "pending":
                            att.pop()
                            write_json(source_path, cur_d)
                        raise EnvironmentBlocked(f"本地工作目录权限或临时文件清理受限，请改用缓存工作目录或申请本机权限后重试：{safe_error(exc)}") from None
                    denied = acquisition_denied(exc, unauthenticated_cli=True)
                    acquisition(source_path, "finish", outcome="denied" if denied else "failed", detail=safe_error(exc))
                    return {"status": "blocked" if denied else "needs_media", "route": None if denied else "B", "source": str(source_path), "error": safe_error(exc), "download_seconds": round(time.perf_counter() - stage, 3)}
        data.update(id=note_id(data["url"]), title=clean_title, multi_speaker_hint=hint, output_dir=str(output_dir))
        data.setdefault("started_at_epoch", time.time())
        timings["download"] = round(time.perf_counter() - stage, 3)

        raw_exp = data.get("duration") if isinstance(data.get("duration"), (int, float)) and data["duration"] > 0 else None
        try:
            tx = transcribe_and_merge(media, work, speakers=use_speakers, expected_duration=float(raw_exp) if raw_exp else None, replacing=replacing_media, runner=run_asr)
        except NoSpeechDetected as exc:
            timings["prepare_total"] = round(time.perf_counter() - started, 3)
            data.update(status="no_speech", media=str(media), media_sig=media_signature(media), note=str(exc), timings=timings)
            write_json(manifest, data)
            return {"status": "no_speech", "manifest": str(manifest), "id": data["id"], "note": str(exc)}
        timings.update(tx["timings"], prepare_total=round(time.perf_counter() - started, 3))
        if tx["replaced_invalid"]:
            return {"status": "invalid_draft", "manifest": str(manifest), "attempted_media": str(media), "invalid_draft": tx["invalid_draft"], "draft_quality": tx["draft_quality"], "timings": timings}
        if replacing_media:
            for k in ("verified_silence", "verified_silence_sig"):
                data.pop(k, None)
            if manifest.exists():
                preserved = read_json(manifest)
                for k in ("recovery_used", "excerpt_retries", "acquisition"):
                    if k in preserved and k not in data:
                        data[k] = preserved[k]
        draft, quality = Path(tx["draft"]), tx["draft_quality"]
        data.update(media=str(media), media_sig=media_signature(media), duration=tx["duration"], asr=tx["asr"], speaker_count=tx["speaker_count"], diarized=use_speakers)
    elif data["content_type"] in ("图文", "纯文字"):
        blocks = [str(data.get("text") or "")]
        image_texts, expected_imgs = data.get("image_texts") or [], data.get("expected_image_count")
        if isinstance(expected_imgs, int) and expected_imgs > 0 and len(image_texts) != expected_imgs:
            extra_warnings.append(f"图文张数提示：预期 {expected_imgs} 张，传入 {len(image_texts)} 项，请核对首图封面与图序")
        if data["content_type"] == "图文" and image_texts:
            blocks = [f"## 笔记正文\n\n{data['text'].strip()}"] if str(data.get("text") or "").strip() else []
            blocks.extend(f"## 【图{i}】\n\n{str(text).strip()}" for i, text in enumerate(image_texts, 1) if str(text).strip())
        body = "\n\n".join(b.strip() for b in blocks if b.strip())
        if not body.strip():
            raise ValueError("没有取得正文")
        draft = work / "draft.txt"
        draft.write_text(body + "\n", encoding="utf-8")
        quality = inspect_draft_quality(body)
        timings["prepare_total"] = round(time.perf_counter() - started, 3)
    else:
        raise ValueError("content_type 只能为视频、图文或纯文字")

    data.update(status="prepared" if quality["usable"] else "invalid_draft", draft=str(draft), draft_quality=quality, work_dir=str(work), timings=timings)
    if extra_warnings:
        data["warnings"] = extra_warnings
    write_json(manifest, data)
    ref_text = str(data.get("text") or "").strip()
    return {
        "status": data["status"], "manifest": str(manifest), "draft": str(draft),
        "multi_speaker_hint": data["multi_speaker_hint"], "draft_quality": quality,
        "warnings": extra_warnings, "timings": data["timings"],
        **({"reference_text": ref_text[:500]} if ref_text else {}),
    }


def finalize(manifest: Path, reviewed: Path, tags: list[str] | None = None, output_dir: Path | None = None, title_override: str | None = None, verified_silence: bool = False) -> dict:
    data = read_json(manifest)
    target_dir = Path(output_dir or data.get("output_dir") or "").expanduser().resolve()
    if not str(target_dir):
        raise ValueError("保存到哪个文件夹？")
    existing = find_existing_work(target_dir, data["url"])
    replace = replacement({**data, "output_dir": str(target_dir)}, existing)
    return finalize_manifest_note(manifest, reviewed, platform="小红书", output_dir=target_dir, tags=tags, title_override=title_override, verified_silence=verified_silence, replace_path=replace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    cp = sub.add_parser("check"); cp.add_argument("--output-dir", type=Path, required=True); cp.add_argument("--speakers", action="store_true")
    prep = sub.add_parser("prepare"); prep.add_argument("--source", type=Path, required=True); prep.add_argument("--work-dir", type=Path, default=None); prep.add_argument("--speakers", action="store_true")
    sub.add_parser("diarize").add_argument("--manifest", type=Path, required=True)
    retry = sub.add_parser("retry-excerpt"); retry.add_argument("--manifest", type=Path, required=True); retry.add_argument("--clip", type=float, nargs=2, required=True, metavar=("START", "END"))
    done = sub.add_parser("finalize"); done.add_argument("--manifest", type=Path, required=True); done.add_argument("--reviewed", type=Path, required=True)
    done.add_argument("--output-dir", type=Path); done.add_argument("--tags", nargs="+"); done.add_argument("--title"); done.add_argument("--verified-silence", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "check":
            result = shared_check_runtime([args.output_dir], executable, speakers=args.speakers, downloader=True)
        elif args.action == "prepare":
            result = prepare(args.source, speakers=args.speakers, work_dir=args.work_dir)
        elif args.action == "diarize":
            result = diarize_existing(args.manifest)
        elif args.action == "retry-excerpt":
            result = retry_excerpt(args.manifest, *args.clip)
        else:
            result = finalize(args.manifest, args.reviewed, tags=args.tags, output_dir=args.output_dir, title_override=args.title, verified_silence=args.verified_silence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(result.get("status") in ("needs_media", "invalid_draft", "failed"))
    except Exception as exc:
        error = safe_error(exc)
        blocked = args.action == "check" or is_environment_error(exc)
        print(json.dumps({"status": "environment_blocked" if blocked else "failed", "error": error}, ensure_ascii=False))
        return 2 if blocked else 1


if __name__ == "__main__":
    sys.exit(main())
