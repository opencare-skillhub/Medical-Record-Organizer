"""
OCR 路由与提取（scripts/route_ocr.py）

职责：
- 根据文件类型路由到最佳提取引擎
- 文字型 PDF → PyMuPDF 本地提取
- 图片 / 扫描件 PDF → MinerU（首选）→ SiliconFlow DeepSeek OCR（托底）
- 缓存结果到 extracted/ 目录

对应 tests/test_route_ocr.py 契约。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# MIME 类型映射
_MIME_MAP = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
    '.heic': 'image/heic',
    '.pdf': 'application/pdf',
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _file_hash(file_path: Path) -> str:
    """计算文件 SHA256。"""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _cache_path(file_path: Path, cache_dir: Optional[Path] = None) -> Path:
    """缓存路径：extracted/{sha256}.txt"""
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parent.parent / 'extracted'
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_dir.chmod(0o700)
    except OSError:
        pass
    return cache_dir / f"{_file_hash(file_path)}.txt"


# ---------------------------------------------------------------------------
# PDF 类型检测
# ---------------------------------------------------------------------------

def detect_pdf_type(pdf_path: Path) -> dict:
    """检测 PDF 类型，返回 {page_count, is_text_based, has_images}。"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = list(doc)
        page_count = len(pages)

        total_text_len = 0
        has_images = False

        for page in pages:
            text = page.get_text()
            total_text_len += len(text.strip())
            if page.get_images():
                has_images = True

        doc.close()

        # 累计字符数 > 50 → 文字型（即使有少量图片/空白页也视为文字型 PDF）
        is_text_based = total_text_len > 50

        return {
            'page_count': page_count,
            'is_text_based': is_text_based,
            'has_images': has_images,
        }
    except Exception as exc:
        logger.warning("PDF 类型检测失败 %s: %s", pdf_path, exc)
        return {
            'page_count': 0,
            'is_text_based': False,
            'has_images': True,
        }


# ---------------------------------------------------------------------------
# OCR 引擎
# ---------------------------------------------------------------------------

def _ocr_with_paddle(image_path: Path) -> str:
    """使用 PaddleOCR 识别图片。"""
    try:
        from paddleocr import PaddleOCR
        import os
        os.environ['FLAGS_use_mkldnn'] = 'False'
        ocr = PaddleOCR(use_textline_orientation=True, lang='ch')
        result = ocr.ocr(str(image_path), cls=True)
        if result and result[0]:
            lines = [line[1][0] for line in result[0]]
            return '\n'.join(lines)
        return '[OCR未识别到文字]'
    except Exception as exc:
        logger.warning("PaddleOCR 失败 %s: %s", image_path, exc)
        return '[OCR失败-需人工确认]'


def _ocr_with_tesseract(image_path: Path) -> str:
    """使用 Tesseract 识别图片（仅英文）。"""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang='eng')
        return text.strip() or '[OCR未识别到文字]'
    except Exception as exc:
        logger.warning("Tesseract OCR 失败 %s: %s", image_path, exc)
        return '[OCR失败-需人工确认]'


def _ocr_image(image_path: Path) -> str:
    """对图片执行 OCR，优先 PaddleOCR，回退 Tesseract。"""
    # 尝试 PaddleOCR
    text = _ocr_with_paddle(image_path)
    if text and not text.startswith('[OCR'):
        return text

    # 回退 Tesseract
    text = _ocr_with_tesseract(image_path)
    return text


def _extract_pdf_text(pdf_path: Path) -> str:
    """用 PyMuPDF 提取 PDF 文本。"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        parts = [page.get_text() for page in doc]
        doc.close()
        text = '\n'.join(parts).strip()
        return text if text else '[PDF无文字层-需OCR]'
    except Exception as exc:
        logger.warning("PDF 提取失败 %s: %s", pdf_path, exc)
        return '[PDF提取失败-需人工确认]'


# ---------------------------------------------------------------------------
# SiliconFlow DeepSeek OCR（托底）
# ---------------------------------------------------------------------------

def ocr_via_siliconflow(
    file_path: Path,
    *,
    api_key: str,
    api_url: str = 'https://api.siliconflow.cn/v1/images/ocr',
    model: str = 'deepseek-ai/DeepSeek-OCR',
    extract_dir: Optional[Path] = None,
) -> str:
    """调用 SiliconFlow DeepSeek OCR 识别图片或 PDF。"""
    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding='utf-8')
            if cached:
                return cached
        except Exception:
            pass

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests 未安装") from exc

    import base64
    b64 = base64.b64encode(file_path.read_bytes()).decode()
    suffix = file_path.suffix.lower()
    mime = _MIME_MAP.get(suffix, 'application/octet-stream')
    image_url = f"data:{mime};base64,{b64}"

    payload = {
        "model": model,
        "image_url": image_url,
    }

    try:
        resp = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        # 兼容不同响应结构
        text = data.get("text") or data.get("content") or data.get("result", "")
        if isinstance(text, list):
            text = "\n".join(text)
        text = text.strip() or '[OCR未识别到文字]'
    except Exception as exc:
        logger.warning("SiliconFlow OCR 失败 %s: %s", file_path.name, exc)
        text = '[OCR失败-需人工确认]'

    try:
        cache_path.write_text(text, encoding='utf-8')
    except Exception as exc:
        logger.warning("缓存写入失败 %s: %s", cache_path, exc)

    return text


# ---------------------------------------------------------------------------
# MinerU（首选引擎）
# ---------------------------------------------------------------------------

def _mineru_extract_text_from_zip(zip_bytes: bytes, filename: str) -> str:
    """从 MinerU 返回的 ZIP 中提取文本。"""
    try:
        buf = __import__('io').BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, 'r') as zf:
            names = zf.namelist()
            # 优先 full.md
            if 'full.md' in names:
                return zf.read('full.md').decode('utf-8', errors='ignore')
            # 回退 content_list.json
            for name in names:
                if 'content_list' in name or 'full_content' in name:
                    data = json.loads(zf.read(name).decode('utf-8'))
                    if isinstance(data, list):
                        texts = [item.get('text', '') for item in data if isinstance(item, dict)]
                        return '\n'.join(texts)
            # 最后回退：所有 .md 文件
            md_files = [n for n in names if n.endswith('.md')]
            if md_files:
                return zf.read(md_files[0]).decode('utf-8', errors='ignore')
    except Exception as exc:
        logger.warning("ZIP 文本提取失败: %s", exc)
    return '[ZIP解析失败]'


def extract_via_mineru(
    file_path: Path,
    *,
    api_key: str,
    api_url: str = 'https://api.mineru.cn/v1',
    extract_dir: Optional[Path] = None,
) -> str:
    """通过 MinerU API 提取文本（图片或 PDF）。"""
    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding='utf-8')
        except Exception:
            pass

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests 未安装") from exc

    # MinerU 官方流程：申请上传链接 → 上传 → 轮询 → 下载 ZIP
    try:
        # 1. 申请上传链接
        apply_resp = requests.post(
            f"{api_url}/api/v4/file-urls/batch",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"file_name": file_path.name, "enable_formula": True},
            timeout=30,
        )
        apply_resp.raise_for_status()
        apply_data = apply_resp.json()
        batch_id = apply_data.get("data", {}).get("batch_id")
        upload_url = apply_data.get("data", {}).get("file_urls", [None])[0]
        if not upload_url:
            raise RuntimeError("MinerU 未返回上传链接")

        # 2. 上传文件
        with open(file_path, 'rb') as f:
            upload_resp = requests.put(upload_url, data=f, timeout=120)
            upload_resp.raise_for_status()

        # 3. 轮询结果
        import time
        for _ in range(30):
            poll_url = f"{api_url}/api/v4/extract-results/batch?batch_id={batch_id}"
            poll_resp = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            results = poll_data.get("data", {}).get("extract_result", [])
            if not results:
                time.sleep(2)
                continue
            state = results[0].get("state", "")
            if state == "done":
                zip_url = results[0].get("full_zip_url", "")
                if zip_url:
                    zip_resp = requests.get(zip_url, timeout=120)
                    zip_resp.raise_for_status()
                    text = _mineru_extract_text_from_zip(zip_resp.content, file_path.name)
                    cache_path.write_text(text, encoding='utf-8')
                    return text
                break
            elif state in ("failed", "error"):
                break
            time.sleep(2)

        logger.warning("MinerU 提取未完成 %s", file_path.name)
        return '[MinerU提取失败-需人工确认]'

    except Exception as exc:
        logger.warning("MinerU 提取失败 %s: %s", file_path.name, exc)
        return '[MinerU失败-需人工确认]'


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def route_ocr(file_path: Path) -> str:
    """根据文件类型路由到最佳提取引擎。

    策略：
    1. 文字型 PDF → local_pdf（PyMuPDF）
    2. 图片 / 扫描件 PDF → mineru（首选）→ siliconflow_ocr（托底）
    """
    suffix = file_path.suffix.lower()

    if suffix == '.pdf':
        info = detect_pdf_type(file_path)
        if info['is_text_based']:
            return 'local_pdf'
        else:
            return 'mineru'
    else:
        # 图片 → mineru 首选
        return 'mineru'


# ---------------------------------------------------------------------------
# 主提取函数
# ---------------------------------------------------------------------------

def extract_text(
    file_path: Path,
    *,
    sf_api_key: str = '',
    sf_api_url: str = 'https://api.siliconflow.cn/v1/images/ocr',
    sf_model: str = 'deepseek-ai/DeepSeek-OCR',
    mineru_api_key: str = '',
    mineru_api_url: str = 'https://api.mineru.cn/v1',
    extract_dir: Optional[Path] = None,
) -> str:
    """提取文件文本（带缓存和 fallback）。"""
    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding='utf-8')
            if cached:
                logger.debug("命中缓存: %s", cache_path)
                return cached
        except Exception:
            pass

    engine = route_ocr(file_path)
    logger.info("文件 %s 路由到引擎: %s", file_path.name, engine)

    if engine == 'local_pdf':
        text = _extract_pdf_text(file_path)
    elif engine == 'mineru':
        # MinerU 首选
        text = extract_via_mineru(
            file_path,
            api_key=mineru_api_key,
            api_url=mineru_api_url,
            extract_dir=extract_dir,
        )
        # MinerU 失败 → SiliconFlow DeepSeek OCR 托底
        if not text or text.startswith('['):
            logger.info("MinerU 失败，回退到 SiliconFlow OCR: %s", file_path.name)
            text = ocr_via_siliconflow(
                file_path,
                api_key=sf_api_key,
                api_url=sf_api_url,
                model=sf_model,
                extract_dir=extract_dir,
            )
    else:
        text = f'[未知引擎: {engine}]'

    # 最终兜底：本地 OCR
    if not text or text.startswith('['):
        logger.info("云端 OCR 失败，回退到本地 OCR: %s", file_path.name)
        if file_path.suffix.lower() == '.pdf':
            text = _extract_pdf_text(file_path)
        else:
            text = _ocr_image(file_path)

    # 缓存结果
    try:
        cache_path.write_text(text, encoding='utf-8')
    except Exception as exc:
        logger.warning("缓存写入失败 %s: %s", cache_path, exc)

    return text
