"""
T3 验收测试：scripts/route_ocr.py

覆盖：
  ① 图片文件路由到 mineru（首选）
  ② 纯文字 PDF 路由到 local_pdf（PyMuPDF 本地提取）
  ③ 扫描件/复杂 PDF 路由到 mineru
  ④ 路由函数不实际发 HTTP 请求（通过 monkeypatch 拦截 detect_pdf_type）
  ⑤ extract_text 的 fallback 链：mineru 失败时回退到 siliconflow_ocr
"""
from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

import scripts.route_ocr as ro


@pytest.fixture
def img_file(tmp_dir) -> Path:
    p = tmp_dir / "a.jpg"
    p.write_bytes(b"fake-image")
    return p


@pytest.fixture
def pdf_file(tmp_dir) -> Path:
    p = tmp_dir / "b.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


# ① 图片路由到 mineru（首选）
def test_route_image(img_file):
    assert ro.route_ocr(img_file) == "mineru"


# ② 纯文字 PDF 路由到 local_pdf（PyMuPDF 本地提取，零成本）
def test_route_text_pdf_small(pdf_file, monkeypatch):
    monkeypatch.setattr(ro, "detect_pdf_type", lambda _p: {
        "page_count": 3,
        "is_text_based": True,
        "has_images": False,
    })
    assert ro.route_ocr(pdf_file) == "local_pdf"


# ③ 含图片/扫描件 PDF 路由到 mineru
def test_route_scanned_pdf(pdf_file, monkeypatch):
    monkeypatch.setattr(ro, "detect_pdf_type", lambda _p: {
        "page_count": 10,
        "is_text_based": False,
        "has_images": True,
    })
    assert ro.route_ocr(pdf_file) == "mineru"


# ④ 路由函数不实际发请求（detect_pdf_type 被 monkeypatch，不调用 fitz）
def test_route_does_not_open_real_fitz(pdf_file, monkeypatch):
    called = {}

    def fake_detect(_p):
        called["hit"] = True
        return {"page_count": 1, "is_text_based": True, "has_images": False}

    monkeypatch.setattr(ro, "detect_pdf_type", fake_detect)
    ro.route_ocr(pdf_file)
    assert called.get("hit") is True


# ⑤ _file_hash 稳定
def test_file_hash(img_file):
    h1 = ro._file_hash(img_file)
    h2 = ro._file_hash(img_file)
    assert h1 == h2
    assert len(h1) == 64


# ⑥ _cache_path 位置
def test_cache_path(img_file):
    cp = ro._cache_path(img_file)
    assert cp.name == ro._file_hash(img_file) + ".txt"
    assert cp.parent.name == "extracted"


def test_cache_dir_is_private(img_file, tmp_dir):
    cache_dir = tmp_dir / "ocr-cache"
    ro._cache_path(img_file, cache_dir)
    if os.name == "posix":
        assert cache_dir.stat().st_mode & 0o077 == 0


# Fix 3：detect_pdf_type 应基于累计字符数判断，不因空白页误判
def test_detect_pdf_type_blank_pages_are_text_based(monkeypatch):
    """有3页空白页+1页有少量文字+有图片 → 仍应判为文字型"""
    class FakePage:
        def __init__(self, text, has_img):
            self._text = text
            self._has_img = has_img
        def get_text(self):
            return self._text
        def get_images(self):
            return [(1,)] if self._has_img else []

    class FakeDoc:
        pages = [
            FakePage("", True),
            FakePage("", False),
            FakePage("", True),
            FakePage("Section header\nSome content here with more than fifty characters total length", False),
        ]
        def __len__(self):
            return len(self.pages)
        def __iter__(self):
            return iter(self.pages)
        def close(self):
            pass

    monkeypatch.setattr("fitz.open", lambda _p: FakeDoc())
    info = ro.detect_pdf_type(Path("/tmp/fake.pdf"))
    assert info["page_count"] == 4
    # Fix 3 后：累计字符数 > 50，即使有几页空白页+图片，仍应判为文字型
    assert info["is_text_based"] is True


def test_detect_pdf_type_scanned_no_text(monkeypatch):
    """有3页全是图片且无文字 → 扫描件"""
    class FakePage:
        def __init__(self):
            pass
        def get_text(self):
            return ""
        def get_images(self):
            return [(1,)]

    class FakeDoc:
        pages = [FakePage(), FakePage(), FakePage()]
        def __len__(self):
            return len(self.pages)
        def __iter__(self):
            return iter(self.pages)
        def close(self):
            pass

    monkeypatch.setattr("fitz.open", lambda _p: FakeDoc())
    info = ro.detect_pdf_type(Path("/tmp/fake.pdf"))
    # 全文字数 < 50 且有图片 → 扫描件
    assert info["is_text_based"] is False


# Fix 4：ocr_via_siliconflow 应使用正确的 MIME 类型
def test_mime_type_for_png():
    assert ro._MIME_MAP[".png"] == "image/png"


def test_mime_type_for_heic():
    assert ro._MIME_MAP[".heic"] == "image/heic"


# ── MinerU ZIP 文本提取 ───────────────────────────────────────────────

def test_mineru_extract_text_from_zip_prefers_full_md():
    """官方文档：ZIP 内 Markdown 固定命名为 full.md"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# 报告\n血钾 7.2 mmol/L")
        zf.writestr("auto/layout.json", "[]")
    buf.seek(0)

    text = ro._mineru_extract_text_from_zip(buf.getvalue(), "report.pdf")
    assert "血钾" in text


def test_mineru_extract_text_from_zip_falls_back_to_content_list_json():
    """无 full.md 时回退到 content_list.json（[{type,text}] 风格）"""
    import io
    import json
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "full_content_list.json",
            json.dumps([
                {"type": "text", "text": "血钾 7.2"},
                {"type": "image", "text": ""},
                {"type": "text", "text": "EGFR 19del"},
            ], ensure_ascii=False),
        )
    buf.seek(0)

    text = ro._mineru_extract_text_from_zip(buf.getvalue(), "report.pdf")
    assert "血钾 7.2" in text
    assert "EGFR 19del" in text


def test_extract_via_mineru_full_flow(monkeypatch, tmp_dir):
    """完整流程：申请上传链接 → 上传 → 轮询 done → 下载 ZIP → 提取 full.md"""
    import io
    import zipfile

    calls = {"apply": 0, "upload": 0, "poll_count": 0, "download": 0}

    class FakeResp:
        def __init__(self, payload, content=b"", status=200):
            self._payload = payload
            self.content = content
            self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")
        def json(self):
            return self._payload

    # 官方结构：ZIP 内含 full.md
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# 扫描报告\nEGFR 19del")
        zf.writestr("layout.json", "[]")
    zip_bytes = buf.getvalue()

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["apply"] += 1
        assert url.endswith("/api/v4/file-urls/batch")
        assert headers["Authorization"] == "Bearer test-token"
        return FakeResp({
            "code": 0,
            "data": {"batch_id": "batch-1", "file_urls": ["https://upload/fake"]},
        })

    def fake_put(url, data=None, timeout=None):
        calls["upload"] += 1
        assert url == "https://upload/fake"
        return FakeResp({}, status=200)

    def fake_get(url, headers=None, timeout=None):
        if "extract-results/batch" in url:
            calls["poll_count"] += 1
            # 模拟官方状态流转：running → done
            state = "done" if calls["poll_count"] >= 2 else "running"
            return FakeResp({
                "code": 0,
                "data": {
                    "extract_result": [{
                        "file_name": "scan.pdf",
                        "state": state,
                        "full_zip_url": "https://result/scan.zip" if state == "done" else "",
                    }]
                },
            })
        # 下载结果 ZIP
        calls["download"] += 1
        return FakeResp({}, content=zip_bytes, status=200)

    import requests as _requests
    monkeypatch.setattr(_requests, "post", fake_post)
    monkeypatch.setattr(_requests, "put", fake_put)
    monkeypatch.setattr(_requests, "get", fake_get)
    # 跳过真实 sleep，加速测试
    monkeypatch.setattr(ro.time, "sleep", lambda _s: None)

    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    text = ro.extract_via_mineru(
        pdf, api_key="test-token", api_url="https://mineru.net",
        extract_dir=tmp_dir,
    )

    assert text == "# 扫描报告\nEGFR 19del"
    assert calls["apply"] == 1
    assert calls["upload"] == 1
    assert calls["poll_count"] >= 2
    assert calls["download"] == 1


def test_extract_via_mineru_uses_cache(tmp_dir, monkeypatch):
    """第二次调用应命中缓存，不再发起网络请求"""
    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    # 预置缓存
    cache = ro._cache_path(pdf, tmp_dir)
    cache.write_text("已缓存的解析结果", encoding="utf-8")

    def boom(*a, **kw):
        raise AssertionError("不应发起网络请求")

    import requests as _requests
    monkeypatch.setattr(_requests, "post", boom)

    text = ro.extract_via_mineru(
        pdf, api_key="test-token", extract_dir=tmp_dir,
    )
    assert text == "已缓存的解析结果"


# ── 新路由策略测试 ─────────────────────────────────────────────────────

def test_extract_text_falls_back_from_mineru_to_siliconflow(monkeypatch, tmp_dir):
    """MinerU 失败时，应回退到 SiliconFlow OCR"""
    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    calls = {"mineru": 0, "sf": 0}

    def fake_route(_p):
        return "mineru"

    def fake_mineru(*a, **kw):
        calls["mineru"] += 1
        return "[OCR失败-需人工确认]"

    def fake_sf(*a, **kw):
        calls["sf"] += 1
        return "SF OCR text"

    monkeypatch.setattr(ro, "route_ocr", fake_route)
    monkeypatch.setattr(ro, "extract_via_mineru", fake_mineru)
    monkeypatch.setattr(ro, "ocr_via_siliconflow", fake_sf)

    text = ro.extract_text(
        pdf,
        sf_api_key="k",
        sf_api_url="https://api.siliconflow.cn/v1",
        sf_model="deepseek-ai/DeepSeek-OCR",
        mineru_api_key="k",
        mineru_api_url="https://mineru.net",
        extract_dir=tmp_dir,
    )
    assert text == "SF OCR text"
    assert calls["mineru"] == 1
    assert calls["sf"] == 1


def test_extract_text_local_pdf_uses_pymupdf(monkeypatch, tmp_dir):
    """文字型 PDF 路由到 local_pdf，直接走 PyMuPDF，不调用 MinerU/DS-OCR"""
    pdf = tmp_dir / "text.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    calls = {"local": 0, "mineru": 0, "sf": 0}

    def fake_route(_p):
        return "local_pdf"

    def fake_local(_p):
        calls["local"] += 1
        return "local pdf text"

    monkeypatch.setattr(ro, "route_ocr", fake_route)
    monkeypatch.setattr(ro, "_extract_pdf_text", fake_local)
    monkeypatch.setattr(ro, "extract_via_mineru", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call mineru")))
    monkeypatch.setattr(ro, "ocr_via_siliconflow", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call sf")))

    text = ro.extract_text(
        pdf,
        sf_api_key="k",
        sf_api_url="https://api.siliconflow.cn/v1",
        sf_model="deepseek-ai/DeepSeek-OCR",
        mineru_api_key="k",
        mineru_api_url="https://mineru.net",
        extract_dir=tmp_dir,
    )
    assert text == "local pdf text"
    assert calls["local"] == 1

