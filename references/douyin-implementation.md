# 技术实现说明

## 概述

本 Skill 使用抖音公开 API 和可配置的语音识别接口实现抖音视频内容提取功能，不依赖第三方视频提取服务。

---

## 技术架构

### 1. 视频信息获取

**实现方式**：直接调用抖音公开 API

**API 端点**：
```
https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}
```

**请求头**：
```
User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15
```

**流程**：
1. 解析抖音分享链接
2. 如果是短链（v.douyin.com），跟踪重定向获取真实 URL
3. 从 URL 中提取视频 ID
4. 调用抖音 API 获取视频详情
5. 提取无水印视频链接（替换 `playwm` 为 `play`）

---

### 2. 视频下载

**实现方式**：使用 Python requests 库直接下载

**特点**：
- 支持进度显示
- 自动处理重定向
- 下载无水印视频

---

### 3. 音频提取

**工具**：ffmpeg

**命令**：
```bash
ffmpeg -i video.mp4 -vn -acodec libmp3lame -q:a 0 audio.mp3
```

**参数说明**：
- `-vn`：不包含视频流
- `-acodec libmp3lame`：使用 MP3 编码
- `-q:a 0`：最高质量

---

### 4. 封面提取

**工具**：ffmpeg

**命令**：
```bash
ffmpeg -i video.mp4 -vframes 1 -q:v 2 cover.jpg
```

**参数说明**：
- `-vframes 1`：只提取一帧
- `-q:v 2`：图片质量（2 是高质量）

---

### 5. 语音识别

**服务**：可配置，默认硅基流动（SiliconFlow），也支持 OpenAI 兼容接口

**API 端点**：
```
默认：
https://api.siliconflow.cn/v1/audio/transcriptions
```

**模型**：默认 `FunAudioLLM/SenseVoiceSmall`，可通过环境变量覆盖

**认证方式**：Bearer Token（API Key）

**请求格式**：multipart/form-data

**请求参数**：
- `file`：音频文件（MP3 格式）
- `model`：模型名称

**响应示例**：
```json
{
  "text": "识别的文本内容"
}
```

---

## 系统依赖

### 必需工具

1. **ffmpeg**
   - 用途：音视频处理（提取音频、封面）
   - 版本要求：>= 4.0
   - 安装方式：
     ```bash
     # Ubuntu/Debian
     sudo apt-get install ffmpeg

     # macOS
     brew install ffmpeg

     # Windows
     # 从 https://ffmpeg.org/download.html 下载
     ```

2. **ffprobe**
   - 用途：获取媒体信息（时长、大小）
   - 通常随 ffmpeg 一起安装

### Python 依赖

```
requests>=2.31.0
```

---

## 环境变量

### 必需配置

- `DOUYIN_TRANSCRIBE_PROVIDER`：`siliconflow` / `openai-compatible` / `none`
- `DOUYIN_API_KEY` 或 `API_KEY`：语音识别 API 密钥（仅转写时需要）
- `DOUYIN_API_BASE_URL`：自定义转写接口地址
- `DOUYIN_TRANSCRIBE_MODEL`：自定义转写模型

### 配置示例

```bash
export DOUYIN_API_KEY="sk-xxxxxxxxxxxxxx"

export DOUYIN_TRANSCRIBE_PROVIDER="openai-compatible"
export DOUYIN_API_BASE_URL="https://api.openai.com/v1/audio/transcriptions"
export DOUYIN_TRANSCRIBE_MODEL="whisper-1"
```

---

## 数据流

```
用户输入抖音链接
    ↓
解析链接，提取视频ID
    ↓
调用抖音 API 获取视频详情
    ↓
下载无水印视频
    ↓
提取音频 (ffmpeg)
    ↓
提取封面 (ffmpeg)
    ↓
语音识别 (已配置的转写 API)
    ↓
返回完整数据
    ↓
智能体生成 Markdown 文档
    ↓
输出给用户
```

---

## 优势

相比使用第三方 API（如 AnyToCopy）的优势：

| 特性 | AnyToCopy API | 本方案 |
|------|---------------|--------|
| **依赖服务** | 依赖第三方 | 不依赖第三方视频提取 |
| **视频质量** | 可能被压缩 | 原画质 |
| **水印** | 可能残留 | 完全无水印 |
| **成本** | 需要付费 | 仅语音识别需要 API |
| **稳定性** | 依赖第三方服务 | 直接调用抖音 API |
| **灵活性** | 受限于 API 功能 | 完全可控 |

---

## 注意事项

1. **API 频率限制**：抖音 API 可能有频率限制，建议控制请求频率

2. **语音识别成本**：所配置的转写 API 可能按使用量计费，请注意费用控制

3. **视频大小**：大视频下载和处理可能需要较长时间

4. **网络环境**：需要能访问抖音和所配置的转写 API

5. **合规性**：请确保使用符合抖音用户协议和相关法律法规
