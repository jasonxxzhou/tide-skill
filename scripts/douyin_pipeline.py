#!/usr/bin/env python3
"""潮汐 · 抖音视频一键流水线（解析 → 下载 → 音频 → 本地逐字稿）

针对 v2 的完整优化：反爬兜底 + 免 API Key 本地转写 + 省时间省 Token。

与旧版 douyin_extractor.py 的区别：
- 解析：douyin.wtf 公开解析 API 优先（demo 账号自动登录），绕开抖音 Web 反爬；
  失败自动回落旧版直连解析。
- 转写：内置 faster-whisper 本地转写，无需 DOUYIN_TRANSCRIBE_PROVIDER / DOUYIN_API_KEY。
  依赖缺失时自动 pip 安装；模型自动下载（默认 hf-mirror 镜像，国内可用）。
- Windows 修复：HuggingFace Hub 在 Windows 下快照硬链接失败会留下 0 字节模型文件，
  本脚本自动检测并从 blobs/ 复制修复。
- 省 Token：逐字稿全部落盘（JSON + Markdown），控制台只打印精简进度与摘要。

用法：
    python scripts/douyin_pipeline.py extract "https://v.douyin.com/xxx" -o ./output
    python scripts/douyin_pipeline.py extract "https://v.douyin.com/xxx" -o ./output --model small --lang zh
    python scripts/douyin_pipeline.py parse  "https://v.douyin.com/xxx"   # 仅解析元数据+直链
    python scripts/douyin_pipeline.py transcribe audio.mp3 --out-dir ./output  # 仅转写已有音频

输出目录结构：
    {output}/{video_id}/
    ├── {video_id}.mp4        # 无水印视频（--save-video 时保留）
    ├── {video_id}.mp3        # 16kHz 单声道音频（转写输入）
    ├── {video_id}.transcript.json  # 带时间戳分段原始数据
    └── {video_id}.transcript.md    # 可读逐字稿（含金句区，供潮汐路线C直接落盘）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

UA_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

WTF_API = "https://api.douyin.wtf"
WTF_DEMO = f"{WTF_API}/api/v1/auth/demo"
WTF_LOGIN = f"{WTF_API}/api/v1/auth/login"
WTF_PARSE = f"{WTF_API}/api/v1/parse?wait=30"
DEMO_USER = "demo"  # demo 密码由 /auth/demo 动态返回，不做硬编码

HF_MIRROR = "https://hf-mirror.com"
WHISPER_LANG_DEFAULT = "zh"


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    raise SystemExit("错误: 未找到 ffmpeg/ffprobe，请先安装（https://ffmpeg.org/download.html）")


# ---------------------------------------------------------------- 解析层

def _http_json(method: str, url: str, **kw) -> dict:
    import requests
    r = requests.request(method, url, timeout=kw.pop("timeout", 45), **kw)
    r.raise_for_status()
    return r.json()


def parse_via_wtf(share_url: str) -> dict | None:
    """douyin.wtf 解析：demo 登录 → session cookie → parse。反爬兜底首选。"""
    try:
        demo = _http_json("GET", WTF_DEMO)
        if not demo.get("success"):
            return None
        cred = demo["data"]
        import requests
        s = requests.Session()
        r = s.post(WTF_LOGIN, json={"username": cred.get("username", DEMO_USER),
                                    "password": cred["password"]}, timeout=30)
        r.raise_for_status()
        resp = s.post(WTF_PARSE, json={"url": share_url}, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if body.get("success") and body.get("data", {}).get("kind") in ("video", "photo"):
            d = body["data"]
            media = d.get("media", {}).get("video") or (d.get("media", {}).get("photo") or {}).get("url")
            video_url = media.get("url") if isinstance(media, dict) else media
            return {
                "source": "douyin.wtf",
                "video_id": d.get("content_id"),
                "title": d.get("title") or d.get("description"),
                "desc": d.get("description"),
                "author": (d.get("author") or {}).get("nickname"),
                "author_stats": (d.get("author") or {}).get("stats"),
                "tags": d.get("tags"),
                "stats": d.get("stats"),
                "created_at": d.get("created_at"),
                "duration_ms": d.get("duration_ms"),
                "web_url": d.get("web_url"),
                "video_url": video_url,
            }
    except Exception as e:  # noqa: BLE001 - 兜底路径，任何异常都回落
        log(f"[parse] douyin.wtf 解析失败（{e.__class__.__name__}: {e}），回落直连解析")
    return None


def parse_via_direct(share_url: str) -> dict | None:
    """旧版直连解析（2026 起常被反爬拦截，仅作兜底）。"""
    try:
        import requests
        r = requests.get(share_url, headers={"User-Agent": UA_MOBILE}, timeout=30, allow_redirects=True)
        page = r.text
        m = re.search(r"/video/(\d+)", str(r.url))
        video_id = m.group(1) if m else None
        m2 = re.search(r'"desc":"(.*?)"', page)
        desc = m2.group(1).encode().decode("unicode_escape", errors="ignore") if m2 else None
        return {"source": "direct", "video_id": video_id, "title": desc, "desc": desc,
                "video_url": None, "author": None, "tags": None, "stats": None,
                "duration_ms": None, "created_at": None, "web_url": str(r.url)}
    except Exception as e:  # noqa: BLE001
        log(f"[parse] 直连解析失败: {e}")
        return None


def parse_video(share_url: str) -> dict:
    info = parse_via_wtf(share_url) or parse_via_direct(share_url)
    if not info or (not info.get("video_url") and not info.get("video_id")):
        raise SystemExit("错误: 所有解析通道均失败，请稍后重试或手动提供视频直链")
    if not info.get("video_url") and info.get("video_id"):
        # 有 id 无直链：构造 share 页播放地址（可能带水印），尽力而为
        info["video_url"] = f"https://www.iesdouyin.com/aweme/v1/play/?video_id={info['video_id']}"
    return info


# ---------------------------------------------------------------- 下载层

def download(url: str, path: Path) -> Path:
    import requests
    with requests.get(url, headers={"User-Agent": UA_DESKTOP}, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return path


def extract_audio(video: Path, audio: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "64k", str(audio)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return audio


# ---------------------------------------------------------------- 转写层

def _pip_install(pkgs: list[str]) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *pkgs])


def ensure_faster_whisper() -> None:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        log("[asr] 安装 faster-whisper ...")
        _pip_install(["faster-whisper"])


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"


def fix_hf_zero_byte_snapshots(repo_id: str) -> bool:
    """Windows 坑：HF Hub（1.x / Xet 存储）在 Windows 下物化快照的硬链接可能失败，
    快照目录只剩 0 字节占位文件而 blobs/ 中数据完好。
    通过 HfApi 的文件元数据（LFS sha256 / git blob_id）精确匹配 blob 并复制修复。
    返回是否有修复动作。"""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        info = api.model_info(repo_id, files_metadata=True)
    except Exception:  # noqa: BLE001
        return False
    cache = _repo_cache_dir(repo_id)
    blobs = cache / "blobs"
    snaps = cache / "snapshots"
    if not blobs.is_dir() or not snaps.is_dir():
        return False
    fixed = False
    for sibling in info.siblings:
        fname = sibling.rfilename
        lfs = getattr(sibling, "lfs", None)
        sha = (lfs or {}).get("sha256") if isinstance(lfs, dict) else None
        sha = sha or getattr(sibling, "blob_id", None)
        if not sha:
            continue
        blob = blobs / sha
        if not blob.is_file() or blob.stat().st_size == 0:
            continue
        for snap in snaps.iterdir():
            f = snap / fname
            if f.is_file() and f.stat().st_size == 0:
                shutil.copy2(blob, f)
                fixed = True
    return fixed


def ensure_whisper_model(model_size: str) -> None:
    """下载模型（默认 hf-mirror），并在下载后验证+修复 0 字节快照。"""
    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)  # 国内默认镜像；海外用户可显式覆盖
    from huggingface_hub import snapshot_download
    repo_id = f"Systran/faster-whisper-{model_size}"
    log(f"[asr] 确保模型 {repo_id} 就绪（镜像: {os.environ['HF_ENDPOINT']}）...")
    for attempt in range(3):
        path = Path(snapshot_download(repo_id, allow_patterns=["config.json", "model.bin",
                                                               "tokenizer.json", "vocabulary.txt"]))
        model_bin = path / "model.bin"
        if model_bin.exists() and model_bin.stat().st_size > 10_000_000:
            return
        if fix_hf_zero_byte_snapshots(repo_id):
            if model_bin.exists() and model_bin.stat().st_size > 10_000_000:
                log("[asr] 已修复 Windows 0 字节快照文件")
                return
        log(f"[asr] 模型文件异常（第 {attempt + 1}/3 次），重试下载...")
        shutil.rmtree(_repo_cache_dir(repo_id), ignore_errors=True)
    raise SystemExit("错误: 模型下载失败，请检查网络后重试")


def _repo_cache_dir(repo_id: str) -> Path:
    return _hf_cache_dir() / f"models--{repo_id.replace('/', '--')}"


def transcribe(audio: Path, out_dir: Path, video_id: str, model_size: str = "small",
               lang: str = WHISPER_LANG_DEFAULT) -> tuple[Path, Path, int]:
    ensure_faster_whisper()
    ensure_whisper_model(model_size)
    from faster_whisper import WhisperModel

    log(f"[asr] 本地转写中（模型 {model_size}/int8/CPU）...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), language=lang, vad_filter=True, beam_size=5)

    seg_list = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
                for s in segments]
    json_path = out_dir / f"{video_id}.transcript.json"
    json_path.write_text(json.dumps({"language": info.language, "duration": info.duration,
                                     "model": model_size, "segments": seg_list},
                                    ensure_ascii=False, indent=1), encoding="utf-8")

    md_path = out_dir / f"{video_id}.transcript.md"
    md_path.write_text(render_transcript_md(video_id, seg_list), encoding="utf-8")
    return json_path, md_path, len(seg_list)


def _ts(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def render_transcript_md(video_id: str, seg_list: list[dict]) -> str:
    lines = [f"# 口播逐字稿（{video_id}）", ""]
    for s in seg_list:
        lines.append(f"**[{_ts(s['start'])}]** {s['text']}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程

def cmd_extract(args) -> None:
    ensure_ffmpeg()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    log("[parse] 解析分享链接 ...")
    info = parse_video(args.share_url)
    video_id = info.get("video_id") or "douyin_video"
    log(f"[parse] ✓ {info.get('title') or info.get('desc') or video_id}"
        f" | 作者: {info.get('author') or '未知'}"
        f" | 时长: {(info.get('duration_ms') or 0) / 1000:.0f}s | 来源: {info['source']}")

    vdir = out_dir / str(video_id)
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    audio = vdir / f"{video_id}.mp3"
    if not audio.exists():
        log("[download] 下载视频 ...")
        video = vdir / f"{video_id}.mp4"
        download(info["video_url"], video)
        if not args.save_video:
            extract_audio(video, audio)
            video.unlink()
        else:
            extract_audio(video, audio)
    else:
        log("[download] 音频已存在，跳过下载")

    json_path, md_path, n = transcribe(audio, vdir, str(video_id), args.model, args.lang)

    # 精简摘要（省 Token：全文已落盘，不回显）
    texts = [s["text"] for s in json.loads(json_path.read_text(encoding="utf-8"))["segments"]]
    full = "".join(texts)
    log(f"\n[done] ✓ 逐字稿 {n} 段 / 约 {len(full)} 字")
    log(f"  逐字稿 Markdown: {md_path}")
    log(f"  逐字稿 JSON:     {json_path}")
    log(f"  音频: {audio}")
    log(f"  元数据: {vdir / 'info.json'}")
    log(f"  开头预览: {full[:120]}...")


def cmd_parse(args) -> None:
    info = parse_video(args.share_url)
    print(json.dumps(info, ensure_ascii=False, indent=1))


def cmd_transcribe(args) -> None:
    ensure_ffmpeg()
    audio = Path(args.audio)
    out_dir = Path(args.out_dir) or audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    video_id = audio.stem
    json_path, md_path, n = transcribe(audio, out_dir, video_id, args.model, args.lang)
    log(f"[done] ✓ {n} 段 → {md_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="抖音视频 → 本地逐字稿 一键流水线（潮汐路线C加速版）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="解析+下载+转写 一条龙")
    pe.add_argument("share_url")
    pe.add_argument("-o", "--output", default="./output")
    pe.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium"],
                    help="whisper 模型，默认 small（中文质量/速度平衡）")
    pe.add_argument("--lang", default=WHISPER_LANG_DEFAULT)
    pe.add_argument("-v", "--save-video", action="store_true", help="保留视频文件")
    pe.set_defaults(func=cmd_extract)

    pp = sub.add_parser("parse", help="仅解析元数据与直链")
    pp.add_argument("share_url")
    pp.set_defaults(func=cmd_parse)

    pt = sub.add_parser("transcribe", help="仅转写已有音频文件")
    pt.add_argument("audio")
    pt.add_argument("--out-dir", default=None)
    pt.add_argument("--model", default="small")
    pt.add_argument("--lang", default=WHISPER_LANG_DEFAULT)
    pt.set_defaults(func=cmd_transcribe)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
