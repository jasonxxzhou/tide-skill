#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Portions Copyright (c) 2026 lens
# Licensed under the MIT License: https://opensource.org/licenses/MIT

"""
抖音视频内容提取脚本（Node.js 版本移植）

功能:
1. 从抖音分享链接获取无水印视频下载链接
2. 下载视频并提取音频
3. 使用硅基流动 API 从音频中提取文本
4. 提取视频首帧作为封面
5. 返回完整的视频数据

环境变量:
- `DOUYIN_TRANSCRIBE_PROVIDER`: 转写提供商，支持 `siliconflow` / `openai-compatible` / `none`
- `DOUYIN_API_KEY`: 默认转写 API 密钥
- `API_KEY`: 兼容的备用 API 密钥
- `DOUYIN_API_BASE_URL`: 自定义转写接口地址
- `DOUYIN_TRANSCRIBE_MODEL`: 自定义转写模型

依赖:
- ffmpeg: 音视频处理
- ffprobe: 媒体信息获取
"""

import os
import sys
import time
import json
import argparse
import subprocess
import requests
from pathlib import Path


# 配置
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
}

DEFAULT_PROVIDER = "siliconflow"
DEFAULT_API_BASE_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"
OPENAI_DEFAULT_API_BASE_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_DEFAULT_MODEL = "whisper-1"


def get_transcribe_config():
    provider = (os.getenv("DOUYIN_TRANSCRIBE_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    api_key = os.getenv("DOUYIN_API_KEY") or os.getenv("API_KEY")

    if provider == "none":
        return {
            "provider": provider,
            "api_key": api_key,
            "api_base_url": None,
            "model": None,
        }

    if provider == "openai-compatible":
        return {
            "provider": provider,
            "api_key": api_key,
            "api_base_url": os.getenv("DOUYIN_API_BASE_URL") or OPENAI_DEFAULT_API_BASE_URL,
            "model": os.getenv("DOUYIN_TRANSCRIBE_MODEL") or OPENAI_DEFAULT_MODEL,
        }

    return {
        "provider": "siliconflow",
        "api_key": api_key,
        "api_base_url": os.getenv("DOUYIN_API_BASE_URL") or DEFAULT_API_BASE_URL,
        "model": os.getenv("DOUYIN_TRANSCRIBE_MODEL") or DEFAULT_MODEL,
    }


def http_request(url, method="GET", headers=None, data=None, stream=False):
    """
    HTTP 请求工具函数

    Args:
        url: 请求URL
        method: 请求方法
        headers: 请求头
        data: 请求数据
        stream: 是否流式传输

    Returns:
        响应数据或响应对象
    """
    if headers is None:
        headers = HEADERS.copy()
    else:
        headers = {**HEADERS, **headers}

    response = requests.request(method, url, headers=headers, data=data, stream=stream, timeout=30)

    if stream:
        return response

    try:
        return response.json()
    except:
        return response.text


def download_file(url, filepath, show_progress=True):
    """
    下载文件

    Args:
        url: 下载URL
        filepath: 保存路径
        show_progress: 是否显示进度

    Returns:
        保存的文件路径
    """
    response = requests.get(url, headers=HEADERS, stream=True, timeout=60)

    # 处理重定向
    if response.status_code >= 300 and response.status_code < 400:
        return download_file(response.headers["location"], filepath, show_progress)

    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}")

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0

    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if show_progress and total_size > 0:
                progress = (downloaded / total_size * 100)
                sys.stdout.write(f"\r下载进度: {progress:.1f}%")
                sys.stdout.flush()

    if show_progress:
        print(f"\n文件已保存: {filepath}")

    return filepath


def run_ffmpeg(args):
    """
    运行 ffmpeg 命令

    Args:
        args: ffmpeg 参数列表

    Raises:
        Exception: ffmpeg 执行失败
    """
    try:
        subprocess.run(
            ["ffmpeg"] + args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except subprocess.CalledProcessError as e:
        raise Exception(f"ffmpeg 执行失败: {e.stderr}")
    except FileNotFoundError:
        raise Exception("ffmpeg 未安装，请先安装 ffmpeg")


def get_media_info(filepath):
    """
    获取媒体信息

    Args:
        filepath: 媒体文件路径

    Returns:
        dict: 媒体信息（时长、大小）
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        info = json.loads(result.stdout)
        format_info = info.get("format", {})
        return {
            "duration": float(format_info.get("duration", 0)),
            "size": int(format_info.get("size", 0))
        }
    except:
        # 如果 ffprobe 失败，返回基本文件信息
        stat = os.stat(filepath)
        return {"duration": 0, "size": stat.st_size}


def follow_redirect(url):
    """
    跟踪重定向获取真实 URL

    Args:
        url: 可能重定向的 URL

    Returns:
        str: 真实 URL
    """
    response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
    if response.status_code >= 300 and response.status_code < 400:
        location = response.headers.get("location", "")
        if location.startswith("http"):
            return location
        # 相对路径处理
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{location}"
    return url


def parse_share_url(share_text):
    """
    解析抖音分享链接

    Args:
        share_text: 分享链接文本

    Returns:
        dict: 视频信息（url, title, video_id）
    """
    # 提取 URL
    import re
    url_match = re.search(r"https?://[^\s]+", share_text)
    if not url_match:
        raise Exception("未找到有效的分享链接")

    share_url = url_match.group(0)

    # 如果是短链，先跟踪重定向获取真实 URL
    if "v.douyin.com" in share_url:
        share_url = follow_redirect(share_url)

    # 从真实 URL 中提取数字视频 ID
    video_id_match = re.search(r"/video/(\d+)", share_url)
    aweme_id = video_id_match.group(1) if video_id_match else share_url.split("/")[-1].split("?")[0]

    # 获取视频详情
    api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
    video_data = None

    try:
        # 尝试直接调用 API
        api_response = http_request(api_url)

        # 检查响应是否为 JSON
        if isinstance(api_response, str):
            # 如果返回字符串，尝试从页面 HTML 中提取数据
            page_url = share_url if share_url.startswith("http") else f"https://www.douyin.com{share_url}"
            page_content = http_request(page_url)

            if isinstance(page_content, str):
                # 尝试从页面中提取视频数据
                data_match = re.search(r'window\._ROUTER_DATA\s*=\s*(.*?)</script>', page_content)
                if data_match:
                    import json
                    json_data = json.loads(data_match.group(1))
                    loader_data = json_data.get("loaderData", json_data)

                    # 尝试多种可能的路径
                    video_data = (
                        loader_data.get("video_(id)/page", {}).get("videoInfoRes", {}).get("item_list", [{}])[0]
                        or loader_data.get("note_(id)/page", {}).get("videoInfoRes", {}).get("item_list", [{}])[0]
                    )

                    if not video_data or not video_data.get("video"):
                        # 尝试直接从页面搜索视频信息
                        aweme_match = re.search(r'"aweme_id":\s*"(\d+)"', page_content)
                        if aweme_match:
                            aweme_id = aweme_match.group(1)
                            raise Exception("需要重新解析视频ID")
                        else:
                            raise Exception("无法从页面中提取视频信息")
        else:
            video_data = api_response.get("aweme_detail", api_response)

        if not video_data or not video_data.get("video"):
            raise Exception("无法解析视频信息：video 数据为空")

        # 获取无水印视频链接
        video_info = video_data.get("video", {})
        play_addr = video_info.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        video_url = url_list[0].replace("playwm", "play") if url_list else None

        if not video_url:
            download_addr = video_info.get("download_addr", {})
            url_list = download_addr.get("url_list", [])
            video_url = url_list[0] if url_list else None

        desc = video_data.get("desc", f"douyin_{video_info.get('id', 'unknown')}")
        video_id = video_info.get("id", video_data.get("aweme_id", aweme_id))

        # 清理标题中的非法字符
        title = re.sub(r'[\\/:*?"<>|]', '_', desc)

        return {
            "url": video_url,
            "title": title,
            "video_id": str(video_id)
        }
    except Exception as e:
        raise Exception(f"解析视频信息失败: {str(e)}")


def extract_audio(video_path, show_progress=True):
    """
    从视频中提取音频

    Args:
        video_path: 视频文件路径
        show_progress: 是否显示进度

    Returns:
        str: 音频文件路径
    """
    audio_path = video_path.replace(".mp4", ".mp3")

    if show_progress:
        print("正在提取音频...")

    run_ffmpeg([
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "0",
        "-y",
        audio_path
    ])

    if show_progress:
        print(f"音频已保存: {audio_path}")

    return audio_path


def extract_cover(video_path, show_progress=True):
    """
    从视频中提取首帧作为封面

    Args:
        video_path: 视频文件路径
        show_progress: 是否显示进度

    Returns:
        str: 封面图片路径
    """
    cover_path = video_path.replace(".mp4", ".jpg")

    if show_progress:
        print("正在提取封面...")

    run_ffmpeg([
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        cover_path
    ])

    if show_progress:
        print(f"封面已保存: {cover_path}")

    return cover_path


def transcribe_audio(audio_path, config, show_progress=True):
    """
    语音转文字

    Args:
        audio_path: 音频文件路径
        config: 转写配置
        show_progress: 是否显示进度

    Returns:
        str: 识别的文本
    """
    if show_progress:
        print("正在识别语音...")

    provider = config.get("provider", DEFAULT_PROVIDER)
    if provider == "none":
        raise Exception("当前配置已禁用转写，请设置 DOUYIN_TRANSCRIBE_PROVIDER 并提供可用 API")

    api_key = config.get("api_key")
    if not api_key:
        raise Exception("未设置 API 密钥，请设置 DOUYIN_API_KEY 或 API_KEY 环境变量")

    api_base_url = config.get("api_base_url") or DEFAULT_API_BASE_URL
    model = config.get("model") or DEFAULT_MODEL

    # 读取音频文件
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    # 创建 multipart/form-data
    import io
    boundary = "----FormBoundary" + "".join([str(ord(c)) for c in str(time.time())])
    body = io.BytesIO()

    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(audio_path)}"\r\n'.encode())
    body.write("Content-Type: audio/mpeg\r\n\r\n".encode())
    body.write(audio_data)
    body.write(f"\r\n--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'.encode())
    body.write(f"--{boundary}--\r\n".encode())

    body.seek(0)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    }

    response = requests.post(api_base_url, data=body.getvalue(), headers=headers, timeout=60)

    if response.status_code != 200:
        raise Exception(f"语音识别失败: {response.text}")

    result = response.json()
    text = result.get("text", "")
    if not text:
        text = json.dumps(result, ensure_ascii=False)

    return text


def extract_video_data(share_link, output_dir="./output", save_video=False, show_progress=True):
    """
    提取视频数据的主函数

    Args:
        share_link: 抖音分享链接
        output_dir: 输出目录
        save_video: 是否保存视频文件
        show_progress: 是否显示进度

    Returns:
        dict: 包含完整视频数据的字典
    """
    transcribe_config = get_transcribe_config()

    if show_progress:
        print("正在解析抖音分享链接...")

    # 解析视频信息
    video_info = parse_share_url(share_link)

    # 创建输出目录
    output_folder = os.path.join(output_dir, video_info["video_id"])
    os.makedirs(output_folder, exist_ok=True)

    # 下载视频
    if show_progress:
        print("正在下载视频...")

    video_path = os.path.join(output_folder, f"{video_info['video_id']}.mp4")
    video_path = download_file(video_info["url"], video_path, show_progress)

    # 获取媒体信息
    media_info = get_media_info(video_path)

    # 提取音频
    audio_path = extract_audio(video_path, show_progress)

    # 提取封面
    cover_path = extract_cover(video_path, show_progress)

    # 语音转文字
    text_content = transcribe_audio(audio_path, transcribe_config, show_progress)

    # 清理临时文件
    if not save_video:
        try:
            os.remove(video_path)
        except:
            pass

    try:
        os.remove(audio_path)
    except:
        pass

    return {
        "video_info": video_info,
        "media_info": media_info,
        "text_content": text_content,
        "cover_path": cover_path,
        "video_path": video_path if save_video else None,
        "output_folder": output_folder
    }


def main():
    parser = argparse.ArgumentParser(description="抖音视频内容提取工具")
    parser.add_argument("command", help="命令: info, download, extract")
    parser.add_argument("share_link", help="抖音分享链接")
    parser.add_argument("-o", "--output", default="./output", help="输出目录")
    parser.add_argument("-v", "--save-video", action="store_true", help="保存视频文件")
    parser.add_argument("--no-progress", action="store_true", help="不显示进度")

    args = parser.parse_args()

    if not args.command or not args.share_link:
        print("""
抖音视频内容提取工具

用法:
  python douyin_extractor.py info <分享链接>      - 获取视频信息
  python douyin_extractor.py download <链接> -o <目录>  - 下载视频
  python douyin_extractor.py extract <链接> -o <目录>   - 提取文案（推荐）

环境变量:
  DOUYIN_TRANSCRIBE_PROVIDER - `siliconflow` / `openai-compatible` / `none`
  DOUYIN_API_KEY 或 API_KEY  - 转写 API 密钥（`extract` 时需要）
  DOUYIN_API_BASE_URL        - 自定义转写接口地址（可选）
  DOUYIN_TRANSCRIBE_MODEL    - 自定义转写模型（可选）
""")
        sys.exit(1)

    show_progress = not args.no_progress

    try:
        if args.command == "info":
            info = parse_share_url(args.share_link)
            print("\n" + "=" * 50)
            print("视频信息:")
            print("=" * 50)
            print(f"视频ID: {info['video_id']}")
            print(f"标题: {info['title']}")
            print(f"下载链接: {info['url']}")
            print("=" * 50)

        elif args.command == "download":
            info = parse_share_url(args.share_link)
            video_path = os.path.join(args.output, f"{info['video_id']}.mp4")
            os.makedirs(args.output, exist_ok=True)
            download_file(info["url"], video_path, show_progress)
            print(f"\n视频已保存到: {video_path}")

        elif args.command == "extract":
            result = extract_video_data(args.share_link, args.output, args.save_video, show_progress)
            print("\n" + "=" * 50)
            print("提取完成!")
            print("=" * 50)
            print(f"视频ID: {result['video_info']['video_id']}")
            print(f"标题: {result['video_info']['title']}")
            print(f"时长: {result['media_info']['duration']:.2f}秒")
            print(f"封面: {result['cover_path']}")
            print("=" * 50)
            print("\n识别的文字内容:\n")
            print(result["text_content"][:500] + "..." if len(result["text_content"]) > 500 else result["text_content"])
            print("\n" + "=" * 50)
        else:
            print(f"未知命令: {args.command}")
            sys.exit(1)

    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
