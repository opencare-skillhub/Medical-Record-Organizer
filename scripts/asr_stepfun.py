"""
ASR 引擎 C（T8）：StepAudio 2.5 SSE 流式识别

功能：
- 本地音频文件 base64 → `POST /v1/audio/asr/sse` → SSE 流式解析
- 支持 PCM / OGG / MP3 / WAV，中英文识别
- 增量拼接 `transcript.text.delta`，`transcript.text.done` 结束
- 失败标记 `[ASR失败-需人工确认]`，不中断主流程
- 路由函数 `route_asr()` 按 PRD 6.4 策略选择 C/D
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# 缓存目录：extracted/transcriptions/{hash}.txt
DEFAULT_TRANSCRIPTION_DIR = (
    Path(__file__).resolve().parent.parent / "extracted" / "transcriptions"
)

# SSE 体积保护上限（参考官方文档，1 期暂定 50MB，超过请走引擎 D 或压缩）
SSE_MAX_FILE_BYTES = 50 * 1024 * 1024


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_path(path: Path, base_dir: Path = DEFAULT_TRANSCRIPTION_DIR) -> Path:
    h = _file_hash(path)
    base_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            base_dir.chmod(0o700)
        except OSError:
            pass
    return base_dir / f"{h}.txt"


def _detect_audio_format(path: Path) -> dict:
    """根据扩展名推断音频格式参数（简化版，1 期按扩展名映射）"""
    ext = path.suffix.lower()
    mapping = {
        ".wav": {"type": "pcm", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        ".pcm": {"type": "pcm", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        ".mp3": {"type": "mp3", "codec": "mp3", "rate": 16000, "bits": 16, "channel": 1},
        ".ogg": {"type": "ogg", "codec": "opus", "rate": 16000, "bits": 16, "channel": 1},
        ".m4a": {"type": "m4a", "codec": "aac", "rate": 16000, "bits": 16, "channel": 1},
    }
    return mapping.get(ext, {"type": "mp3", "codec": "mp3", "rate": 16000, "bits": 16, "channel": 1})


# --------------- PRD 6.4 路由策略 ---------------

def route_asr(
    audio_path: str | Path,
    duration_sec: float,
    has_public_url: bool,
    *,
    need_word_level_timestamps: bool = False,
    need_channel_split: bool = False,
) -> Literal["sse", "async_file"]:
    """自动选择 ASR 路径（与 PRD 6.4 保持一致）

    默认全部 → 引擎 C（SSE，StepAudio 2.5）
    仅当以下任一条件满足时 → 引擎 D（异步，接口预留，1 期不实际调用）：
      1. 需要词级时间戳做字幕/逐字对齐（need_word_level_timestamps）
      2. 双声道录音需拆分两人对话（need_channel_split）
      3. 本地超长文件已有公网 URL（has_public_url and duration_sec > 30min）
    """
    if need_word_level_timestamps or need_channel_split:
        return "async_file"      # 引擎 D（接口预留）
    if has_public_url and duration_sec > 30 * 60:
        return "async_file"      # 引擎 D（接口预留）
    return "sse"                 # 引擎 C（默认，1 期主力）


# --------------- 引擎 C：StepAudio 2.5 ASR（SSE） ---------------

def transcribe_sse(
    file_path: str | Path,
    *,
    api_key: str,
    api_url: str = "https://api.stepfun.com/v1/audio/asr/sse",
    enable_timestamp: bool = False,
    enable_itn: bool = True,
    language: str = "zh",
    cache_dir: Path = DEFAULT_TRANSCRIPTION_DIR,
    max_file_bytes: int | None = None,
) -> str:
    """调用 StepAudio 2.5 SSE 接口，返回完整转写文本（带缓存）"""
    if max_file_bytes is None:
        max_file_bytes = SSE_MAX_FILE_BYTES
    p = Path(file_path)

    # 体积保护：超过上限直接失败标记
    if p.stat().st_size > max_file_bytes:
        logger.warning("音频文件过大 (%s bytes)，超过 SSE 上限 %s bytes，请走引擎 D", p.stat().st_size, max_file_bytes)
        return "[ASR失败-文件过大，请走异步引擎]"

    cache = _cache_path(p, cache_dir)
    if cache.exists():
        return cache.read_text(encoding="utf-8")

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests 未安装，请运行: pip install requests") from exc

    audio_b64 = base64.b64encode(p.read_bytes()).decode()
    fmt = _detect_audio_format(p)

    payload = {
        "audio": {
            "data": audio_b64,
            "input": {
                "transcription": {
                    "model": "stepaudio-2.5-asr",
                    "language": language,
                    "enable_itn": enable_itn,
                    "enable_timestamp": enable_timestamp,
                },
                "format": fmt,
            },
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    full_text_parts: list[str] = []
    try:
        logger.info("开始 SSE 转写: %s", p.name)
        with requests.post(
            api_url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=300,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if not data_str:
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # 解析 SSE 事件
                    if event.get("event") == "transcript.text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            full_text_parts.append(delta)
                    elif event.get("event") == "transcript.text.done":
                        final_text = event.get("text", "") or "".join(full_text_parts)
                        break
        text = "".join(full_text_parts)
        if not text:
            logger.warning("SSE 返回空文本: %s", p.name)
            text = "[ASR失败-返回结果为空]"
    except Exception as exc:
        logger.exception("StepAudio 2.5 SSE 转写失败: %s", p.name)
        text = "[ASR失败-需人工确认]"

    cache.write_text(text, encoding="utf-8")
    return text


# --------------- 引擎 D：异步文件识别（接口预留，1 期不实际调用） ---------------

def transcribe_async_stub(
    file_path: str | Path,
    *,
    public_url: str,
    api_key: str,
    api_url: str = "https://api.stepfun.com/v1/audio/asr/file/submit",
    query_url: str = "https://api.stepfun.com/v1/audio/asr/file/query",
    enable_timestamp: bool = False,
    enable_channel_split: bool = False,
    cache_dir: Path = DEFAULT_TRANSCRIPTION_DIR,
) -> str:
    """异步文件识别 stub（1 期接口预留，不实际调用）

    参考流程（未实现）：
    1. POST /file/submit，传 audio.url=public_url
    2. 轮询 /file/query，建议 1-3s 一次
    3. 拿到 result 后缓存并返回
    """
    logger.warning("引擎 D（异步文件识别）为 1 期接口预留，尚未实现。需要 public_url='%s'", public_url)
    p = Path(file_path)
    cache = _cache_path(p, cache_dir)
    cache.write_text("[ASR-异步引擎预留-待V2实现]", encoding="utf-8")
    return "[ASR-异步引擎预留-待V2实现]"


# --------------- 统一调用入口 ---------------

def transcribe(
    file_path: str | Path,
    *,
    api_key: str,
    duration_sec: float = 0.0,
    has_public_url: bool = False,
    need_word_level_timestamps: bool = False,
    need_channel_split: bool = False,
    **kwargs,
) -> str:
    """统一入口：根据路由策略选择引擎 C 或 D"""
    engine = route_asr(
        file_path,
        duration_sec=duration_sec,
        has_public_url=has_public_url,
        need_word_level_timestamps=need_word_level_timestamps,
        need_channel_split=need_channel_split,
    )
    if engine == "sse":
        return transcribe_sse(file_path, api_key=api_key, **kwargs)
    # 引擎 D：需要 public_url，1 期未实现，返回提示
    return transcribe_async_stub(
        file_path,
        public_url=kwargs.get("public_url", ""),
        api_key=api_key,
    )
