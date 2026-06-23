"""
T8 验收测试：scripts/asr_stepfun.py

覆盖：
  ① 短/中录音默认路由到 SSE
  ② 需要词级时间戳时路由到 async_file
  ③ 双声道分离时路由到 async_file
  ④ 本地超长文件（>30min）且无公网 URL 时仍走 SSE（不满足 D 条件）
  ⑤ 超过 SSE 体积上限时返回失败标记
  ⑥ 引擎 D 路由条件满足时返回 stub 结果
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.asr_stepfun import (
    route_asr,
    transcribe_sse,
    transcribe_async_stub,
    transcribe,
    _file_hash,
    _cache_path,
    SSE_MAX_FILE_BYTES,
)


@pytest.fixture
def audio_file(tmp_dir) -> Path:
    p = tmp_dir / "voice.mp3"
    p.write_bytes(b"x" * 1024)
    return p


# ① 短/中录音默认路由到 SSE
def test_route_default_sse(audio_file):
    assert route_asr(audio_file, duration_sec=300, has_public_url=False) == "sse"


# ② 需要词级时间戳时路由到 async_file
def test_route_word_level_timestamps(audio_file):
    assert route_asr(audio_file, duration_sec=300, has_public_url=False, need_word_level_timestamps=True) == "async_file"


# ③ 双声道分离时路由到 async_file
def test_route_channel_split(audio_file):
    assert route_asr(audio_file, duration_sec=300, has_public_url=False, need_channel_split=True) == "async_file"


# ④ 本地超长文件（>30min）且无公网 URL 时仍走 SSE（不满足 D 条件）
def test_route_long_no_url_still_sse(audio_file):
    assert route_asr(audio_file, duration_sec=35 * 60, has_public_url=False) == "sse"


# ⑤ 超过 SSE 体积上限时返回失败标记
def test_transcribe_sse_too_large(audio_file, monkeypatch):
    monkeypatch.setattr("scripts.asr_stepfun.SSE_MAX_FILE_BYTES", 100)
    result = transcribe_sse(audio_file, api_key="fake-key")
    assert "失败" in result or "过大" in result


# ⑥ 引擎 D 路由条件满足时返回 stub 结果
def test_transcribe_async_stub(audio_file, caplog):
    caplog.set_level("WARNING")
    result = transcribe_async_stub(audio_file, public_url="https://example.com/audio.mp3", api_key="fake")
    assert "预留" in result or "待V2" in result
    assert "接口预留" in caplog.text


# ⑦ transcribe 统一入口路由到 SSE（默认情况）
def test_transcribe_default_sse(audio_file, monkeypatch):
    called = {}

    def fake_sse(fp, **kwargs):
        called["sse"] = True
        return "ok"

    monkeypatch.setattr("scripts.asr_stepfun.transcribe_sse", fake_sse)
    result = transcribe(audio_file, api_key="fake", duration_sec=60, has_public_url=False)
    assert called.get("sse") is True
    assert result == "ok"


# ⑧ _file_hash 稳定
def test_file_hash(audio_file):
    h1 = _file_hash(audio_file)
    h2 = _file_hash(audio_file)
    assert h1 == h2
    assert len(h1) == 64


# ⑨ _cache_path 位置
def test_cache_path(audio_file):
    cp = _cache_path(audio_file)
    assert cp.name == _file_hash(audio_file) + ".txt"
    assert cp.parent.name == "transcriptions"


def test_cache_dir_is_private(audio_file, tmp_dir):
    cache_dir = tmp_dir / "asr-cache"
    _cache_path(audio_file, cache_dir)
    if os.name == "posix":
        assert cache_dir.stat().st_mode & 0o077 == 0
