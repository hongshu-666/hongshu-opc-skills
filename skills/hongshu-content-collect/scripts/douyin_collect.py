#!/usr/bin/env python3
"""Prepare Douyin media/image-text drafts and save quality-gated Markdown notes."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_common import (
    NoSpeechDetected, acquisition, check_runtime as shared_check_runtime, clean_topic_title, diarize_existing,
    executable, fetch_verified_media, finalize_manifest_note, find_existing_work, has_multi_speaker_hint,
    inspect_draft_quality, is_environment_error, media_signature, merge_transcript, normalize_published_date,
    probe_media, read_json, run_asr, safe_error, shared_retry_excerpt as retry_excerpt, transcribe_and_merge, write_json,
)

ID_RE = re.compile(r"(?:video|note)/(\d+)|\b(\d{15,22})\b")


def item_id(value: str | dict[str, Any]) -> str:
    if isinstance(value, dict) and value.get("id"):
        return str(value["id"])
    match = ID_RE.search(str(value))
    if not match:
        raise RuntimeError(f"无法识别作品 ID: {value}")
    return match.group(1) or match.group(2)


def canonical_url(info: dict[str, Any], iid: str) -> str:
    raw = str(info.get("webpage_url") or info.get("url") or "")
    kind = "note" if f"/note/{iid}" in raw else "video"
    return f"https://www.douyin.com/{kind}/{iid}"


def import_media(payload_path: Path, output: Path) -> dict[str, Any]:
    data = read_json(payload_path)
    if data.get("status") != 200 or not data.get("base64"):
        raise RuntimeError(f"浏览器导出载荷不可用: {data.get('status')}")
    body = base64.b64decode(data["base64"], validate=True)
    if not body or (data.get("bytes") and len(body) != int(data["bytes"])):
        raise RuntimeError("浏览器导出字节数不完整")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    mfile = output.parent / "manifest.json"
    mdata = read_json(mfile) if mfile.is_file() else {}
    exp_dur = mdata.get("expected_duration") if mdata.get("expected_duration") else mdata.get("duration")
    attr_list = mdata.get("attributed_urls")
    used_url = str(data.get("url") or "")
    strict_dur = bool(attr_list is not None and (used_url not in attr_list if used_url else not attr_list))
    part = output.with_suffix(output.suffix + ".part")
    part.write_bytes(body)
    try:
        probed = probe_media(part, require_audio=True, expected_duration=float(exp_dur) if exp_dur else None, strict_duration=strict_dur)
    except Exception as exc:
        part.unlink(missing_ok=True)
        if mfile.is_file():
            attempts = (mdata.get("acquisition") or {}).get("attempts") or []
            if attempts and attempts[-1].get("outcome") == "pending":
                acquisition(mfile, "finish", outcome="failed", detail=safe_error(exc))
        raise
    part.replace(output)
    if mfile.is_file():
        attempts = (read_json(mfile).get("acquisition") or {}).get("attempts") or []
        if attempts and attempts[-1].get("outcome") == "pending":
            acquisition(mfile, "finish", outcome="success", media=output)
    return {"status": "imported", "media": str(output), "bytes": len(body), "duration": probed["duration"], "streams": probed["streams"]}


def _select_video(info: dict[str, Any], iid: str) -> dict[str, Any] | None:
    raw_videos = [v for v in (info.get("videos") or []) if isinstance(v, dict) and (str(v.get("src", "")).startswith(("https://", "blob:")) or v.get("sources"))]
    matched = []
    for v in raw_videos:
        all_u = [str(v.get("src") or ""), *(str(s or "") for s in (v.get("sources") or []))]
        vids = {v_id for u in all_u if u for v_id in parse_qs(urlsplit(u).query).get("__vid", [])}
        if not vids or iid in vids:
            matched.append((iid in vids, bool(v.get("active")), isinstance(v.get("duration"), (int, float)) and v["duration"] > 0, v))
    if not matched:
        return None
    for idx in (0, 1, 2):
        narrowed = [item for item in matched if item[idx]]
        if len(narrowed) == 1:
            return narrowed[0][3]
        if narrowed:
            matched = narrowed
    if len(matched) == 1:
        return matched[0][3]
    raise RuntimeError("检测到多个活跃或已加载播放器且无法唯一锁定当前作品，请只传入当前主播放器")


def _candidate_urls(info: dict[str, Any], active_video: dict[str, Any] | None = None, iid: str | None = None, *, out_attributed: set[str] | None = None) -> list[str]:
    work_iid = iid or (item_id(info if info.get("id") else info["url"]) if (info.get("id") or info.get("url")) else "")
    loaded_videos = [v for v in (info.get("videos") or []) if isinstance(v, dict) and (str(v.get("src", "")).startswith(("https://", "blob:")) or v.get("sources"))]
    if active_video is None and loaded_videos and work_iid:
        active_video = _select_video(info, work_iid)
    raw: list[Any] = []
    active_urls: set[str] = set()
    if isinstance(active_video, dict):
        for u in [*(active_video.get("sources") or []), active_video.get("src")]:
            su = str(u or "").strip()
            if su.startswith(("https://", "http://")):
                active_urls.add(su)
                raw.append(su)
    active_vids = {vid for u in active_urls for vid in parse_qs(urlsplit(u).query).get("video_id", []) if vid}
    other_vids = {
        vid for v in loaded_videos if v is not active_video
        for u in [str(v.get("src") or ""), *(str(s or "") for s in (v.get("sources") or []))]
        for vid in parse_qs(urlsplit(u).query).get("video_id", []) if vid
    } - active_vids
    for key in ("audio_url", "audioUrls", "play_url", "play_urls", "source_urls", "sourceUrls", "media_url", "media_urls"):
        val = info.get(key)
        raw.extend([val] if isinstance(val, str) else (val if isinstance(val, list) else []))
    foreign_seen = any(
        work_iid and (vids := parse_qs(urlsplit(u).query).get("__vid", [])) and work_iid not in vids
        for v in loaded_videos for u in [str(v.get("src") or ""), *(str(s or "") for s in (v.get("sources") or []))]
    )
    seen: list[str] = []
    attr_set: set[str] = set()
    for item in raw:
        u = str(item or "").strip()
        if not u.startswith(("https://", "http://")) or u in seen:
            continue
        q = parse_qs(urlsplit(u).query)
        vids, uvids = q.get("__vid", []), q.get("video_id", [])
        if (work_iid and vids and work_iid not in vids) or (active_vids and uvids and not (set(uvids) & active_vids)) or (other_vids and uvids and bool(set(uvids) & other_vids)):
            foreign_seen = True
            continue
        seen.append(u)
        if u in active_urls or (bool(work_iid) and work_iid in vids) or (bool(active_vids) and bool(set(uvids) & active_vids)):
            attr_set.add(u)
    unattr_audio_paths = {urlsplit(u).path for u in seen if u not in attr_set and "media-audio-und-mp4a" in u}
    allow_unattr = len(loaded_videos) <= 1 and not foreign_seen and len(unattr_audio_paths) <= 1
    filtered = [u for u in seen if u in attr_set or allow_unattr]
    if out_attributed is not None:
        out_attributed.update(attr_set)
    return sorted(
        filtered,
        key=lambda u: (
            0 if (not re.search(r"[?&](?:bytestr|range)=", u, re.I) and u in attr_set) else (1 if not re.search(r"[?&](?:bytestr|range)=", u, re.I) else 2),
            0 if "media-audio-und-mp4a" in u else (1 if "/aweme/v1/play/" in u else 2),
        ),
    )


def media_script(source: Path, output: Path) -> dict[str, Any]:
    page = read_json(source)
    iid = item_id(page["url"])
    video = _select_video(page, iid)
    if video is None:
        raise RuntimeError("未检测到本作品有效播放器")
    urls = _candidate_urls(page, active_video=video, iid=iid)
    if not urls:
        raise RuntimeError("未确认可核实的 https 音视频地址，请从 <video><source> 或 performance 资源提取")
    script = """async () => {
  if (location.href.split(/[?#]/)[0] !== %s ||
      !Array.from(document.querySelectorAll('video')).some(v => v.currentSrc === %s))
    return {status: 'page_mismatch'};
  let last = 0;
  for (const u of %s) {
    const r = await fetch(u, {credentials: 'omit'});
    last = r.status;
    if (r.status !== 200) continue;
    const a = new Uint8Array(await r.arrayBuffer()), parts = [];
    for (let i = 0; i < a.length; i += 32768)
      parts.push(String.fromCharCode(...a.subarray(i, i + 32768)));
    return {status: 200, url: u, bytes: a.byteLength, base64: btoa(parts.join(''))};
  }
  return {status: last || 'fetch_failed'};
} """ % (json.dumps(page["url"].split("?")[0].split("#")[0]), json.dumps(video["src"]), json.dumps(urls))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(script, encoding="utf-8")
    return {"script": str(output), "media_kind": "audio" if any("media-audio" in u for u in urls) else "video", "duration": video.get("duration"), "candidate_count": len(urls)}


def _resolve_work_dir(iid: str, target_out: Path, work_dir: Path | None, info: dict[str, Any]) -> Path:
    raw_wd = work_dir or (Path(info["work_dir"]) if info.get("work_dir") else None)
    if raw_wd is not None:
        base_wd = Path(raw_wd).expanduser().resolve()
        work = base_wd if base_wd.name == iid else (base_wd / iid)
        work.mkdir(parents=True, exist_ok=True)
        return work
    legacy = target_out / ".douyin-reach" / iid
    if (legacy / "manifest.json").is_file():
        return legacy
    try:
        work = (Path(os.environ.get("REACH_DOUYIN_CACHE", "~/.cache/reach-douyin")).expanduser() / iid).resolve()
        work.mkdir(parents=True, exist_ok=True)
        return work
    except OSError:
        work = Path(tempfile.gettempdir()).resolve() / "reach-douyin" / iid
        work.mkdir(parents=True, exist_ok=True)
        return work


def prepare_one(source: Path, output_dir: Path | None = None, speakers: bool = False, work_dir: Path | None = None) -> dict[str, Any]:
    started, started_epoch = time.perf_counter(), time.time()
    info = read_json(source)
    if not isinstance(info, dict) or (not info.get("id") and not info.get("url")):
        raise RuntimeError("source 必须为包含 id 或 url 的 JSON 对象")
    iid = item_id(info if info.get("id") else info["url"])
    canon_url = canonical_url(info, iid)
    target_out = output_dir or (Path(info["output_dir"]) if info.get("output_dir") else None)
    if target_out is None:
        raise RuntimeError("保存到哪个文件夹？请提供 --output-dir 或 source.output_dir")
    target_out = Path(target_out).expanduser().resolve()
    if not info.get("replace_existing") and (existing := find_existing_work(target_out, canon_url)):
        return {"status": "existing_needs_format_review", "id": iid, "url": canon_url, "output": str(existing), "output_dir": str(target_out)}

    raw_media = str(info.get("media") or "").strip()
    explicit_media: Path | None = None
    if raw_media:
        explicit_media = Path(raw_media).expanduser()
        if not explicit_media.is_absolute():
            raise RuntimeError("source.media 必须为本地绝对路径")
        explicit_media = explicit_media.resolve()

    work = _resolve_work_dir(iid, target_out, work_dir, info)
    manifest = work / "manifest.json"
    prior: dict[str, Any] = {}
    replacing_media = False
    if manifest.exists():
        prior = read_json(manifest)
        if (prior.get("id") and str(prior["id"]) != iid) or (prior.get("work_dir") and Path(prior["work_dir"]).resolve() != work.resolve()):
            raise RuntimeError("现有结果与本次作品不匹配")
        if explicit_media is not None:
            old_media = Path(prior["media"]).resolve() if prior.get("media") else None
            new_sig = media_signature(explicit_media) if (explicit_media.is_file() and explicit_media.stat().st_size) else None
            replacing_media = (old_media != explicit_media) or bool(new_sig and prior.get("media_sig") and prior["media_sig"] != new_sig)
        if prior.get("id") and (prior.get("process_root") != str(target_out) or prior.get("output_dir") != str(target_out)):
            prior["process_root"] = prior["output_dir"] = str(target_out)
            if prior.get("status") == "saved" and Path(prior.get("draft", "")).is_file():
                prior["status"] = "prepared"
                prior.pop("output", None)
            write_json(manifest, prior)
        if not replacing_media:
            if prior.get("status") == "prepared" and Path(prior.get("draft", "")).is_file():
                quality = inspect_draft_quality(Path(prior["draft"]).read_text(encoding="utf-8"))
                if not quality["usable"]:
                    prior.update(status="invalid_draft", draft_quality=quality)
                    write_json(manifest, prior)
                    return prior
                if speakers and not prior.get("diarized"):
                    diar_res = diarize_existing(manifest)
                    return read_json(manifest) if diar_res.get("status") == "diarized" else diar_res
                return prior
            same_out = bool(prior.get("output")) and Path(prior["output"]).parent.resolve() == target_out
            if prior.get("status") in ("invalid_draft", "no_speech") or prior.get("recovery_used") or (prior.get("status") == "saved" and same_out and Path(prior["output"]).is_file()):
                return prior

    raw_title = str(info.get("item_title") or info.get("title") or "")
    title = clean_topic_title(raw_title) or raw_title.strip()
    description = str(info.get("description") or info.get("text") or "")
    author = str(info.get("channel") or info.get("uploader") or info.get("artist") or info.get("author") or "")
    pub_val, _, _ = normalize_published_date(info.get("timestamp") if info.get("timestamp") not in (None, "") else (info.get("upload_date") or info.get("published")))
    content_type = info.get("content_type") or ("图文" if info.get("image_texts") and not info.get("media") else "视频")
    if content_type not in ("视频", "图文", "纯文字"):
        raise RuntimeError("content_type 只能为视频、图文或纯文字")

    timings: dict[str, float] = {}
    result: dict[str, Any] = {
        **prior, **({"acquisition": info["acquisition"]} if "acquisition" in info and "acquisition" not in prior else {}),
        "status": "prepared", "id": iid, "url": canon_url, "title": title,
        "title_evidence": info.get("title_evidence") or raw_title, "title_generated": bool(info.get("title_generated", False)),
        "description": description, "author": author, "published": pub_val,
        "content_type": "视频" if content_type == "视频" else "图文", "like_count": info.get("like_count"),
        "multi_speaker_hint": has_multi_speaker_hint(raw_title, description),
        "work_dir": str(work), "process_root": str(target_out), "output_dir": str(target_out), "started_at_epoch": started_epoch, "manifest": str(manifest),
        **({"tags": info["tags"]} if info.get("tags") else {}),
    }

    if content_type in ("图文", "纯文字"):
        blocks = [f"## 笔记正文\n\n{description.strip()}"] if description.strip() else []
        if content_type == "图文" and info.get("image_texts"):
            blocks.extend(f"## 【图{i}】\n\n{str(text).strip()}" for i, text in enumerate(info["image_texts"], 1) if str(text).strip())
        elif not info.get("image_texts") and description.strip():
            blocks = [description.strip()]
        body = "\n\n".join(b.strip() for b in blocks if b.strip())
        if not body.strip():
            raise RuntimeError("图文／纯文字缺少可用正文")
        draft = work / "draft.txt"
        draft.write_text(body + "\n", encoding="utf-8")
        timings["prepare_total"] = round(time.perf_counter() - started, 3)
        result.update(draft=str(draft), draft_quality=inspect_draft_quality(body), timings=timings)
        write_json(manifest, result)
        return result

    active_video = _select_video(info, iid) if info.get("videos") else None
    raw_dur = info.get("duration") if isinstance(info.get("duration"), (int, float)) and info["duration"] > 0 else (
        active_video.get("duration") if active_video and isinstance(active_video.get("duration"), (int, float)) and active_video["duration"] > 0 else None
    )
    expected_dur = float(raw_dur) if raw_dur is not None else None
    attr_urls: set[str] = set()
    candidates = _candidate_urls(info, active_video=active_video, iid=iid, out_attributed=attr_urls)
    if explicit_media is not None:
        media = explicit_media
        if replacing_media and (not media.is_file() or not media.stat().st_size):
            raise RuntimeError("替换媒体文件不存在或为空，保留原转写资料")
    elif prior.get("media") and Path(prior["media"]).is_file():
        media = Path(prior["media"]).resolve()
    elif candidates:
        media = (work / ("media.m4a" if any("media-audio" in u for u in candidates) else "media.mp4")).resolve()
    else:
        raise RuntimeError("视频 source 需提供已下载的本地 media，或从 <video><source>／performance 提取的 audioUrls／source_urls")
    if info.get("media_incomplete") or result.get("acquisition", {}).get("blocked"):
        raise RuntimeError("已知媒体不完整或获取已受限；不作为完整录入")

    media_kind = info.get("media_kind")
    if not media.is_file() or not media.stat().st_size:
        if not candidates:
            raise RuntimeError("没有已下载的非空媒体")
        write_json(manifest, result)
        dl_stage = time.perf_counter()
        try:
            dl = fetch_verified_media(candidates, "douyin", media, state_path=manifest, route="auto", require_audio=True, expected_duration=expected_dur, attributed_urls=attr_urls)
        except Exception as exc:
            result["acquisition"] = read_json(manifest).get("acquisition", {})
            script_out: str | None = None
            script_urls = [u for u in candidates if u in attr_urls] if attr_urls else candidates
            if active_video is not None and script_urls:
                try:
                    obs = work / "observation.json"
                    write_json(obs, {"url": result["url"], "videos": [active_video], "audioUrls": script_urls})
                    media_script(obs, work / "media.js")
                    script_out = str(work / "media.js")
                except Exception:
                    pass
            timings["prepare_total"] = round(time.perf_counter() - started, 3)
            result.update(
                status="needs_media", route="B", error=safe_error(exc), candidate_urls=candidates,
                attributed_urls=sorted(attr_urls), expected_duration=expected_dur, import_target=str(media),
                **({"media_script": script_out} if script_out else {}), timings=timings,
            )
            write_json(manifest, result)
            return result
        result["acquisition"] = read_json(manifest).get("acquisition", {})
        timings["download"] = round(time.perf_counter() - dl_stage, 3)
        result["duration"] = dl.get("duration") or expected_dur
        media_kind = media_kind or ("audio" if "video" not in dl.get("streams", []) else "video")
    else:
        strict_local = bool(expected_dur and not attr_urls and candidates and explicit_media is None)
        probed = probe_media(media, require_audio=True, expected_duration=expected_dur, strict_duration=strict_local)
        result["duration"] = probed.get("duration") or expected_dur
        media_kind = media_kind or ("audio" if "video" not in probed.get("streams", []) else "video")
    if media_kind not in ("audio", "video"):
        raise RuntimeError("source.media_kind 必须为 audio 或 video")

    use_speakers = bool(speakers or info.get("speakers"))
    result.update(media_kind=media_kind, media=str(media), media_sig=media_signature(media), duration=result.get("duration") or expected_dur)
    try:
        tx = transcribe_and_merge(media, work, speakers=use_speakers, expected_duration=result["duration"], replacing=replacing_media, runner=run_asr)
    except NoSpeechDetected as exc:
        timings["prepare_total"] = round(time.perf_counter() - started, 3)
        result.update(status="no_speech", note=str(exc), timings=timings)
        write_json(manifest, result)
        return result

    timings.update(tx["timings"], prepare_total=round(time.perf_counter() - started, 3))
    if tx["replaced_invalid"]:
        return {**prior, "status": "invalid_draft", "attempted_media": str(media), "invalid_draft": tx["invalid_draft"], "draft_quality": tx["draft_quality"], "timings": timings}
    if replacing_media:
        for k in ("output", "note", "error", "verified_silence", "verified_silence_sig"):
            result.pop(k, None)
    quality = tx["draft_quality"]
    result.update(status="prepared" if quality["usable"] else "invalid_draft", asr=tx["asr"], draft=tx["draft"], draft_quality=quality, speaker_count=tx["speaker_count"], duration=tx["duration"] or result["duration"], diarized=use_speakers, timings=timings)
    write_json(manifest, result)
    return result


def recover(manifest: Path) -> dict[str, Any]:
    started = time.perf_counter()
    data = read_json(manifest)
    work, media = Path(data["work_dir"]), Path(data["media"])
    if work.resolve() != manifest.parent.resolve() or not media.is_file() or not (work / "asr.json").is_file():
        raise RuntimeError("请先将完整过程目录还原原位；恢复所需媒体或原始结果缺失")
    if data.get("recovery_used"):
        raise RuntimeError("本篇整篇恢复已用过一次，停止，不换模型或重新下载")
    data.update(status="failed", recovery_used=True)
    write_json(manifest, data)
    (work / "asr-invalid.json").write_bytes((work / "asr.json").read_bytes())
    asr_path, _ = run_asr(media, work, executable, previous=False)
    rows = read_json(work / "speakers.json") if (work / "speakers.json").is_file() else None
    body, spk = merge_transcript(read_json(asr_path), rows, data.get("duration"), include_timestamps=False)
    draft = work / "draft.txt"
    draft.write_text(body + "\n", encoding="utf-8")
    quality = inspect_draft_quality(body)
    data.update(draft=str(draft), draft_quality=quality, speaker_count=spk, status="prepared" if quality["usable"] else "invalid_draft")
    data.setdefault("timings", {})["recovery"] = round(time.perf_counter() - started, 3)
    write_json(manifest, data)
    return data


def finalize(manifest_path: Path, reviewed_path: Path, output_dir: Path | None = None, title_override: str | None = None, published_override: str | None = None, tags_override: list[str] | None = None, verified_silence: bool = False) -> dict[str, Any]:
    return finalize_manifest_note(
        manifest_path, reviewed_path, platform="抖音", output_dir=output_dir, tags=tags_override,
        title_override=title_override, published_override=published_override, verified_silence=verified_silence,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    c = sub.add_parser("check"); c.add_argument("--output-dir", type=Path, required=True); c.add_argument("--speakers", action="store_true")
    im = sub.add_parser("import-media"); im.add_argument("--payload", type=Path, required=True); im.add_argument("--output", type=Path, required=True)
    ms = sub.add_parser("media-script"); ms.add_argument("--source", type=Path, required=True); ms.add_argument("--output", type=Path, required=True)
    for cmd_name in ("prepare", "transcribe"):
        p = sub.add_parser(cmd_name); p.add_argument("--source", type=Path, required=True); p.add_argument("--work-dir", type=Path); p.add_argument("--output-dir", type=Path); p.add_argument("--speakers", action="store_true")
    sub.add_parser("diarize").add_argument("--manifest", type=Path, required=True)
    sub.add_parser("recover").add_argument("--manifest", type=Path, required=True)
    re_p = sub.add_parser("retry-excerpt"); re_p.add_argument("--manifest", type=Path, required=True); re_p.add_argument("--clip", type=float, nargs=2, required=True, metavar=("START", "END"))
    fin = sub.add_parser("finalize"); fin.add_argument("--manifest", type=Path, required=True); fin.add_argument("--reviewed", type=Path, required=True)
    fin.add_argument("--output-dir", type=Path); fin.add_argument("--tags", nargs="+"); fin.add_argument("--title"); fin.add_argument("--published"); fin.add_argument("--verified-silence", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "check":
            result: Any = shared_check_runtime([args.output_dir], executable, speakers=args.speakers)
        elif args.action == "import-media":
            result = import_media(args.payload, args.output)
        elif args.action == "media-script":
            result = media_script(args.source, args.output)
        elif args.action in ("prepare", "transcribe"):
            result = prepare_one(args.source, args.output_dir, speakers=args.speakers, work_dir=args.work_dir)
        elif args.action == "diarize":
            result = diarize_existing(args.manifest)
        elif args.action == "retry-excerpt":
            result = retry_excerpt(args.manifest, *args.clip)
        elif args.action == "recover":
            result = recover(args.manifest)
        else:
            result = finalize(args.manifest, args.reviewed, args.output_dir, args.title, args.published, args.tags, verified_silence=args.verified_silence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in ("needs_media", "invalid_draft", "failed") else 0
    except Exception as exc:
        blocked = args.action == "check" or is_environment_error(exc)
        print(json.dumps({"status": "environment_blocked" if blocked else "failed", "error": safe_error(exc)}, ensure_ascii=False, indent=2))
        return 2 if blocked else 1


if __name__ == "__main__":
    sys.exit(main())
