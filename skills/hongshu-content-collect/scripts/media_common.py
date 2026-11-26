#!/usr/bin/env python3
"""Shared offline ASR, optional diarization, media fetch, quality gate, and note saver."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
from urllib.parse import parse_qs, unquote, urlsplit
import urllib.request
import wave
from zoneinfo import ZoneInfo

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
PLATFORM_REFERERS = {"douyin": "https://www.douyin.com/", "xiaohongshu": "https://www.xiaohongshu.com/", "bilibili": "https://www.bilibili.com/"}
PLATFORM_ORIGINS = {"douyin": "https://www.douyin.com", "xiaohongshu": "https://www.xiaohongshu.com", "bilibili": "https://www.bilibili.com"}
VALID_PLATFORMS = {"抖音", "B站", "小红书", "微信公众号", "知乎"}
MULTI_SPEAKER_RE = re.compile(r"对谈|访谈|专访|对话|连麦|采访|问答|街访|帮粉丝|播客|嘉宾|主持人|共创")
BAD_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
CONTROL_WS_RE = re.compile(r"[\u200b-\u200f\ufeff]")
PLATFORM_BOT_RE = re.compile(r"(?<![A-Za-z0-9._-])@(?:抖音小助手|DOU\+小助手|巨量引擎小助手|小红书(?:成长|创作)?助手|薯队长|哔哩哔哩创作中心)\s*", re.I)
TRAILING_ATTACH_RE = re.compile(r"(?:[\s，,、|｜\-—]*(?:#[^\s#]+|(?<![A-Za-z0-9._-])@[^\s#@，。！？!?；;：:、\"'”’()（）\[\]【】]+))+\s*$")
CJK_BEFORE_INLINE_MENTION_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=@[^\s#@，。！？!?；;：:、\"'”’()（）\[\]【】]+)")
INLINE_MENTION_RE = re.compile(r"(?<![A-Za-z0-9._-])@([^\s#@，。！？!?；;：:、\"'”’()（）\[\]【】]+)(?:\s+(?=[\u4e00-\u9fff，。！？!?；;：:、]))?")
TRAILING_SITE_RE = re.compile(r"\s*[-_|｜]\s*(?:抖音|小红书|哔哩哔哩|bilibili|知乎)\s*$", re.I)
LEADING_JUNK_RE = re.compile(r"^[，,、|｜\-—\s:：;；]+")
TRAILING_JUNK_RE = re.compile(r"[，,、|｜\-—\s:：;；]+$")
SILENCE_HALLUCINATION_RE = re.compile(
    r"^(?:优优独播剧场.*|YoYo Television Series.*|请不吝点赞.*订阅.*转发.*|"
    r"字幕由.*提供.*|Subtitles by .*|Amara\.org.*|Thanks for watching[.!]*|"
    r"谢谢(?:大家)?观看[。!！]*)$",
    re.I,
)


class EnvironmentBlocked(RuntimeError):
    pass


class NoSpeechDetected(RuntimeError):
    pass


def read_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, data: dict) -> None:
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def run(argv: list) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in argv], check=True, text=True, capture_output=True,
        encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


SMOKE_KEYWORDS = ("环境", "测试", "通过")


def env_ready_path() -> Path:
    return Path.home() / ".cache/reach-tools/env-ready.json"


def persistent_app_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library/Application Support/HongshuCollect"
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        return base / "HongshuCollect"
    return Path.home() / ".local/share/hongshu-collect"


def dedicated_chrome_profile() -> Path:
    recorded = _recorded_env().get("chrome_profile")
    if recorded and Path(recorded).is_dir():
        return Path(recorded)
    legacy = Path.home() / ".cache/chrome-devtools-mcp/chrome-profile"
    if legacy.is_dir():
        return legacy
    return persistent_app_dir() / "chrome-profile"


def dedicated_chrome_launcher() -> Path:
    system = platform.system()
    if system == "Darwin":
        return persistent_app_dir() / "采集浏览器.app"
    if system == "Windows":
        return persistent_app_dir() / "采集浏览器.lnk"
    return persistent_app_dir() / "open-collect-browser.sh"


def _default_chrome_path() -> str:
    if recorded := _recorded_tool("chrome"):
        return recorded
    system = platform.system()
    if system == "Darwin":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return str(p) if p.is_file() else ""
    if system == "Windows":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                p = Path(root) / "Google/Chrome/Application/chrome.exe"
                if p.is_file():
                    return str(p)
        return ""
    return shutil.which("google-chrome") or shutil.which("chromium") or ""


def _dedicated_profile_candidates() -> list[Path]:
    out: list[Path] = []
    recorded = _recorded_env().get("chrome_profile")
    for cand in (
        Path(recorded) if recorded else None,
        persistent_app_dir() / "chrome-profile",
        Path.home() / ".cache/chrome-devtools-mcp/chrome-profile",
    ):
        if cand is not None and cand not in out:
            out.append(cand)
    return out


def default_work_root(platform_key: str, item_key: str = "") -> Path:
    base = Path.home() / ".cache/reach-tools/work" / platform_key
    target = (base / item_key) if item_key else base
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target.resolve()
    except OSError:
        fallback = Path(tempfile.gettempdir()).resolve() / "reach-tools-work" / platform_key
        if item_key:
            fallback = fallback / item_key
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _probe_local_chrome(port: int | None = None, expected_profile: Path | None = None) -> tuple[dict | None, str]:
    """Return (info, state) where state in ('connected', 'needs_launch', 'needs_permission', 'port_occupied')."""
    profiles = [expected_profile] if expected_profile is not None else []
    for p in _dedicated_profile_candidates():
        if p not in profiles:
            profiles.append(p)
    dap_ws_by_port: dict[int, set[str]] = {}
    candidate_ports: list[int] = []
    for prof in profiles:
        dap = prof / "DevToolsActivePort"
        if dap.is_file():
            try:
                lines = [s.strip() for s in dap.read_text(encoding="utf-8").splitlines() if s.strip()]
                if len(lines) >= 2 and lines[0].isdigit() and lines[1].startswith("/devtools/browser/"):
                    p_num = int(lines[0])
                    if 1 <= p_num <= 65535:
                        dap_ws_by_port.setdefault(p_num, set()).add(lines[1])
                        if p_num not in candidate_ports:
                            candidate_ports.append(p_num)
            except Exception:
                pass
    ps_dedicated: set[int] = set()
    ps_unsafe: set[int] = set()
    ps_foreign: set[int] = set()
    if platform.system() != "Windows":
        try:
            ps_out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=1.5).stdout
            for line in ps_out.splitlines():
                if not re.match(r"^\s*(?:/(?:Applications|Users/[^/\n]+/Applications)/Google Chrome\.app/Contents/MacOS/Google Chrome|/\S+/(?:google-chrome(?:-stable)?|chromium|chrome))(?:\s|$)", line):
                    continue
                m_port = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", line)
                if not m_port:
                    continue
                p_num = int(m_port.group(1))
                if not (1 <= p_num <= 65535):
                    continue
                if re.search(r"\s--no-sandbox(?:\s|$)", line):
                    ps_unsafe.add(p_num)
                elif any(str(prof) in line for prof in profiles):
                    ps_dedicated.add(p_num)
                    if p_num not in candidate_ports:
                        candidate_ports.append(p_num)
                else:
                    ps_foreign.add(p_num)
        except Exception:
            pass
    ports_to_check = [port] if port is not None else candidate_ports
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    saw_permission = False
    saw_occupied = False
    for p_num in ports_to_check:
        try:
            with opener.open(f"http://127.0.0.1:{p_num}/json/version", timeout=1.2) as resp:
                info = json.loads(resp.read().decode("utf-8"))
                if isinstance(info, dict) and info.get("webSocketDebuggerUrl") and re.match(r"^(?:Chrome|Chromium)/", str(info.get("Browser") or "")):
                    ws_path = urlsplit(str(info["webSocketDebuggerUrl"])).path
                    if p_num in ps_unsafe or p_num in ps_foreign:
                        saw_occupied = True
                        continue
                    dap_ws = dap_ws_by_port.get(p_num, set())
                    dap_matched = ws_path in dap_ws
                    ps_matched = (p_num in ps_dedicated) and (not dap_ws or dap_matched)
                    if dap_matched or ps_matched:
                        return {"endpoint": f"http://127.0.0.1:{p_num}", "port": p_num, "browser": info["Browser"]}, "connected"
                    saw_occupied = True
        except PermissionError:
            saw_permission = True
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, PermissionError) or getattr(exc.reason, "errno", None) in (1, 13):
                saw_permission = True
        except OSError as exc:
            if getattr(exc, "errno", None) in (1, 13):
                saw_permission = True
        except Exception:
            pass
    if saw_permission:
        return None, "needs_permission"
    if saw_occupied:
        return None, "port_occupied"
    return None, "needs_launch"


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def env_browser_launcher(chrome_path: str = "", launch: bool = False) -> dict:
    chrome = str(Path(chrome_path).expanduser().resolve()) if chrome_path else _default_chrome_path()
    if not chrome or not Path(chrome).is_file():
        raise EnvironmentBlocked("未找到本机 Google Chrome；请先经用户确认安装官方 Chrome")
    app_dir = persistent_app_dir()
    profile = dedicated_chrome_profile()
    launcher = dedicated_chrome_launcher()
    app_dir.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    meta_path = app_dir / "launcher-meta.json"
    meta = {"chrome": chrome, "profile": str(profile), "port": 0}
    base = {"launcher": str(launcher), "profile": str(profile), "chrome": chrome, "port": 0}
    system = platform.system()
    existing_meta = read_json(meta_path) if meta_path.is_file() else None
    static_match = isinstance(existing_meta, dict) and all(existing_meta.get(k) == v for k, v in meta.items())
    needs_build = (not launcher.exists()) or (not static_match)
    if needs_build:
        try:
            if system == "Darwin":
                cmd = (
                    f"{shlex.quote(chrome)} --user-data-dir={shlex.quote(str(profile))} --profile-directory=Default "
                    f"--remote-debugging-port=0 --mute-audio --no-first-run --no-default-browser-check about:blank >/dev/null 2>&1 &"
                )
                with tempfile.TemporaryDirectory(prefix="hongshu-launcher-") as tmp_dir:
                    compiled = Path(tmp_dir) / launcher.name
                    run(["osacompile", "-o", str(compiled), "-e", f"do shell script {_applescript_string(cmd)}"])
                    if not (compiled / "Contents/MacOS").is_dir():
                        raise RuntimeError("osacompile 未生成有效应用包")
                    sibling_new = app_dir / f".{launcher.name}.new"
                    if sibling_new.exists():
                        shutil.rmtree(sibling_new, ignore_errors=True)
                    try:
                        shutil.copytree(compiled, sibling_new)
                    except Exception:
                        shutil.rmtree(sibling_new, ignore_errors=True)
                        raise
                    backup: Path | None = None
                    if launcher.exists():
                        backup = app_dir / f".{launcher.name}.prev"
                        if backup.exists():
                            shutil.rmtree(backup, ignore_errors=True)
                        launcher.rename(backup)
                    try:
                        sibling_new.rename(launcher)
                    except Exception:
                        if backup is not None and backup.exists() and not launcher.exists():
                            backup.rename(launcher)
                        shutil.rmtree(sibling_new, ignore_errors=True)
                        raise
                    if backup is not None and backup.exists():
                        shutil.rmtree(backup, ignore_errors=True)
            elif system == "Windows":
                args_str = f'--user-data-dir="{profile}" --profile-directory=Default --remote-debugging-port=0 --mute-audio --no-first-run --no-default-browser-check about:blank'
                ps = (
                    "$ws=New-Object -ComObject WScript.Shell;"
                    "$sc=$ws.CreateShortcut($env:REACH_LNK);"
                    "$sc.TargetPath=$env:REACH_CHROME;"
                    "$sc.Arguments=$env:REACH_ARGS;"
                    "$sc.IconLocation=$env:REACH_CHROME+',0';"
                    "$sc.Save()"
                )
                with tempfile.TemporaryDirectory(prefix="hongshu-launcher-") as tmp_dir:
                    staged = Path(tmp_dir) / launcher.name
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True,
                        env={**os.environ, "REACH_LNK": str(staged), "REACH_CHROME": chrome, "REACH_ARGS": args_str},
                    )
                    if not staged.is_file():
                        raise RuntimeError("快捷方式生成失败")
                    sibling_new = app_dir / f".{launcher.name}.new"
                    shutil.copyfile(staged, sibling_new)
                    os.replace(sibling_new, launcher)
            else:
                staged_text = (
                    f"#!/bin/sh\nexec {shlex.quote(chrome)} --user-data-dir={shlex.quote(str(profile))} --profile-directory=Default "
                    f"--remote-debugging-port=0 --mute-audio --no-first-run --no-default-browser-check about:blank >/dev/null 2>&1 &\n"
                )
                launcher.write_text(staged_text, encoding="utf-8")
                launcher.chmod(0o755)
            write_json(meta_path, meta)
        except Exception as exc:
            return {"status": "launcher_build_failed", **base, "message": f"未能生成专用采集浏览器启动器，请勿自行改用其他 Chrome 启动参数：{safe_error(exc)}"}
    if not launch:
        return {"status": "ready", **base}
    live, state = _probe_local_chrome(expected_profile=profile)
    if live:
        return {"status": "connected", **base, **live}
    if state == "needs_permission":
        return {"status": "needs_permission", **base, "message": "当前会话缺少连接本机采集浏览器端口的权限，请申请本机权限后重试，无需重新打开浏览器"}
    if state == "port_occupied":
        return {"status": "port_occupied", **base, "message": "检测到冲突或关闭安全保护（--no-sandbox）的旧浏览器实例，保留现场不强行连接，请先退出旧实例后重试"}
    try:
        if system == "Darwin":
            run(["open", str(launcher)])
        elif system == "Windows":
            subprocess.run(["powershell", "-NoProfile", "-Command", "Start-Process -FilePath $env:REACH_LNK"], check=True, capture_output=True, text=True, env={**os.environ, "REACH_LNK": str(launcher)})
        else:
            subprocess.Popen([str(launcher)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        if is_environment_error(exc):
            return {"status": "needs_permission", **base, "message": f"当前会话无法代开采集浏览器：{safe_error(exc)}"}
        return {"status": "needs_manual_launch", **base, "message": f"未能自动打开采集浏览器，请用户直接点击打开：{launcher}"}
    for _ in range(10):
        time.sleep(0.8)
        live, state = _probe_local_chrome(expected_profile=profile)
        if live:
            return {"status": "connected", **base, **live}
        if state == "needs_permission":
            return {"status": "needs_permission", **base, "message": "采集浏览器可能已启动，但当前会话缺少连接本机端口的权限，请申请本机权限后重试"}
        if state == "port_occupied":
            return {"status": "port_occupied", **base, "message": "检测到非专用浏览器实例占用连接，保留现场不强行连接"}
    return {"status": "needs_manual_launch", **base, "message": f"未能自动连上采集浏览器，请不要改用 --no-sandbox，直接请用户点击打开一次：{launcher}"}


def smoke_audio_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets/asr-smoke.wav"


def _recorded_env() -> dict:
    path = env_ready_path()
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _recorded_tool(name: str) -> str | None:
    recorded = (_recorded_env().get("tools") or {}).get(name)
    return str(recorded) if recorded and Path(recorded).is_file() else None


def _model_weights_present(path: Path, backend: str) -> bool:
    if not path.is_dir():
        return False
    if backend == "mlx":
        cfg = path / "config.json"
        if not cfg.is_file() or cfg.stat().st_size == 0:
            return False
        return any(p.is_file() and p.stat().st_size > 0 and p.suffix in (".npz", ".bin", ".safetensors", ".pt", ".ckpt") for p in path.iterdir())
    required = ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")
    if any(not (path / n).is_file() or (path / n).stat().st_size == 0 for n in required):
        return False
    return (path / "model.bin").stat().st_size == 1617884929


def executable(name: str) -> str:
    if recorded := _recorded_tool(name):
        return recorded
    home = Path.home()
    is_win = platform.system() == "Windows"
    suffixes = (".exe", ".cmd", "") if is_win else ("",)
    search_dirs = (
        [home / ".cache/reach-tools/faster-whisper/Scripts", home / ".local/bin", *([Path(local_app) / "Microsoft/WinGet/Links"] if (local_app := os.environ.get("LOCALAPPDATA")) else [])]
        if is_win
        else [home / ".cache/reach-tools/mlx-whisper/bin", home / ".cache/reach-tools/faster-whisper/bin", home / ".local/bin", Path("/opt/homebrew/bin")]
    )
    for directory in search_dirs:
        for suffix in suffixes:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"缺少运行时：{name}")
    return path


def safe_error(exc: Exception) -> str:
    message = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
    cleaned = re.sub(r"https?://\S+", "[URL]", message or type(exc).__name__)
    cleaned = re.sub(r"(?im)^.*(?:authorization|cookie|api[_ -]?key|secret).*$", "[敏感行已隐藏]", cleaned)
    return cleaned.strip()[-1800:]


def work_identity(url: str) -> tuple[str, ...]:
    """Return canonical platform + ID tuple for supported work URLs."""
    u = urlsplit(str(url).replace("&amp;", "&"))
    if u.scheme not in ("http", "https"):
        raise ValueError("仅接受作品网页链接")
    host, path, q = (u.hostname or "").lower(), unquote(u.path), parse_qs(u.query)
    if host in ("douyin.com", "www.douyin.com"):
        m = re.fullmatch(r"/(?:video|note)/(\d+)/?", path)
        if m:
            return ("douyin", m[1])
    if host in ("xiaohongshu.com", "www.xiaohongshu.com"):
        m = re.fullmatch(r"/(?:explore|discovery/item|user/profile/[0-9a-fA-F]{24})/([0-9a-fA-F]{24})/?", path)
        if m:
            return ("xiaohongshu", m[1].lower())
    if host in ("bilibili.com", "www.bilibili.com"):
        m = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av\d+)/?", path)
        part = q.get("p", ["1"])
        if m and len(part) == 1 and part[0].isdigit() and int(part[0]) > 0:
            return ("bilibili", m[1], str(int(part[0])))
    if host in ("zhihu.com", "www.zhihu.com"):
        m = re.fullmatch(r"/question/\d+/answer/(\d+)/?", path)
        if m:
            return ("zhihu-answer", m[1])
    if host == "zhuanlan.zhihu.com":
        m = re.fullmatch(r"/p/(\d+)/?", path)
        if m:
            return ("zhihu-article", m[1])
    if host == "mp.weixin.qq.com":
        keys = ("__biz", "mid", "idx")
        if path.rstrip("/") == "/s" and all(len(q.get(k, [])) == 1 for k in keys):
            return ("weixin", *(q[k][0] for k in keys))
        if re.fullmatch(r"/s/[\w-]+", path):
            return ("weixin-short", path)
    raise ValueError("链接未解析或作品身份不明确；先核实规范链接，不按标题猜配")


def same_work(left: str, right: str) -> bool:
    if left.replace("&amp;", "&") == right.replace("&amp;", "&"):
        return True
    try:
        return work_identity(left) == work_identity(right)
    except ValueError:
        return False


def reach_runtime() -> dict:
    system, arch = platform.system(), platform.machine().lower()
    processor = platform.processor().strip() or "未知"
    apple = system == "Darwin" and arch in ("arm64", "aarch64")
    portable = (system == "Linux" and arch in ("x86_64", "amd64", "aarch64", "arm64")) or (
        system == "Windows" and arch in ("amd64", "x86_64")
    )
    if not (apple or portable):
        raise EnvironmentBlocked(f"未配置支持的系统/运行架构：{system}/{arch}；不自动换后端或启用模拟层")
    home = Path.home() / ".cache"
    python_tail = Path("Scripts/python.exe" if system == "Windows" else "bin/python")
    asr_default = home / "reach-tools/faster-whisper" / python_tail
    backend = "mlx" if apple else "faster-whisper"
    recorded = _recorded_env()
    same_host = (recorded.get("os"), recorded.get("arch"), recorded.get("backend")) == (system, arch, backend)
    rec_model = recorded.get("model_path") if same_host else None
    rec_asr_py = (recorded.get("tools") or {}).get("asr_runtime") if (same_host and not apple) else None
    chosen_model = (
        os.environ.get("REACH_ASR_MODEL")
        or (rec_model if rec_model and Path(rec_model).is_dir() else None)
        or (home / ("reach-models/whisper-large-v3-turbo" if apple else "reach-models/faster-whisper-large-v3-turbo"))
    )
    chosen_asr_py = (
        os.environ.get("REACH_ASR_PYTHON")
        or (rec_asr_py if rec_asr_py and Path(rec_asr_py).is_file() else None)
        or (str(asr_default) if asr_default.is_file() else sys.executable)
    )
    return {
        "os": system, "arch": arch, "processor": processor,
        "cpu_class": "Apple Silicon" if apple else "x86-64（按运行架构）" if arch in ("x86_64", "amd64") else "ARM64（按运行架构）",
        "backend": backend,
        "asr_python": str(Path(chosen_asr_py).expanduser()),
        "model": Path(chosen_model).expanduser().resolve(),
        "speaker_python": str(Path(os.environ.get("REACH_DIARIZATION_PYTHON") or home / "reach-tools/pyannote-community-1" / python_tail).expanduser()),
        "speaker_model": Path(os.environ.get("REACH_DIARIZATION_MODEL") or home / "reach-models/pyannote-community-1").expanduser().resolve(),
        "speaker_device": "mps" if apple else "cpu",
    }


def readable_model_file(path: Path) -> None:
    with path.open("rb") as handle:
        prefix = handle.read(256)
    if not prefix or prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise EnvironmentBlocked(f"模型文件为空或仅为下载指针：{path}")


def check_speaker_files(runtime: dict) -> dict:
    """Read Community-1 config in its own environment without loading model weights."""
    code = r"""import json,sys,yaml
from pathlib import Path
root=Path(sys.argv[1]).resolve()
config=yaml.safe_load((root/'config.yaml').read_text(encoding='utf-8'))
params=config['pipeline']['params']
if config.get('device') not in (None, sys.argv[2]):
    raise ValueError('声纹配置固定了不适用设备；完整性/适配未通过，需获准调整配置')
files=[root/'config.yaml']
for key in ('segmentation','embedding','plda'):
    ref=params.get(key)
    if isinstance(ref,str) and ref.startswith('$model/') and '@' not in ref:
        target=root/ref[len('$model/'):]
    elif isinstance(ref,str) and Path(ref).is_absolute():
        target=Path(ref)
    elif isinstance(ref,dict) and isinstance(ref.get('checkpoint'),str) and Path(ref['checkpoint']).is_absolute() and ref.get('revision') is None:
        target=Path(ref['checkpoint'])/(ref.get('subfolder') or '')
    else:
        raise ValueError(f'{key} 不是可确认的完整本地引用；完整性未核验，不联网补取')
    if key=='plda':
        files.extend([target/'plda.npz',target/'xvec_transform.npz'])
    else:
        files.append(target/'pytorch_model.bin' if target.is_dir() else target)
for path in files:
    with path.open('rb') as handle:
        prefix=handle.read(256)
    if not prefix or prefix.startswith(b'version https://git-lfs.github.com/spec/v1'):
        raise ValueError(f'本地模型文件为空或仅为下载指针：{path}')
print(json.dumps({'path':str(root),'config_references':'checked','files':[str(p) for p in files],'model_load':'not_run'}))
"""
    return json.loads(run([runtime["speaker_python"], "-c", code, str(runtime["speaker_model"]), runtime["speaker_device"]]).stdout)


def speaker_ready_hint(runtime: dict) -> bool:
    """Lightweight non-blocking check whether optional diarization runtime is configured."""
    if not Path(runtime["speaker_python"]).is_file() or not (Path(runtime["speaker_model"]) / "config.yaml").is_file():
        return False
    try:
        check_speaker_files(runtime)
        return True
    except Exception:
        return False


def check_runtime(directories: list, lookup=executable, speakers: bool = False, downloader: bool = False, require_downloader: bool = False, smoke: bool = False) -> dict:
    runtime = reach_runtime()
    errors, details, resolved_tools = [], {}, {"python": sys.executable}

    def inspect(label: str, action) -> None:
        try:
            details[label] = action()
        except Exception as exc:
            msg = str(getattr(exc, "stderr", None) or exc)
            if platform.system() == "Darwin" and re.search(r"Metal|IOAccelerator|kIOGPU|No GPU|GPU|Operation not permitted|Permission denied", msg, re.I):
                msg += "（疑似 macOS 命令沙箱拦截 GPU 或本机权限；请先申请脱离命令沙箱执行后重试，勿误判为缺少硬件或重下模型）"
            errors.append(f"{label}：{msg}")

    def writable(directory: Path | str) -> str:
        target = Path(directory).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        probe_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".reach-write-probe-", dir=target, delete=False) as probe:
                probe_path = Path(probe.name)
                probe.write(b"probe")
                probe.flush()
                os.fsync(probe.fileno())
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)
        return str(target)

    def model_files(path: Path, mlx: bool = False) -> dict:
        names = ("config.json",) if mlx else ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")
        files = [path / name for name in names]
        if mlx:
            weights = [p for p in path.iterdir() if p.is_file() and p.suffix in (".npz", ".bin", ".safetensors", ".pt", ".ckpt")]
            if not weights:
                raise EnvironmentBlocked(f"缺少本地模型权重：{path}")
            files.extend(weights)
        for file in files:
            readable_model_file(file)
        if not mlx:
            weight = path / "model.bin"
            if weight.stat().st_size != 1617884929:
                raise EnvironmentBlocked("CT2 权重大小不符；需要已指定 revision 的完整 FP16 large-v3-turbo，不换小模型或量化权重")
            with weight.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da":
                raise EnvironmentBlocked("CT2 权重 SHA256 不符；请按指定模型 revision 核对获准配置，不自动重新下载")
        return {"path": str(path), "files_readable": len(files), "model_load": "not_run"}

    if sys.version_info < (3, 11):
        errors.append("主脚本需要 Python 3.11+，请使用已配置解释器")
    inspect("timezone", lambda: str(ZoneInfo("Asia/Shanghai")))
    for index, directory in enumerate(directories):
        inspect(f"directory_{index + 1}", lambda directory=directory: writable(directory))

    def _inspect_bin(name: str, args: list[str]) -> dict:
        bin_path = lookup(name)
        ver = run([bin_path, *args]).stdout.splitlines()[0]
        resolved_tools[name] = bin_path
        return {"path": bin_path, "version": ver}

    for name in ("ffmpeg", "ffprobe"):
        inspect(name, lambda name=name: _inspect_bin(name, ["-version"]))
    inspect("curl", lambda: _inspect_bin("curl", ["--fail-with-body", "--version"]))
    if require_downloader:
        inspect("yt_dlp", lambda: _inspect_bin("yt-dlp", ["--version"]))
    elif downloader:
        try:
            details["yt_dlp"] = _inspect_bin("yt-dlp", ["--version"])
            details["yt_dlp_ready"] = True
        except Exception:
            details["yt_dlp_ready"] = False
    inspect("asr_model", lambda: model_files(runtime["model"], mlx=runtime["backend"] == "mlx"))
    if runtime["backend"] == "mlx":
        def _check_mlx() -> dict:
            cli = lookup("mlx_whisper")
            resolved_tools["mlx_whisper"] = resolved_tools["asr_runtime"] = cli
            return {"cli": cli, "help": bool(run([cli, "--help"]).stdout)}
        inspect("asr_runtime", _check_mlx)
    else:
        probe = (
            "import json,sys,platform,importlib.metadata as m; import faster_whisper,ctranslate2,av,onnxruntime,tokenizers; "
            "assert m.version('faster-whisper') == '1.2.1' and m.version('ctranslate2') == '4.6.0', '需要已指定的 faster-whisper 1.2.1 / CTranslate2 4.6.0；先说明并获准配置，不自动改版本'; "
            "assert 'float32' in ctranslate2.get_supported_compute_types('cpu'); "
            "print(json.dumps({'python':sys.executable,'os':platform.system(),'arch':platform.machine(),'versions':{n:m.version(n) for n in ('faster-whisper','ctranslate2','av','onnxruntime','tokenizers')}}))"
        )
        def _check_faster() -> dict:
            info = json.loads(run([runtime["asr_python"], "-c", probe]).stdout)
            resolved_tools["asr_runtime"] = info["python"]
            return info
        inspect("asr_runtime", _check_faster)
    if speakers:
        inspect("speaker_model", lambda: check_speaker_files(runtime))
        probe = (
            "import os; os.environ['HF_HUB_OFFLINE']='1'; os.environ['PYANNOTE_METRICS_ENABLED']='0'; "
            "import json,sys,numpy,torch; from pyannote.audio import Pipeline; device=sys.argv[1]; "
            "assert device != 'mps' or torch.backends.mps.is_available(), 'MPS not available'; "
            "print(json.dumps({'python':sys.executable,'torch':torch.__version__,'device':device}))"
        )
        inspect("speaker_runtime", lambda: json.loads(run([runtime["speaker_python"], "-c", probe, runtime["speaker_device"]]).stdout))
    else:
        details["speaker_ready_hint"] = speaker_ready_hint(runtime)
    if smoke and not errors:
        def _run_smoke() -> dict:
            audio = smoke_audio_path()
            if not audio.is_file():
                raise EnvironmentBlocked(f"缺少固定中文验收音频：{audio}")
            with tempfile.TemporaryDirectory(prefix="reach-smoke-") as td:
                out_json, elapsed = run_asr(audio, Path(td), lookup=lookup)
                text = str(read_json(out_json).get("text") or "").strip()
            compact = re.sub(r"[\s，。！？!?、,.：:；;\"'“”‘’]", "", text)
            if not all(keyword in compact for keyword in SMOKE_KEYWORDS):
                raise EnvironmentBlocked(f"固定短音频转写未包含预期关键词（{''.join(SMOKE_KEYWORDS)}），实得：{text!r}")
            details["asr_model"]["model_load"] = "verified"
            return {"passed": True, "text": text, "elapsed_s": round(elapsed, 2), "audio": "assets/asr-smoke.wav"}
        inspect("asr_smoke", _run_smoke)
    if errors:
        raise EnvironmentBlocked("完整后端检查未通过；先说明用途和拟配置并取得授权，不自动安装或下载：\n" + "\n".join(errors))
    return {
        "status": "ready", "backend": runtime["backend"], "os": runtime["os"], "arch": runtime["arch"],
        "processor": runtime["processor"], "cpu_class": runtime["cpu_class"], "speakers_checked": speakers,
        "model_path": str(runtime["model"]), "resolved_tools": resolved_tools, "checks": details,
        "desktop_browser_note": "抖音／小红书批量清单与媒体取源通过 browser_collect.js 连接本机已运行的专用桌面 Chrome；浏览器连接与读写需另由 browser_collect.js verify 独立验证",
        "scope": "已完成本地依赖与固定中文短音频真实转写校验；需待 browser_collect.js verify 通过后方可统一写入本机就绪记录" if smoke else "仅后端依赖和本地文件检查；浏览器、来源网络、模型加载和完整业务运行不由此证明",
    }


SHARED_TOOL_KEYS = ("chrome", "ffmpeg", "ffprobe", "curl", "yt-dlp", "asr_runtime")


def env_status(agent: str | None = None) -> dict:
    path = env_ready_path()
    if not path.is_file():
        return {"status": "not_ready", "reason": "未找到本机就绪记录", "path": str(path)}
    try:
        data = read_json(path)
        runtime = reach_runtime()
    except Exception as exc:
        return {"status": "not_ready", "reason": safe_error(exc), "path": str(path)}
    if data.get("browser_verified") is not True or data.get("asr_smoke_verified") is not True:
        return {"status": "not_ready", "reason": "浏览器或短音频转写验收尚未同时通过", "path": str(path)}
    if (data.get("os"), data.get("arch"), data.get("backend")) != (runtime["os"], runtime["arch"], runtime["backend"]):
        return {"status": "not_ready", "reason": "系统或架构与就绪记录不匹配", "path": str(path)}
    tools = data.get("tools") or {}
    check_keys = SHARED_TOOL_KEYS if agent else (*SHARED_TOOL_KEYS, "node", "python")
    missing = [key for key in check_keys if not tools.get(key) or not Path(tools[key]).is_file()]
    model_path = data.get("model_path") or ""
    if not model_path or not _model_weights_present(Path(model_path), runtime["backend"]):
        missing.append("model_weights")
    elif Path(model_path).resolve() != runtime["model"]:
        return {"status": "not_ready", "reason": f"当前模型配置（{runtime['model']}）与已验收记录不一致", "path": str(path)}
    if missing:
        return {"status": "not_ready", "reason": f"登记路径或关键权重无效：{', '.join(missing)}", "missing": missing, "path": str(path)}
    effective_tools = dict(tools)
    if agent:
        entry = (data.get("agents") or {}).get(agent) or {}
        agent_node = entry.get("node") or tools.get("node")
        agent_python = entry.get("python") or tools.get("python")
        if not (
            entry.get("browser_verified")
            and entry.get("tools_verified")
            and agent_node and Path(agent_node).is_file()
            and agent_python and Path(agent_python).is_file()
        ):
            shared_only = {k: tools[k] for k in SHARED_TOOL_KEYS if tools.get(k)}
            return {
                "status": "needs_agent_verify", "machine_ready": True, "agent": agent,
                "tools": shared_only, "model_path": model_path,
                "chrome_profile": data.get("chrome_profile") or str(dedicated_chrome_profile()),
                "chrome_launcher": data.get("chrome_launcher") or str(dedicated_chrome_launcher()),
                "path": str(path),
            }
        effective_tools.update(node=agent_node, python=agent_python)
    return {
        "status": "ready", "machine_ready": True, "agent": agent, "tools": effective_tools, "model_path": model_path,
        "chrome_profile": data.get("chrome_profile") or str(dedicated_chrome_profile()),
        "chrome_launcher": data.get("chrome_launcher") or str(dedicated_chrome_launcher()),
        "path": str(path),
    }


def env_mark_ready(browser_proof_path: Path, asr_proof_path: Path | None, reuse_machine_asr: bool, agent: str, chrome_path: str, node_path: str) -> dict:
    browser = read_json(browser_proof_path)
    channel = str(browser.get("channel") or "cdp-script")
    if channel not in ("cdp-script", "host-browser"):
        raise EnvironmentBlocked(f"不支持的浏览器验收通道：{channel}")
    if not (
        browser.get("status") == "verified"
        and browser.get("browser_connected") is True
        and browser.get("page_read_ok") is True
        and browser.get("file_write_ok") is True
        and str(browser.get("page_title") or "").strip()
        and str(browser.get("url_checked") or "").strip()
    ):
        raise EnvironmentBlocked("浏览器读写验收凭证未通过，拒绝写入就绪记录")
    if not Path(chrome_path).is_file():
        raise EnvironmentBlocked(f"指定的 Chrome 路径不存在：{chrome_path}")
    if not Path(node_path).is_file():
        raise EnvironmentBlocked(f"指定的 Node 路径不存在：{node_path}")
    runtime = reach_runtime()
    stamp_path = env_ready_path()
    existing = read_json(stamp_path) if stamp_path.is_file() else {}
    if asr_proof_path is not None:
        asr = read_json(asr_proof_path)
        smoke_info = (asr.get("checks") or {}).get("asr_smoke") or {}
        if not (asr.get("status") == "ready" and smoke_info.get("passed") is True):
            raise EnvironmentBlocked("固定中文短音频转写验收未通过，拒绝写入就绪记录")
        resolved = asr.get("resolved_tools") or {}
        model_path = asr.get("model_path") or str(runtime["model"])
    elif reuse_machine_asr:
        rec_model = existing.get("model_path") or ""
        if not (existing.get("asr_smoke_verified") is True and (existing.get("os"), existing.get("arch"), existing.get("backend")) == (runtime["os"], runtime["arch"], runtime["backend"]) and _model_weights_present(Path(rec_model), runtime["backend"])):
            raise EnvironmentBlocked("本机尚无有效的短音频转写就绪记录或权重已失效，无法跳过首次转写验收")
        ZoneInfo("Asia/Shanghai")
        resolved = {"python": sys.executable}
        for name, flag in (("ffmpeg", ["-version"]), ("ffprobe", ["-version"]), ("curl", ["--fail-with-body", "--version"]), ("yt-dlp", ["--version"])):
            bin_path = executable(name)
            run([bin_path, *flag])
            resolved[name] = bin_path
        if runtime["backend"] == "mlx":
            cli = executable("mlx_whisper")
            run([cli, "--help"])
            resolved["mlx_whisper"] = resolved["asr_runtime"] = cli
        else:
            run([runtime["asr_python"], "-c", "import faster_whisper, ctranslate2"])
            resolved["asr_runtime"] = runtime["asr_python"]
        model_path = str(Path(rec_model).resolve())
        smoke_info = existing.get("asr_smoke") or {"passed": True}
    else:
        raise EnvironmentBlocked("必须提供 --asr-proof 或在已就绪机器上使用 --reuse-machine-asr")
    tools = {**resolved, "chrome": str(Path(chrome_path).resolve()), "node": str(Path(node_path).resolve())}
    missing = [k for k in (*SHARED_TOOL_KEYS, "node", "python") if not tools.get(k) or not Path(tools[k]).is_file()]
    if missing:
        raise EnvironmentBlocked(f"就绪登记缺少有效可执行路径：{', '.join(missing)}")
    prev_tools = existing.get("tools") or {}
    shared_unchanged = (
        existing.get("model_path") == model_path
        and all(prev_tools.get(k) == tools.get(k) for k in SHARED_TOOL_KEYS)
    )
    agents = dict(existing.get("agents") or {}) if shared_unchanged else {}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    agents[agent] = {
        "browser_verified": True, "tools_verified": True, "channel": channel,
        "node": tools["node"], "python": tools["python"],
        "verified_at": now, "endpoint": browser.get("endpoint"), "browser": browser.get("browser"),
    }
    record = {
        "schema_version": 1, "os": runtime["os"], "arch": runtime["arch"], "backend": runtime["backend"],
        "browser_verified": True, "asr_smoke_verified": True, "asr_smoke": smoke_info,
        "chrome_profile": str(dedicated_chrome_profile()),
        "chrome_launcher": str(dedicated_chrome_launcher()),
        "model_path": model_path, "tools": tools, "agents": agents, "updated_at": now,
    }
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(stamp_path, record)
    return {"status": "ready", "path": str(stamp_path), "agent": agent, "tools": tools}


def is_environment_error(exc: Exception) -> bool:
    detail = str(getattr(exc, "stderr", "") or exc)
    return isinstance(exc, (EnvironmentBlocked, PermissionError)) or bool(
        re.search(r"No module named|DLL load failed|cannot open shared object|No Metal device|MPS.*not available|Operation not permitted|Permission denied|Cannot write video metadata|file-unlink|\[sandbox\]|Read-only file system|缺少.*(?:依赖|运行时|模型)|out of memory|std::bad_alloc", detail, re.I)
    )


def faster_transcribe(media: Path | str, work: Path, runtime: dict, previous: bool = False, clip: str = "0", prompt: str | None = None) -> None:
    """Run faster-whisper in the isolated ASR environment without context loop traps."""
    code = r"""import dataclasses,json,os,sys
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1'
p=json.loads(sys.argv[1])
import onnxruntime
onnxruntime.disable_telemetry_events()
from faster_whisper import WhisperModel
model=WhisperModel(p['model'],device='cpu',compute_type='float32',cpu_threads=4,local_files_only=True)
segments,info=model.transcribe(p['media'],language='zh',task='transcribe',word_timestamps=True,beam_size=5,vad_filter=False,condition_on_previous_text=p['previous'],clip_timestamps=p['clip'],initial_prompt=p['prompt'])
rows=[dataclasses.asdict(s) for s in segments]
for row in rows:
    row['words']=row.get('words') or []
text=''.join(row['text'] for row in rows).strip()
data={'text':text,'segments':rows,'language':info.language,'backend':'faster-whisper','device':'cpu','compute_type':'float32','model_path':p['model']}
output=Path(p['output']); temporary=output.with_suffix('.json.partial')
temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=lambda x:x.item())+'\n',encoding='utf-8')
os.replace(temporary,output)
"""
    for name in ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"):
        readable_model_file(runtime["model"] / name)
    run([runtime["asr_python"], "-c", code, json.dumps({"media": str(media), "model": str(runtime["model"]), "output": str(work / "asr.json"), "previous": previous, "clip": clip, "prompt": prompt})])


def run_asr(media: Path, work: Path, lookup=executable, previous: bool = False, clip: str = "0") -> tuple[Path, float]:
    """Run offline large-v3-turbo ASR cleanly (default condition_on_previous_text=False, no initial prompt)."""
    started = time.perf_counter()
    output = work / "asr.json"
    previous_mtime = output.stat().st_mtime_ns if output.exists() else None
    runtime = reach_runtime()
    proc_diag = ""
    if runtime["backend"] == "faster-whisper":
        faster_transcribe(media, work, runtime, previous=previous, clip=clip, prompt=None)
    else:
        argv = [
            lookup("mlx_whisper"), str(media), "--model", str(runtime["model"]), "--language", "zh",
            "--output-dir", str(work), "--output-name", "asr", "--output-format", "json",
            "--word-timestamps", "True", "--condition-on-previous-text", str(previous), "--verbose", "False",
        ]
        if clip != "0":
            argv.extend(["--clip-timestamps", clip])
        proc = run(argv)
        proc_diag = (proc.stdout + "\n" + proc.stderr).strip()[-400:]
    if not output.is_file() or (previous_mtime is not None and output.stat().st_mtime_ns <= previous_mtime):
        suffix = f"（{proc_diag}）" if proc_diag else ""
        raise RuntimeError(f"本次转写未生成新结果{suffix}")
    data = read_json(output)
    segments = data.get("segments")
    if not isinstance(data, dict) or not isinstance(segments, list):
        raise RuntimeError("本次转写结果结构损坏")
    text = str(data.get("text") or "").strip()
    compact_text = re.sub(r"[\s，。！？!?、,.]", "", text)
    if (
        not text
        or not segments
        or any(not isinstance(s, dict) or not isinstance(s.get("words"), list) for s in segments)
        or not any(s["words"] for s in segments)
        or SILENCE_HALLUCINATION_RE.fullmatch(text)
        or (len(compact_text) <= 3 and all(float(s.get("avg_logprob") or 0) < -0.9 for s in segments))
        or all(float(s.get("no_speech_prob") or 0) > 0.75 and float(s.get("avg_logprob") or 0) < -0.8 for s in segments)
    ):
        raise NoSpeechDetected("未检测到有效口播；若为纯配乐／画面文字视频，请按可见画面原字录入并注明无口播")
    return output, time.perf_counter() - started


def run_clip_asr(media: Path, work: Path, start: float, end: float, lookup=executable) -> tuple[Path, Path, float]:
    """Slice [start, end] to 16kHz wav, transcribe, shift timestamps to absolute media seconds, and write draft.txt."""
    clip = work / "clip.wav"
    run([lookup("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", str(media), "-t", str(end - start), "-vn", "-ac", "1", "-ar", "16000", str(clip)])
    asr_path, seconds = run_asr(clip, work, lookup, previous=False)
    asr = read_json(asr_path)
    for seg in asr.get("segments", []):
        seg["start"] = round(float(seg["start"]) + start, 3)
        seg["end"] = round(float(seg["end"]) + start, 3)
        for w in seg.get("words") or []:
            w["start"] = round(float(w["start"]) + start, 3)
            w["end"] = round(float(w["end"]) + start, 3)
    write_json(asr_path, asr)
    draft_path = work / "draft.txt"
    draft_path.write_text(format_segments(asr["segments"]) + "\n", encoding="utf-8")
    return asr_path, draft_path, seconds


def format_segments(segments: list[dict]) -> str:
    return "\n\n".join(f"[{s['start']:.2f}–{s['end']:.2f}s] {s['text'].strip() or '【空文本】'}" for s in segments)


def diarize(media: Path | str, work: Path | str) -> dict:
    work = Path(work)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    runtime = reach_runtime()
    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    started = time.perf_counter()
    wav = work / "audio.wav"
    run([executable("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    converted = time.perf_counter()
    with wave.open(str(wav), "rb") as reader:
        duration = reader.getnframes() / reader.getframerate()
        audio = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32) / 32768
    pipeline = Pipeline.from_pretrained(str(runtime["speaker_model"]))
    pipeline.to(torch.device(runtime["speaker_device"]))
    loaded = time.perf_counter()
    with torch.inference_mode():
        result = pipeline({"waveform": torch.from_numpy(audio.copy()).unsqueeze(0), "sample_rate": 16000}, max_speakers=3)
    if runtime["speaker_device"] == "mps":
        torch.mps.synchronize()
    rows = [{"start": float(turn.start), "end": float(turn.end), "speaker": speaker} for turn, _, speaker in result.speaker_diarization.itertracks(yield_label=True)]
    write_json(work / "speakers.json", rows)
    return {
        "speaker_limit": 3, "speaker_limit_is_not_actual_count": True, "duration": duration,
        "conversion": converted - started, "model_load": loaded - converted,
        "inference": time.perf_counter() - loaded, "total": time.perf_counter() - started,
    }


def merge_transcript(asr: dict, rows: list | None = None, duration: float | None = None, include_timestamps: bool = False) -> tuple[str, int]:
    """Merge ASR segments with optional diarization turns; clean text by default."""
    if not str(asr.get("text") or "").strip() or not asr.get("segments"):
        raise NoSpeechDetected("没有可用口播；若为无口播画面视频，请按画面原字录入并注明无口播")

    speakers = {row["speaker"] for row in (rows or []) if row.get("speaker") is not None}
    if not rows or len(speakers) <= 1:
        if include_timestamps:
            segments, covered = [], 0.0
            for segment in asr["segments"]:
                start, end = round(segment["start"], 2), round(segment["end"], 2)
                if start > covered + 0.5:
                    segments.append(dict(start=covered, end=start, text="【未覆盖】", uncovered=True))
                segments.append(segment)
                covered = max(covered, end)
            if duration is not None and round(duration, 2) > covered + 0.5:
                segments.append(dict(start=covered, end=round(duration, 2), text="【未覆盖】", uncovered=True))
            return format_segments(segments), 1

        paragraphs, current, prev_end = [], [], 0.0
        for segment in asr["segments"]:
            text = str(segment.get("text") or "")
            if not text.strip():
                continue
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
            if not current and prev_end == 0.0 and start >= 10.0:
                paragraphs.append(f"【未覆盖 0.0–{start:.1f}s】")
            elif current and start - prev_end >= 8.0:
                paragraphs.extend(["".join(current).strip(), f"【未覆盖 {prev_end:.1f}–{start:.1f}s】"])
                current = []
            elif current and start - prev_end >= 1.5:
                paragraphs.append("".join(current).strip())
                current = []
            current.append(text)
            prev_end = max(prev_end, end)
        if current:
            paragraphs.append("".join(current).strip())
        if duration is not None and float(duration) - prev_end >= 10.0:
            paragraphs.append(f"【未覆盖 {prev_end:.1f}–{float(duration):.1f}s】")
        return ("\n\n".join(p for p in paragraphs if p) or str(asr["text"]).strip()), 1

    segments, covered = [], 0.0
    for segment in asr["segments"]:
        start, end = round(segment["start"], 2), round(segment["end"], 2)
        gap_limit = 0.5 if include_timestamps else (10.0 if covered == 0.0 else 8.0)
        if start >= covered + gap_limit:
            tag = "【未覆盖】" if include_timestamps else f"【未覆盖 {covered:.1f}–{start:.1f}s】"
            segments.append(dict(start=covered, end=start, text=tag, uncovered=True))
        segments.append(segment)
        covered = max(covered, end)
    tail_limit = 0.5 if include_timestamps else 10.0
    if duration is not None and round(duration, 2) >= covered + tail_limit:
        end_d = round(duration, 2)
        tag = "【未覆盖】" if include_timestamps else f"【未覆盖 {covered:.1f}–{end_d:.1f}s】"
        segments.append(dict(start=covered, end=end_d, text=tag, uncovered=True))

    utterances = []
    for segment in segments:
        if segment.get("uncovered") or not str(segment.get("text") or "").strip():
            utterances.append([None, str(segment.get("text") or "").strip() or "【空文本】", segment["start"], segment["end"]])
            continue
        words = segment.get("words") or [{"start": segment["start"], "end": segment["end"], "word": segment["text"]}]
        for word in words:
            overlap = defaultdict(float)
            for row in rows:
                overlap[row["speaker"]] += max(0.0, min(word["end"], row["end"]) - max(word["start"], row["start"]))
            if max(overlap.values()) > 0:
                speaker = max(overlap, key=overlap.get)
            else:
                center = (word["start"] + word["end"]) / 2
                speaker = min(rows, key=lambda row: min(abs(center - row["start"]), abs(center - row["end"])))["speaker"]
            if utterances and utterances[-1][0] == speaker:
                utterances[-1][1] += word["word"]
                utterances[-1][3] = word["end"]
            else:
                utterances.append([speaker, word["word"], word["start"], word["end"]])

    labels = {speaker: f"说话人{i}" for i, speaker in enumerate(dict.fromkeys(u[0] for u in utterances if u[0] is not None), 1)}
    if not labels:
        raise RuntimeError("多人转写缺少有效词级对齐")
    if include_timestamps:
        body = "\n\n".join(f"[{start:.2f}–{end:.2f}s] {(labels[speaker] + '：') if speaker is not None else ''}{text.strip()}" for speaker, text, start, end in utterances)
    else:
        body = "\n\n".join(f"{(labels[speaker] + '：') if speaker is not None else ''}{text.strip()}" for speaker, text, _start, _end in utterances)
    return body, len(labels)


def _next_acquisition_route(attempts: list[dict], default_first: str = "A") -> str | None:
    if len(attempts) >= 4:
        return None
    if not attempts:
        return default_first
    nxt = "A" if attempts[-1].get("route") == "B" else "B"
    return nxt if sum(a.get("route") == nxt for a in attempts) < 2 else None


def _ensure_subtitle_audio(manifest_path: Path, data: dict, work: Path, purpose: str) -> tuple[Path | None, dict | None]:
    """Download audio on demand when a Bilibili subtitle-lane item later needs diarization or excerpt retry."""
    if not (data.get("subtitle_source") and data.get("url")):
        raise RuntimeError(f"缺少已保存的媒体文件，无法{purpose}")
    attempts = data.get("acquisition", {}).get("attempts", [])
    if data.get("acquisition", {}).get("blocked"):
        raise RuntimeError("本条获取已明确受限；不切换路线重试")
    nxt = _next_acquisition_route(attempts, default_first="A")
    if nxt is None:
        raise RuntimeError("四次完整获取预算已用尽")
    if nxt == "B":
        return None, {"status": "needs_media", "route": "B", "manifest": str(manifest_path), "url": data["url"], "note": f"已保留现成字幕，请走路线 B 下载同篇音频后复跑{purpose}"}
    acquisition(manifest_path, "begin", route="A")
    try:
        res = run([
            executable("yt-dlp"), "--ignore-config", "--no-playlist", "-f", "bestaudio",
            "--retries", "0", "--extractor-retries", "0", "--fragment-retries", "0",
            "--socket-timeout", "20", "--print", "after_move:filepath",
            "-o", str(work / "audio.%(ext)s"), str(data["url"]),
        ])
        if acquisition_denied(res.stderr, unauthenticated_cli=True):
            raise RuntimeError(res.stderr)
        media = Path(res.stdout.strip().splitlines()[-1]).resolve()
        acquisition(manifest_path, "finish", outcome="success", media=media)
        return media, None
    except Exception as exc:
        denied = acquisition_denied(exc, unauthenticated_cli=True)
        acquisition(manifest_path, "finish", outcome="denied" if denied else "failed", detail=safe_error(exc))
        if denied:
            raise RuntimeError(safe_error(exc)) from None
        return None, {"status": "needs_media", "route": "B", "manifest": str(manifest_path), "url": data["url"], "error": safe_error(exc)}


def diarize_existing(manifest_path: Path) -> dict:
    """Run optional speaker diarization on an already-prepared item without re-downloading or re-running ASR."""
    started = time.perf_counter()
    manifest_path = manifest_path.resolve()
    data = read_json(manifest_path)
    work = manifest_path.parent
    media = Path(data.get("media") or "") if data.get("media") else Path()
    asr_path = Path(data.get("asr") or (work / "asr.json"))
    if not asr_path.is_file():
        raise RuntimeError("缺少已保存的 asr.json，无法就地补跑声纹")

    runtime = reach_runtime()
    if not speaker_ready_hint(runtime):
        return {
            "status": "speaker_unavailable", "manifest": str(manifest_path), "asr": str(asr_path),
            "note": "当前环境未配置完整本地声纹模型或运行环境，已保留单轨文本；请依据问答语义与 asr.json 停顿切分对话并在简报说明",
        }

    if not (media.name and media.is_file()):
        media_res, pending_resp = _ensure_subtitle_audio(manifest_path, data, work, "diarize")
        if pending_resp is not None:
            return pending_resp
        media, data = media_res, read_json(manifest_path)

    speech = json.loads(run([runtime["speaker_python"], str(Path(__file__).resolve()), "_diarize", str(media), str(work)]).stdout)
    rows, asr = read_json(work / "speakers.json"), read_json(asr_path)
    draft_path = Path(data.get("draft") or (work / "draft.txt"))
    single_backup = work / "draft.single.txt"
    if draft_path.is_file() and not single_backup.exists():
        shutil.copy2(draft_path, single_backup)

    body, speaker_count = merge_transcript(asr, rows, speech["duration"], include_timestamps=False)
    draft_path.write_text(body + "\n", encoding="utf-8")
    quality = inspect_draft_quality(body)
    data.update(speaker_count=speaker_count, speaker_limit=3, diarized=True, duration=speech["duration"], draft=str(draft_path), draft_quality=quality)
    timings = data.setdefault("timings", {})
    timings["diarization_followup"] = round(time.perf_counter() - started, 3)
    write_json(manifest_path, data)
    return {"status": "diarized", "manifest": str(manifest_path), "draft": str(draft_path), "speaker_count": speaker_count, "draft_quality": quality, "timings": timings}


def acquisition(path: Path | str, action: str, route: str | None = None, outcome: str | None = None, detail: str = "", media: Path | str | None = None, info: dict | None = None) -> dict:
    """Persist complete attempts in this item's authoritative source/manifest (supports B-first BABA and legacy ABAB)."""
    path = Path(path)
    if not path.is_file() and action in ("begin", "skip"):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {})
    data = read_json(path)
    budget = data.setdefault("acquisition", {"attempts": []})
    attempts = budget.setdefault("attempts", [])
    if budget.get("blocked"):
        raise RuntimeError("本条获取已明确受限；不切换路线重试")
    pending = attempts and attempts[-1]["outcome"] == "pending"
    if action == "begin":
        if pending:
            raise RuntimeError("上次获取结果未知；先核实并结束该次，不重复获取")
        if attempts and attempts[-1]["outcome"] == "success":
            raise RuntimeError("本条已取得媒体；复用现有材料")
        if len(attempts) >= 4 or route not in ("A", "B") or sum(a.get("route") == route for a in attempts) >= 2:
            raise RuntimeError("四次完整获取预算已用尽或路线参数无效")
        if attempts:
            expected = _next_acquisition_route(attempts)
            if route != expected:
                raise RuntimeError(f"下一次只能使用实际可用的 {expected} 路径；没有该能力则保留缺口")
        attempts.append({"route": route, "outcome": "pending"})
    elif action == "skip":
        nxt = _next_acquisition_route(attempts, default_first="B")
        if pending or (attempts and attempts[-1]["outcome"] == "success") or nxt != "B" or not detail:
            raise RuntimeError("仅能说明实际缺失原因后跳过尚未开始的 B 槽位")
        attempts.append({"route": "B", "outcome": "unavailable", "detail": detail})
    elif action == "finish":
        if not pending:
            raise RuntimeError("没有等待核实的获取尝试")
        if outcome not in ("success", "failed", "denied"):
            raise ValueError("outcome 必须为 success/failed/denied")
        if outcome == "success":
            file = Path(media).expanduser().resolve() if media else None
            if file is None or not file.is_file() or not file.stat().st_size:
                raise ValueError("成功须提供实际非空媒体文件")
            data["media"] = str(file)
            if info is not None:
                data["source_info"] = info
        attempts[-1].update(outcome=outcome, detail=detail)
        if outcome == "denied":
            budget["blocked"] = True
    else:
        raise ValueError("action 必须为 begin/finish/skip")
    write_json(path, data)
    return data


def acquisition_denied(exc: Exception | str, unauthenticated_cli: bool = False) -> bool:
    """Distinguish explicit platform content denial from unauthenticated CLI 403/login or local FS permission errors."""
    if isinstance(exc, PermissionError):
        return False
    detail = str(getattr(exc, "stderr", "") or exc)
    if unauthenticated_cli:
        return bool(re.search(r"付费|试看|会员专享|仅限会员|only the preview|supporter-only|premium members only|members-only|video is private|HTTP (?:Error )?404|已删除|does not exist", detail, re.I))
    return bool(re.search(r"access denied|forbidden|HTTP (?:Error )?(?:401|403)|login required|sign in|captcha|安全|拒绝|风控|付费|试看|only the preview|supporter-only|premium members only", detail, re.I))


def probe_media(path: Path, *, require_audio: bool = False, expected_duration: float | None = None, strict_duration: bool = False) -> dict:
    """Validate decoded media streams and optional player duration consistency."""
    meta = json.loads(run([executable("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type,codec_name,duration", "-of", "json", str(path)]).stdout)
    streams = meta.get("streams") or []
    types = [s.get("codec_type") for s in streams]
    if not any(t in ("audio", "video") for t in types):
        raise RuntimeError("媒体文件不包含可解码音视频轨道")
    if require_audio and "audio" not in types:
        raise RuntimeError("媒体文件缺少音轨（疑似纯画面分轨）")
    dur = float((meta.get("format") or {}).get("duration") or 0) or max((float(s.get("duration") or 0) for s in streams), default=0.0) or None
    if strict_duration and (expected_duration is None or float(expected_duration) <= 0 or dur is None):
        raise RuntimeError("未确认归属的备用音轨缺少精确播放器时长供交叉核对，拒绝盲用")
    if expected_duration is not None and float(expected_duration) > 0 and dur is not None:
        exp = float(expected_duration)
        tol = 0.6 if strict_duration else max(3.0, exp * 0.05)
        if abs(dur - exp) > tol:
            raise RuntimeError(f"媒体时长（{dur:.1f}s）与当前作品播放器时长（{exp:.1f}s）不符，疑似混入相邻视频")
    return {"duration": dur, "streams": types}


def fetch_verified_media(urls: str | list[str], platform: str, output: Path, state_path: Path | None = None, route: str | None = "auto", timeout: int = 180, *, require_audio: bool = False, expected_duration: float | None = None, attributed_urls: set[str] | None = None, info_json: Path | None = None) -> dict:
    """Immediately download a browser-verified media stream with standard platform headers and ffprobe verification."""
    if platform not in PLATFORM_REFERERS:
        raise ValueError(f"platform 必须为 {sorted(PLATFORM_REFERERS)} 之一")
    raw_list = [urls] if isinstance(urls, str) else list(urls or [])
    candidates: list[str] = []
    for item in raw_list:
        u = str(item or "").strip()
        if not u or u.startswith("blob:") or u in candidates:
            continue
        parsed = urlsplit(u)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            candidates.append(u)
    if not candidates:
        raise ValueError("仅接受完整 http/https 媒体直链（不能传空值或 blob: 地址）")
    output = Path(output).expanduser()
    if not output.is_absolute():
        raise RuntimeError("媒体输出必须为绝对路径")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(output.suffix + ".part")

    if state_path is not None:
        sp = Path(state_path)
        if not sp.is_file():
            sp.parent.mkdir(parents=True, exist_ok=True)
            write_json(sp, {})
        chosen_route = route
        if chosen_route in (None, "", "auto"):
            attempts = (read_json(sp).get("acquisition") or {}).get("attempts") or []
            chosen_route = _next_acquisition_route(attempts, default_first="A")
            if chosen_route is None:
                raise RuntimeError("四次完整获取预算已用尽")
        acquisition(sp, "begin", route=chosen_route)
    try:
        errors: list[str] = []
        for candidate in candidates:
            res = subprocess.run(
                [
                    executable("curl"), "--disable", "--http1.1", "--fail", "--location", "--retry", "0",
                    "--connect-timeout", "15", "--max-time", str(timeout),
                    "-H", f"Referer: {PLATFORM_REFERERS[platform]}", "-H", f"Origin: {PLATFORM_ORIGINS[platform]}",
                    "-H", f"User-Agent: {USER_AGENT}", "-o", str(part), candidate,
                ],
                text=True, capture_output=True, encoding="utf-8", errors="replace",
            )
            if res.returncode != 0:
                if res.returncode == 23 or is_environment_error(RuntimeError(res.stderr or "")):
                    raise EnvironmentBlocked(f"本地目录写入或清理受限（{output.parent}）：{safe_error(RuntimeError(res.stderr.strip() or f'curl 写入失败 ({res.returncode})'))}")
                errors.append(f"curl 退出码 {res.returncode}: {res.stderr.strip()}")
                continue
            if not part.is_file() or not part.stat().st_size:
                errors.append("下载结果为空文件")
                continue
            try:
                unattr = attributed_urls is not None and candidate not in attributed_urls
                probed = probe_media(part, require_audio=require_audio, expected_duration=expected_duration, strict_duration=unattr)
            except Exception as probe_exc:
                errors.append(safe_error(probe_exc))
                continue
            try:
                part.replace(output)
            except PermissionError:
                shutil.copyfile(part, output)
            if state_path is not None:
                acquisition(state_path, "finish", outcome="success", media=output, info=read_json(info_json) if info_json else None)
            return {"status": "downloaded", "media": str(output), "url_used": candidate, "bytes": output.stat().st_size, "duration": probed["duration"], "streams": probed["streams"]}
        raise RuntimeError("；".join(errors) if errors else "全部候选直链下载失败")
    except Exception as exc:
        if part.exists():
            try:
                part.unlink(missing_ok=True)
            except PermissionError:
                pass
        if is_environment_error(exc):
            if state_path is not None:
                try:
                    cur_s = read_json(state_path)
                    att = (cur_s.get("acquisition") or {}).get("attempts") or []
                    if att and att[-1].get("outcome") == "pending":
                        att.pop()
                        write_json(state_path, cur_s)
                except Exception:
                    pass
            if isinstance(exc, EnvironmentBlocked):
                raise
            raise EnvironmentBlocked(f"本地目录写入或清理受限（{output.parent}）：{safe_error(exc)}") from None
        if state_path is not None:
            try:
                attempts = (read_json(state_path).get("acquisition") or {}).get("attempts") or []
                if attempts and attempts[-1].get("outcome") == "pending":
                    acquisition(state_path, "finish", outcome="denied" if acquisition_denied(exc, unauthenticated_cli=True) else "failed", detail=safe_error(exc))
            except Exception:
                pass
        raise


def clean_topic_title(raw: str) -> str:
    """Strip trailing hashtags/@mentions and platform bots while keeping inline @person names."""
    text = re.sub(r"\s+", " ", CONTROL_WS_RE.sub("", html.unescape(str(raw or "")))).strip()
    if not text:
        return ""
    for _ in range(3):
        updated = PLATFORM_BOT_RE.sub("", text)
        updated = TRAILING_SITE_RE.sub("", updated)
        no_attach = TRAILING_ATTACH_RE.sub("", updated)
        if no_attach.strip():
            updated = no_attach
        updated = CJK_BEFORE_INLINE_MENTION_RE.sub("", updated)
        updated = INLINE_MENTION_RE.sub(r"\1", updated)
        updated = re.sub(r"\s+", " ", updated).strip()
        updated = TRAILING_JUNK_RE.sub("", LEADING_JUNK_RE.sub("", updated))
        if updated == text:
            break
        text = updated
    return text.strip()


def has_multi_speaker_hint(*texts: str) -> bool:
    return bool(MULTI_SPEAKER_RE.search(" ".join(str(t or "") for t in texts)))


def media_signature(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    size = resolved.stat().st_size
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        digest.update(handle.read(65536))
        if size > 65536:
            handle.seek(max(65536, size - 65536))
            digest.update(handle.read(65536))
    return f"{resolved}:{size}:{digest.hexdigest()[:16]}"


def _has_repetition_loop(text: str) -> str | None:
    compact = re.sub(r"[\s，,。．.！？!?、；;：:…—\-~～()（）\[\]【】「」『』“”\"'‘’]+", "", text)
    single = re.search(r"(.)\1{11,}", compact)
    if single:
        return single.group(0)[:12]
    match = re.search(r"(.{2,30}?)\1{3,}", compact)
    return match.group(1) if match and len(set(match.group(1))) >= 2 else None


def inspect_draft_quality(text: str) -> dict:
    body = str(text or "").strip()
    issues: list[str] = []
    if not body:
        issues.append("empty_draft")
    elif _effective_chars(body) == 0:
        issues.append("no_effective_text")
    bad_repl = body.count("\ufffd")
    if bad_repl > 3 or (body and bad_repl * 20 > len(body)):
        issues.append(f"replacement_chars({bad_repl})")
    fullwidth_b = body.count("\uff22")
    if "\uff22\uff22\uff22" in body or fullwidth_b >= 5:
        issues.append(f"fullwidth_B_noise({fullwidth_b})")
    loop = _has_repetition_loop(body)
    if loop:
        issues.append(f"repetition_loop({loop[:12]})")
    gaps = re.findall(r"【未覆盖[^】]*】", body)
    return {"usable": not issues, "has_loop": bool(loop), "uncovered_gaps": gaps, "issues": issues}


def _effective_chars(text: str, *, dedupe_loops: bool = False) -> int:
    cleaned = re.sub(r"\[\d+(?:\.\d+)?[–-]\d+(?:\.\d+)?s\]", "", str(text or ""))
    cleaned = re.sub(r"(?m)^说话人\d+[：:]\s*", "", cleaned)
    cleaned = re.sub(r"【(?:未覆盖[^】]*|空文本)】", "", cleaned)
    if dedupe_loops:
        for _ in range(3):
            cleaned = re.sub(r"(.)\1{11,}", r"\1", cleaned)
            cleaned = re.sub(r"(.{2,30}?)(?:[\s，,。．.！？!?、；;：:…]*\1){3,}", r"\1", cleaned)
    return len(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", cleaned))


def validate_reviewed_body(body: str, draft_text: str | None = None, is_transcript: bool = True, *, verified_gaps: list[tuple[float, float]] | None = None, verified_silence: bool = False) -> dict:
    """Hard quality gate blocking garbled noise, unresolved gaps, loops, walls of text, and severe truncation."""
    text = str(body or "").strip()
    if not text:
        raise ValueError("复核正文为空，拒绝写入")
    gap_marker = re.search(
        r"[【〔\[（(][^】〕\]）)\n]{0,40}(?:未覆盖|空文本|原音(?:缺失|损坏|不清)|大段缺失|音频(?:缺失|损坏)|漏转|未转出)[^】〕\]）)\n]{0,40}[】〕\]）)]",
        text,
    )
    if gap_marker:
        raise ValueError(
            f"正文残留未核实的空档或缺失标记（{gap_marker.group(0)}）；请调 retry-excerpt 核对该时段（确系纯音乐/停顿可删标记，确有口播请补齐；若原音大段损坏缺失请停止写入正式库并单列报告）"
        )
    bad_repl = text.count("\ufffd")
    if bad_repl > 3 or bad_repl * 20 > len(text):
        raise ValueError(f"正文包含过多替换符（{bad_repl} 处），疑似坏稿，拒绝写入")
    fullwidth_b = text.count("\uff22")
    if "\uff22\uff22" in text or fullwidth_b >= 3:
        raise ValueError(f"正文残留全角Ｂ乱码（{fullwidth_b} 处），请先清理或恢复后再保存")
    loop = _has_repetition_loop(text)
    if loop:
        raise ValueError(f"正文检测到异常连续重复循环片段（{loop[:15]}），请先核清原音后保存")

    non_ws = re.sub(r"\s+", "", text)
    body_eff = _effective_chars(text)
    if body_eff == 0 or (len(non_ws) >= 20 and body_eff < len(non_ws) * 0.25):
        raise ValueError("正文缺少有效中英文或数字内容（疑似全角符号或占位符坏稿），拒绝写入")
    if body_eff >= 80:
        eff_only = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text)
        if eff_only and max(eff_only.count(ch) for ch in set(eff_only)) > len(eff_only) * 0.45:
            raise ValueError("正文单一字符占比异常过高，疑似占位符刷屏坏稿，拒绝写入")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if is_transcript and len(non_ws) >= 300:
        for idx, para in enumerate(paragraphs, 1):
            p_len = len(re.sub(r"\s+", "", para))
            if p_len > 900:
                raise ValueError(f"第 {idx} 段达 {p_len} 字，超出单段 900 字上限；请按完整话题与论点自然分段")
            if p_len > 220 and not re.search(r"[。！？!?…]", para):
                raise ValueError(f"第 {idx} 段达 {p_len} 字却无句末标点（。！？），疑似连写未校对；请补齐句末标点并分段")

    draft_eff = _effective_chars(draft_text) if draft_text else None
    draft_base_eff = _effective_chars(draft_text, dedupe_loops=True) if draft_text else None
    if draft_text and draft_base_eff and draft_base_eff >= 150 and body_eff < draft_base_eff * 0.78:
        raise ValueError(f"成稿有效字数（{body_eff}）低于草稿去重基准（{draft_base_eff}）的 78%（{body_eff / draft_base_eff:.1%}），疑似实质删段或摘要化；请保留完整原话后再保存")

    draft_gaps = [(float(a), float(b)) for a, b in re.findall(r"【未覆盖\s*(\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)s】", str(draft_text or ""))]
    if is_transcript and draft_gaps and not verified_silence:
        checked = list(verified_gaps or [])
        unverified: list[tuple[float, float]] = []
        for ga, gb in draft_gaps:
            spans = sorted((max(ga, va), min(gb, vb)) for va, vb in checked if min(gb, vb) > max(ga, va))
            covered_len, cur_e = 0.0, ga
            for sa, sb in spans:
                if sb > cur_e:
                    covered_len += sb - max(sa, cur_e)
                    cur_e = sb
            gap_len = gb - ga
            if covered_len < min(max(0.5, gap_len - 2.0), gap_len * 0.8):
                unverified.append((ga, gb))
        added_eff = body_eff - (draft_eff or 0)
        if unverified and added_eff < max(12, int(sum(gb - ga for ga, gb in unverified) * 1.2)):
            ga, gb = unverified[0]
            raise ValueError(
                f"草稿存在长空档（{ga:.1f}–{gb:.1f}s）仅删除提示但未见有效完成且覆盖缺口的补转记录或补齐口播；请先调 retry-excerpt --clip {ga:.1f} {gb:.1f} 核实，若确系纯配乐/静音可在 finalize 加 --verified-silence 登记放行"
            )

    return {"reviewed_chars": len(text), "effective_chars": body_eff, "draft_effective_chars": draft_eff, "paragraphs": len(paragraphs)}


def normalize_published_date(raw: str | int | float | None, *, allow_edited: bool = False) -> tuple[str, dt.date, bool]:
    """Return (frontmatter_value, filename_date, used_entry_date)."""
    today = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if raw is None or str(raw).strip() == "":
        return "", today, True
    text = str(raw).strip()
    if re.match(r"^编辑于(?:\s|$)", text):
        if not allow_edited:
            return "", today, True
        text = re.sub(r"^编辑于\s*", "", text).strip()
    else:
        text = re.sub(r"^发布于\s*", "", text).strip()
    m_date = re.match(r"^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}-\d{1,2})(?:\s+[\u4e00-\u9fa5A-Za-z]+)?$", text)
    if m_date:
        text = m_date.group(1)
    if re.fullmatch(r"\d+(?:\.\d+)?", text) and len(text.split(".")[0]) >= 9:
        stamp = dt.datetime.fromtimestamp(float(text), ZoneInfo("Asia/Shanghai")).date()
        return stamp.isoformat(), stamp, False
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
        return parsed.date().isoformat(), parsed.date(), False
    except ValueError:
        return text, today, True


def find_existing_work(directory: Path, url: str) -> Path | None:
    if not directory.is_dir():
        return None
    for path in sorted(directory.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(directory).parts):
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:6000]
        except OSError:
            continue
        parts = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)", head, re.S)
        if not parts or not parts[2].strip() or not all(re.search(rf"(?m)^{k}:", parts[1]) for k in ("发布日期", "作者")):
            continue
        m = re.search(r"(?m)^原文链接:[ \t]*(.+)$", parts[1])
        if not m:
            continue
        raw_url = m.group(1).strip()
        existing_url = json.loads(raw_url) if raw_url.startswith('"') else raw_url.strip("'")
        if same_work(existing_url, url):
            return path
    return None


def yaml_line(key: str, value) -> str:
    return f"{key}:" if value is None or value == "" else f"{key}: {json.dumps(value, ensure_ascii=False)}"


def save_standard_note(*, url: str, platform: str, title: str, author: str, published: str | int | float | None, like_count, content_type: str, tags: list[str], body: str, output_dir: Path, work_id: str = "", draft_text: str | None = None, is_transcript: bool = True, replace_path: Path | None = None, clean_title_flag: bool = True, backup_dir: Path | None = None, verified_silence: bool = False) -> dict:
    """Validate reviewed body and save canonical 7-field Markdown note with readback verification."""
    if platform not in VALID_PLATFORMS:
        raise ValueError(f"平台必须为 {sorted(VALID_PLATFORMS)} 之一")
    if content_type not in ("视频", "图文"):
        raise ValueError("内容类型只用 视频 或 图文")
    raw_tags = [str(t).strip() for t in (tags or [])]
    if not raw_tags or any(not t for t in raw_tags):
        raise ValueError("按正文提供 1–2 个非空主题 tags")
    clean_tags = list(dict.fromkeys(p.strip() for t in raw_tags for p in re.split(r"[,，、]", t) if p.strip()))
    if not 1 <= len(clean_tags) <= 2:
        raise ValueError("按正文提供 1–2 个非空主题 tags")

    checked_gaps: list[tuple[float, float]] = []
    if backup_dir is not None and Path(backup_dir).is_dir():
        bdir = Path(backup_dir)
        mfile = bdir / "manifest.json"
        retry_states: dict[tuple[float, float], str] = {}
        if mfile.is_file():
            try:
                mdata = read_json(mfile)
                live_m = Path(mdata["media"]) if mdata.get("media") else None
                cur_sig = media_signature(live_m) if (live_m and live_m.is_file()) else str(mdata.get("media_sig") or "")
                for item in mdata.get("excerpt_retries") or []:
                    if "start" in item and "end" in item and str(item.get("media_sig") or "") == cur_sig:
                        key_span = (float(item["start"]), float(item["end"]))
                        retry_states[key_span] = str(item.get("status") or "")
                if mdata.get("verified_silence") and "verified_silence_sig" in mdata and str(mdata.get("verified_silence_sig") or "") == cur_sig:
                    verified_silence = True
            except Exception:
                pass
        for sub_d in bdir.glob("local-retry-*"):
            m_retry = re.fullmatch(r"local-retry-(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", sub_d.name)
            if not (m_retry and sub_d.is_dir()):
                continue
            span = (float(m_retry[1]), float(m_retry[2]))
            if retry_states.get(span) == "completed" and (sub_d / "asr.json").is_file() and (sub_d / "draft.txt").is_file():
                checked_gaps.append(span)

    stats = validate_reviewed_body(body, draft_text=draft_text, is_transcript=is_transcript, verified_gaps=checked_gaps, verified_silence=verified_silence)
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_title = clean_topic_title(title) if clean_title_flag else re.sub(r"\s+", " ", str(title or "")).strip()
    pub_value, fname_date, used_entry_date = normalize_published_date(published, allow_edited=(platform == "小红书"))
    frontmatter = [
        "---", yaml_line("发布日期", pub_value), f"平台: {platform}", yaml_line("原文链接", url),
        yaml_line("作者", str(author or "")), yaml_line("点赞数", "" if like_count is None else like_count),
        f"内容类型: {content_type}", "标签:", *(f"  - {json.dumps(t, ensure_ascii=False)}" for t in clean_tags), "---", "",
    ]
    content = "\n".join(frontmatter) + str(body).strip() + "\n"

    existing = find_existing_work(output_dir, url)
    if existing and (not replace_path or existing.resolve() != Path(replace_path).resolve()):
        if existing.read_text(encoding="utf-8") == content:
            return {"status": "saved", "output": str(existing), "title": final_title, "published": pub_value, "used_entry_date": used_entry_date, "review_stats": stats}
        return {"status": "existing_needs_format_review", "output": str(existing)}

    safe_name = BAD_FILENAME_RE.sub("_", final_title).strip(" .") or work_id or "未命名"
    base = f"{fname_date:%y.%m.%d}-{safe_name}"
    target = output_dir / f"{base}.md"
    suffix = 2
    while target.exists() and (not replace_path or target.resolve() != Path(replace_path).resolve()):
        target = output_dir / f"{base}-{suffix}.md"
        suffix += 1

    if replace_path:
        replace_resolved = Path(replace_path).resolve()
        if backup_dir is not None and replace_resolved.is_file():
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(replace_resolved, backup_dir / "replaced.md")
        if replace_resolved == target.resolve():
            target.write_text(content, encoding="utf-8")
        else:
            tmp: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir, prefix=".note-", delete=False) as handle:
                    handle.write(content)
                    tmp = Path(handle.name)
                tmp.replace(target)
                tmp = None
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
            replace_resolved.unlink()
    else:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(content)

    if target.read_text(encoding="utf-8") != content:
        raise RuntimeError("保存回读不一致，保留现场")
    return {
        "status": "saved", "output": str(target), "title": final_title, "published": pub_value,
        "tags": clean_tags, "used_entry_date": used_entry_date, "review_stats": stats,
        "output_written": True, "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def transcribe_and_merge(
    media: Path, work: Path, *, speakers: bool = False, expected_duration: float | None = None,
    replacing: bool = False, reuse_asr: Path | None = None, runner=run_asr,
) -> dict:
    """Shared ASR + optional parallel diarization + quality-gated atomic staging across video platforms."""
    asr_work = (work / ".replace-staging") if replacing else work
    if replacing:
        shutil.rmtree(asr_work, ignore_errors=True)
        asr_work.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    stage = time.perf_counter()
    try:
        if speakers:
            script_self = str(Path(__file__).resolve())
            if reuse_asr and reuse_asr.is_file():
                speech = json.loads(run([reach_runtime()["speaker_python"], script_self, "_diarize", str(media), str(asr_work)]).stdout)
                asr_path = reuse_asr
                timings.update(asr=0.0, diarization=round(speech["total"], 3))
            else:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    asr_task = pool.submit(runner, media, asr_work, executable, False)
                    diar_task = pool.submit(run, [reach_runtime()["speaker_python"], script_self, "_diarize", str(media), str(asr_work)])
                    asr_path, asr_sec = asr_task.result()
                    speech = json.loads(diar_task.result().stdout)
                timings.update(speech_parallel=round(time.perf_counter() - stage, 3), asr=round(asr_sec, 3), diarization=round(speech["total"], 3))
            duration = speech.get("duration") or expected_duration
            rows = read_json(asr_work / "speakers.json")
        else:
            asr_path, asr_sec = runner(media, asr_work, executable, False)
            timings["asr"] = round(asr_sec, 3)
            duration, rows = expected_duration, None
    except Exception:
        if replacing:
            shutil.rmtree(asr_work, ignore_errors=True)
        raise

    merge_tick = time.perf_counter()
    body, speaker_count = merge_transcript(read_json(asr_path), rows, duration, include_timestamps=False)
    timings["merge"] = round(time.perf_counter() - merge_tick, 3)
    quality = inspect_draft_quality(body)
    if replacing:
        if not quality["usable"]:
            bad = work / "draft-replace-invalid.txt"
            bad.write_text(body + "\n", encoding="utf-8")
            shutil.rmtree(asr_work, ignore_errors=True)
            return {"replaced_invalid": True, "invalid_draft": str(bad), "draft_quality": quality, "timings": timings}
        final_asr = work / "asr.json"
        if Path(asr_path).resolve() != final_asr.resolve():
            Path(asr_path).replace(final_asr)
        asr_path = final_asr
        if speakers and (asr_work / "speakers.json").is_file():
            (asr_work / "speakers.json").replace(work / "speakers.json")
        else:
            (work / "speakers.json").unlink(missing_ok=True)
        shutil.rmtree(asr_work, ignore_errors=True)
    draft = work / "draft.txt"
    draft.write_text(body + "\n", encoding="utf-8")
    return {
        "replaced_invalid": False, "asr": str(asr_path), "draft": str(draft), "body": body,
        "draft_quality": quality, "speaker_count": speaker_count, "duration": duration, "timings": timings,
    }


def shared_retry_excerpt(manifest_path: Path, start: float, end: float) -> dict:
    """Slice and re-transcribe [start, end] with completion and media_sig tracking in manifest.json."""
    started = time.perf_counter()
    manifest_path = manifest_path.resolve()
    data = read_json(manifest_path)
    media = Path(data.get("media") or "") if data.get("media") else Path()
    if not (media.name and media.is_file()):
        media_res, pending_resp = _ensure_subtitle_audio(manifest_path, data, manifest_path.parent, "retry-excerpt")
        if pending_resp is not None:
            return pending_resp
        media, data = media_res, read_json(manifest_path)
    cur_sig = media_signature(media)
    if not data.get("media_sig"):
        data["media_sig"] = cur_sig
    dur = data.get("duration") or probe_media(media, require_audio=True).get("duration")
    if start < 0 or start >= end or (dur is not None and end > float(dur) + 1.0):
        raise ValueError("补转范围须在原音频时长内且开始早于结束")
    if any(r.get("start") == start and r.get("end") == end and str(r.get("media_sig") or "") == cur_sig for r in data.get("excerpt_retries", [])):
        raise RuntimeError("该窗口已用过，复用现有结果；终态不明也不重置次数")
    work = manifest_path.parent / f"local-retry-{start}-{end}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    attempt = {"start": start, "end": end, "status": "started", "media_sig": cur_sig}
    data.setdefault("excerpt_retries", []).append(attempt)
    write_json(manifest_path, data)
    asr, draft, seconds = run_clip_asr(media, work, start, end, executable)
    attempt["status"] = "completed"
    write_json(manifest_path, data)
    return {
        "status": "retry_evidence", "asr": str(asr), "draft": str(draft), "range": [start, end],
        "timestamp_offset": start, "end": end, "timestamps": "原音频绝对秒数",
        "asr_seconds": round(seconds, 3), "total_seconds": round(time.perf_counter() - started, 3),
    }


def finalize_manifest_note(
    manifest_path: Path, reviewed_path: Path, *, platform: str, output_dir: Path | None = None,
    tags: list[str] | None = None, title_override: str | None = None,
    published_override: str | None = None, verified_silence: bool = False, replace_path: Path | None = None,
) -> dict:
    """Shared finalize wrapper across Douyin, Bilibili, and Xiaohongshu."""
    started = time.perf_counter()
    data = read_json(manifest_path)
    body = reviewed_path.read_text(encoding="utf-8")
    final_tags = tags if tags is not None else data.get("tags")
    raw_dir = output_dir or data.get("process_root") or data.get("output_dir") or ""
    if not str(raw_dir):
        raise ValueError("请提供 --output-dir 或在 manifest 中指定输出目录")
    target_dir = Path(raw_dir).expanduser().resolve()
    draft_path = Path(data["draft"]) if data.get("draft") else None
    draft_text = draft_path.read_text(encoding="utf-8") if draft_path and draft_path.is_file() else None
    if published_override is not None:
        raw_pub = published_override
    elif data.get("date_kind") == "edited" and platform != "小红书":
        raw_pub = ""
    else:
        raw_pub = data.get("date") if data.get("date") is not None else (data.get("published") or data.get("published_display") or "")
    like_val = data.get("like_count") if "like_count" in data else data.get("likes", "")
    content_type = "图文" if data.get("content_type") in ("图文", "纯文字") else "视频"
    live_m = Path(data["media"]) if data.get("media") else None
    cur_sig = media_signature(live_m) if (live_m and live_m.is_file()) else str(data.get("media_sig") or "")
    stored_silence = bool(data.get("verified_silence")) and "verified_silence_sig" in data and str(data.get("verified_silence_sig") or "") == cur_sig
    allow_silence = bool(verified_silence or stored_silence)
    effective_replace = replace_path
    if effective_replace is None and data.get("status") == "saved" and data.get("output") and data.get("output_sha256"):
        prev_out = Path(data["output"]).expanduser().resolve()
        if prev_out.parent == target_dir and prev_out.is_file():
            try:
                if hashlib.sha256(prev_out.read_bytes()).hexdigest() == str(data["output_sha256"]):
                    effective_replace = prev_out
            except OSError:
                pass
    saved = save_standard_note(
        url=data["url"], platform=platform, title=title_override if title_override is not None else data.get("title", ""),
        author=data.get("author", ""), published=raw_pub, like_count=like_val, content_type=content_type,
        tags=final_tags, body=body, output_dir=target_dir, work_id=str(data.get("id") or data.get("key") or ""),
        draft_text=draft_text, is_transcript=(content_type == "视频"), replace_path=effective_replace,
        clean_title_flag=(title_override is None), backup_dir=manifest_path.parent, verified_silence=allow_silence,
    )
    if saved["status"] != "saved":
        return saved
    if allow_silence:
        data["verified_silence"] = True
        data["verified_silence_sig"] = cur_sig
    data.update(status="saved", output=saved["output"], title=saved["title"], published=saved["published"], tags=saved.get("tags", final_tags), output_dir=str(target_dir))
    if saved.get("output_written") and saved.get("output_sha256"):
        data["output_sha256"] = saved["output_sha256"]
    timings = data.setdefault("timings", {})
    timings["finalize"] = round(time.perf_counter() - started, 3)
    if "started_at_epoch" in data:
        elapsed = round(time.time() - float(data["started_at_epoch"]), 3)
        timings["through_save_wall"] = timings["total_observed"] = elapsed
        if "prepare_total" in timings:
            timings["review_and_finalize"] = round(elapsed - float(timings["prepare_total"]), 3)
    write_json(manifest_path, data)
    return {**data, "used_entry_date": saved["used_entry_date"], "review_stats": saved["review_stats"]}


def _cli_main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "acquisition":
        parser = argparse.ArgumentParser(description="Record one complete authorized acquisition attempt; never reset ABAB")
        parser.add_argument("command")
        parser.add_argument("action", choices=("begin", "finish", "skip"))
        parser.add_argument("path", type=Path)
        parser.add_argument("--route", choices=("A", "B"))
        parser.add_argument("--outcome", choices=("success", "failed", "denied"))
        parser.add_argument("--detail", default="")
        parser.add_argument("--media", type=Path)
        parser.add_argument("--info-json", type=Path)
        args = parser.parse_args()
        result = acquisition(args.path, args.action, args.route, args.outcome, args.detail, args.media, read_json(args.info_json) if args.info_json else None)
        print(json.dumps(result["acquisition"], ensure_ascii=False))
        return 0

    if len(sys.argv) >= 2 and sys.argv[1] == "fetch-media":
        parser = argparse.ArgumentParser(description="Fetch verified full media stream immediately")
        parser.add_argument("command")
        parser.add_argument("--url", action="append", required=True)
        parser.add_argument("--platform", choices=tuple(sorted(PLATFORM_REFERERS)), required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--state", type=Path)
        parser.add_argument("--info-json", type=Path)
        parser.add_argument("--route", choices=("A", "B", "auto"), default="auto")
        parser.add_argument("--timeout", type=int, default=180)
        parser.add_argument("--require-audio", action="store_true")
        parser.add_argument("--expected-duration", type=float)
        args = parser.parse_args()
        print(json.dumps(fetch_verified_media(args.url, args.platform, args.output, args.state, args.route, args.timeout, require_audio=args.require_audio, expected_duration=args.expected_duration, info_json=args.info_json), ensure_ascii=False, indent=2))
        return 0

    if len(sys.argv) >= 2 and sys.argv[1] == "save-note":
        parser = argparse.ArgumentParser(description="Save canonical 7-field Markdown note with quality gate")
        parser.add_argument("command")
        parser.add_argument("--meta", type=Path, required=True)
        parser.add_argument("--body", type=Path, required=True)
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--verified-silence", action="store_true")
        args = parser.parse_args()
        meta = read_json(args.meta)
        draft_text = Path(meta["draft"]).read_text(encoding="utf-8") if meta.get("draft") and Path(meta["draft"]).is_file() else None
        content_type = meta.get("content_type") or "图文"
        result = save_standard_note(
            url=meta["url"], platform=meta["platform"], title=meta.get("title") or "", author=meta.get("author") or "",
            published=meta.get("published"), like_count=meta.get("like_count", ""), content_type=content_type,
            tags=meta.get("tags") or [], body=args.body.read_text(encoding="utf-8"), output_dir=args.output_dir,
            work_id=str(meta.get("id") or ""), draft_text=draft_text, is_transcript=(content_type == "视频"),
            clean_title_flag=bool(meta.get("clean_title", True)), backup_dir=args.meta.resolve().parent,
            verified_silence=bool(args.verified_silence or meta.get("verified_silence")),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if len(sys.argv) >= 2 and sys.argv[1] == "env":
        parser = argparse.ArgumentParser(description="Inspect local readiness, prepare/launch browser, run smoke ASR, or write stamp")
        parser.add_argument("command")
        parser.add_argument("action", choices=("status", "check", "mark-ready", "browser-launcher"))
        parser.add_argument("--agent", default="")
        parser.add_argument("--output-dir", type=Path)
        parser.add_argument("--smoke", action="store_true")
        parser.add_argument("--speakers", action="store_true")
        parser.add_argument("--browser-proof", type=Path)
        parser.add_argument("--asr-proof", type=Path)
        parser.add_argument("--reuse-machine-asr", action="store_true")
        parser.add_argument("--chrome", default="")
        parser.add_argument("--node", default="")
        parser.add_argument("--launch", action="store_true")
        args = parser.parse_args()
        if args.action == "status":
            print(json.dumps(env_status(args.agent or None), ensure_ascii=False, indent=2))
            return 0
        if args.action == "browser-launcher":
            result = env_browser_launcher(chrome_path=args.chrome, launch=args.launch)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") in ("ready", "connected") else 1
        if args.action == "check":
            dirs = [args.output_dir] if args.output_dir else []
            result = check_runtime(dirs, executable, speakers=args.speakers, require_downloader=True, smoke=args.smoke)
            if args.asr_proof:
                args.asr_proof.parent.mkdir(parents=True, exist_ok=True)
                write_json(args.asr_proof, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not args.browser_proof or not args.agent or not args.chrome or not args.node:
            raise ValueError("mark-ready 需要 --browser-proof、--agent、--chrome、--node")
        print(json.dumps(env_mark_ready(args.browser_proof, args.asr_proof, args.reuse_machine_asr, args.agent, args.chrome, args.node), ensure_ascii=False, indent=2))
        return 0

    if len(sys.argv) >= 3 and sys.argv[1] == "_diarize":
        print(json.dumps(diarize(Path(sys.argv[2]), Path(sys.argv[3])), ensure_ascii=False))
        return 0

    raise ValueError("未知 media_common 子命令")


if __name__ == "__main__":
    try:
        raise SystemExit(_cli_main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": safe_error(exc)}, ensure_ascii=False))
        raise SystemExit(1)
