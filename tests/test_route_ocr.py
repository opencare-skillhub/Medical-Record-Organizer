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


# ③b 文字型 PDF 但有图片 → 也应路由到 mineru（如 38 页基因报告含图表）
def test_route_pdf_text_based_with_images_routes_to_mineru(pdf_file, monkeypatch):
    monkeypatch.setattr(ro, "detect_pdf_type", lambda _p: {
        "page_count": 38,
        "is_text_based": True,
        "has_images": True,
    })
    assert ro.route_ocr(pdf_file) == "mineru"


# ③c 纯文字 PDF 超过5页 → 送给 MinerU 深度解析
def test_route_pdf_large_text_only_routes_to_mineru(pdf_file, monkeypatch):
    monkeypatch.setattr(ro, "detect_pdf_type", lambda _p: {
        "page_count": 10,
        "is_text_based": True,
        "has_images": False,
    })
    assert ro.route_ocr(pdf_file) == "mineru"


# ③d 纯文字小 PDF ≤5页且无图片 → PyMuPDF（不变）
def test_route_pdf_small_text_no_images(pdf_file, monkeypatch):
    monkeypatch.setattr(ro, "detect_pdf_type", lambda _p: {
        "page_count": 5,
        "is_text_based": True,
        "has_images": False,
    })
    assert ro.route_ocr(pdf_file) == "local_pdf"


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


# ── Phase 2: MinerU 官方文档对齐测试 ─────────────────────────────────


def test_mineru_default_base_url_not_v1_doubled():
    """默认 base 不应出现 /v1 或 /api/v4 段，避免拼出 /v1/api/v4/... 错误路径。"""
    base = ro._resolve_mineru_base()
    assert base == "https://mineru.net"
    assert "/v1" not in base
    assert "/api/v4" not in base


def test_mineru_base_strips_misconfigured_suffix():
    """误填带 /v1 或 /api/v4 的完整路径时应被裁回 base。"""
    assert ro._resolve_mineru_base("https://api.mineru.cn/v1") == "https://api.mineru.cn"
    assert ro._resolve_mineru_base("https://mineru.net/api/v4/file-urls/batch") == "https://mineru.net"
    assert ro._resolve_mineru_base("https://mineru.net/api/v4") == "https://mineru.net"


def test_mineru_apply_uses_files_array_payload(monkeypatch, tmp_dir):
    """apply payload 必须用 files 数组 + model_version，而非旧的 file_name。"""
    captured = {}

    class FakeResp:
        def __init__(self, payload, status=200):
            self._p = payload
            self.status_code = status
            self.content = b""
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("HTTP fail")
        def json(self):
            return self._p

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp({"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://up"]}})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(ro.time, "sleep", lambda _s: None)

    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # poll: running -> done
    poll_call = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        poll_call["n"] += 1
        state = "done" if poll_call["n"] >= 2 else "running"
        return FakeResp({"code": 0, "data": {"extract_result": [{"state": state, "full_zip_url": ""}]}})

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.put", lambda url, data=None, timeout=None: FakeResp({}, status=200))

    ro.extract_via_mineru(pdf, api_key="tok", extract_dir=tmp_dir)

    assert captured["payload"].get("files")
    assert captured["payload"]["files"][0]["name"] == "scan.pdf"
    assert "model_version" in captured["payload"]
    assert "file_name" not in captured["payload"]


def test_mineru_poll_uses_path_batch_id(monkeypatch, tmp_dir):
    """轮询 URL 必须用路径参数 {batch_id}，而非查询参数。"""
    poll_urls = []

    class FakeResp:
        def __init__(self, payload, status=200):
            self._p = payload
            self.status_code = status
            self.content = b""
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    monkeypatch.setattr("requests.post", lambda url, headers=None, json=None, timeout=None:
                        FakeResp({"code": 0, "data": {"batch_id": "BATCH123", "file_urls": ["https://up"]}}))
    monkeypatch.setattr("requests.put", lambda url, data=None, timeout=None: FakeResp({}, status=200))

    def fake_get(url, headers=None, timeout=None):
        poll_urls.append(url)
        return FakeResp({"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": ""}]}})

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr(ro.time, "sleep", lambda _s: None)

    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF fake")
    ro.extract_via_mineru(pdf, api_key="tok", extract_dir=tmp_dir)

    # 至少一次轮询，URL 含 /batch/BATCH123（路径参数），不含 ?batch_id=
    assert any("/extract-results/batch/BATCH123" in u for u in poll_urls)
    assert not any("?batch_id=" in u for u in poll_urls)


def test_mineru_token_env_resolution(monkeypatch, tmp_dir):
    """未传 api_key 时应解析 env：MINERU_API_KEY 优先于 MINERU_TOKEN。"""
    monkeypatch.setenv("MINERU_API_KEY", "")
    monkeypatch.setenv("MINERU_TOKEN", "TOKEN_FROM_ENV")
    assert ro._resolve_mineru_key() == "TOKEN_FROM_ENV"

    monkeypatch.setenv("MINERU_API_KEY", "KEY_FROM_ENV")
    assert ro._resolve_mineru_key() == "KEY_FROM_ENV"

    # 显式参数最高优先
    assert ro._resolve_mineru_key("explicit") == "explicit"


def test_mineru_skips_when_no_token(monkeypatch, tmp_dir):
    """无 token 时直接返回失败标记，不发起网络请求。"""
    monkeypatch.setenv("MINERU_API_KEY", "")
    monkeypatch.setenv("MINERU_TOKEN", "")

    def boom(*a, **kw):
        raise AssertionError("无 token 不应发请求")

    monkeypatch.setattr("requests.post", boom)
    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF fake")
    text = ro.extract_via_mineru(pdf, extract_dir=tmp_dir)
    assert text.startswith("[MinerU")


def test_mineru_code_nonzero_raises(monkeypatch, tmp_dir):
    """apply 返回 code!=0（HTTP 200）时应判失败而非当成功。"""
    class FakeResp:
        def __init__(self, payload):
            self._p = payload; self.status_code = 200; self.content = b""
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    monkeypatch.setattr("requests.post", lambda *a, **kw:
                        FakeResp({"code": -10002, "msg": "type mismatch for field files"}))
    monkeypatch.setattr(ro.time, "sleep", lambda _s: None)

    pdf = tmp_dir / "scan.pdf"
    pdf.write_bytes(b"%PDF fake")
    text = ro.extract_via_mineru(pdf, api_key="tok", extract_dir=tmp_dir)
    assert text.startswith("[MinerU")


# ── Phase 3: 本地 OCR 兜底测试 ───────────────────────────────────────


def test_tesseract_uses_chinese_language(monkeypatch, tmp_dir):
    """Tesseract 应使用 chi_sim+eng 而非仅 eng。"""
    captured = {}
    img = tmp_dir / "a.png"
    img.write_bytes(b"fake-png")

    class FakeImg:
        pass

    def fake_itss(img_obj, lang=None):
        captured["lang"] = lang
        return "中文 text"

    # 注入 fake pytesseract 模块（本机未装 pytesseract，避免 ModuleNotFoundError）
    import sys, types
    fake_ts = types.ModuleType("pytesseract")
    fake_ts.image_to_string = fake_itss
    monkeypatch.setitem(sys.modules, "pytesseract", fake_ts)

    class FakePIL:
        Image = type("I", (), {"open": staticmethod(lambda p: FakeImg())})
    monkeypatch.setitem(sys.modules, "PIL", FakePIL)

    text = ro._ocr_with_tesseract(img)
    assert "chi_sim" in (captured.get("lang") or "")
    assert "中文" in text


def test_paddleocr_not_in_default_path():
    """_ocr_image 不应再调用 PaddleOCR（已移除）。"""
    assert not hasattr(ro, "_ocr_with_paddle")
    # _ocr_image 走的应是 tesseract
    import inspect
    src = inspect.getsource(ro._ocr_image)
    assert "tesseract" in src.lower()
    assert "paddle" not in src.lower()


# ── Phase 4: SiliconFlow DeepSeek-OCR 兜底测试 ────────────────────────


def test_siliconflow_endpoint_built_from_base(monkeypatch):
    """endpoint 默认从 base + /chat/completions 构建，单一来源。"""
    monkeypatch.setenv("OCR_BASE_URL", "https://api.siliconflow.cn/v1")
    assert ro._sf_endpoint() == "https://api.siliconflow.cn/v1/chat/completions"
    # 显式 api_url 优先
    assert ro._sf_endpoint("https://custom/ocr") == "https://custom/ocr"


def test_siliconflow_default_model():
    """默认模型为 deepseek-ai/DeepSeek-OCR。"""
    assert ro._resolve_sf_model() == "deepseek-ai/DeepSeek-OCR"


def test_siliconflow_skips_without_key(monkeypatch, tmp_dir):
    """无 key 时直接返回失败标记，不发请求。"""
    monkeypatch.setenv("OCR_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")

    def boom(*a, **kw):
        raise AssertionError("无 key 不应发请求")

    monkeypatch.setattr("requests.post", boom)
    img = tmp_dir / "a.png"
    img.write_bytes(b"fake")
    text = ro.ocr_via_siliconflow(img, extract_dir=tmp_dir)
    assert text.startswith("[OCR失败")


def test_siliconflow_failed_result_not_cached(monkeypatch, tmp_dir):
    """失败标记结果不写入成功缓存，下次可重试。"""
    monkeypatch.setenv("OCR_API_KEY", "k")

    class FakeResp:
        def __init__(self, payload, status=500):
            self._p = payload; self.status_code = status; self.content = b""
        def raise_for_status(self):
            raise RuntimeError("HTTP 500")
        def json(self):
            return self._p

    img = tmp_dir / "a.png"
    img.write_bytes(b"fake")
    cache = ro._cache_path(img, tmp_dir)

    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResp({}, 500))
    text = ro.ocr_via_siliconflow(img, extract_dir=tmp_dir)
    assert text.startswith("[OCR失败")
    # 失败标记不应落盘
    assert not cache.exists() or not cache.read_text(encoding="utf-8").startswith("[OCR失败")


def test_siliconflow_uses_model_in_payload(monkeypatch, tmp_dir):
    """payload 必须用 chat/completions 多模态格式：model + messages[image_url/text]。"""
    captured = {}
    monkeypatch.setenv("OCR_API_KEY", "k")

    class FakeResp:
        def __init__(self, payload):
            self._p = payload; self.status_code = 200; self.content = b""
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp({"choices": [{"message": {"content": "OCR 内容"}}]})

    monkeypatch.setattr("requests.post", fake_post)
    img = tmp_dir / "a.png"
    img.write_bytes(b"fake")
    ro.ocr_via_siliconflow(img, extract_dir=tmp_dir)
    assert captured["payload"]["model"] == "deepseek-ai/DeepSeek-OCR"
    msg = captured["payload"]["messages"][0]["content"]
    assert any(part.get("type") == "image_url" for part in msg)
    assert any(part.get("type") == "text" for part in msg)
    # endpoint 是 /chat/completions
    assert captured["url"].endswith("/chat/completions")

