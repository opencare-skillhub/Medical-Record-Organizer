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

# 原始文件扩展名（pipeline 据此判定是否需要 OCR 预处理）
RAW_OCR_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp', '.tiff', '.pdf'}

# ---------------------------------------------------------------------------
# 配置常量（对应 .env；单点真实，杜绝硬编码 URL/payload 不一致）
#   MinerU 官方文档：docs/mineru_batch_api.md
# ---------------------------------------------------------------------------
_MINERU_DEFAULT_BASE = 'https://mineru.net'
_MINERU_APPLY_PATH = '/api/v4/file-urls/batch'
_MINERU_POLL_PATH_TMPL = '/api/v4/extract-results/batch/{batch_id}'
_MINERU_DEFAULT_MODEL_VERSION = 'vlm'

# SiliconFlow DeepSeek-OCR（最后云端托底）
# SiliconFlow DeepSeek-OCR（最后云端托底）：实测确认走 /chat/completions 多模态消息
_SF_DEFAULT_BASE = 'https://api.siliconflow.cn/v1'
_SF_OCR_PATH = '/chat/completions'
_SF_DEFAULT_MODEL = 'deepseek-ai/DeepSeek-OCR'
_SF_OCR_INSTRUCTION = '请识别图片中所有文字，按原文顺序输出，不要加工、不要解释。'

# 失败标记前缀：以 `[` 开头视为失败，触发回退且不写入成功缓存
_FAIL_PREFIX = '['


def _resolve_mineru_key(explicit: str = '') -> str:
    """解析 MinerU token：显式参数 > MINERU_API_KEY > MINERU_TOKEN。"""
    if explicit:
        return explicit
    return os.getenv('MINERU_API_KEY', '') or os.getenv('MINERU_TOKEN', '')


def _resolve_mineru_base(explicit: str = '') -> str:
    """解析 MinerU base URL，去掉尾部斜杠与多余的 /v1/api/v4 段。"""
    url = (explicit or os.getenv('MINERU_API_URL', '') or _MINERU_DEFAULT_BASE).rstrip('/')
    # 防御：裁回 base，避免拼出 /v1/api/v4/... 这类错误路径
    for seg in ('/api/v4/file-urls/batch', '/api/v4/extract-results', '/api/v4', '/v1'):
        if url.endswith(seg):
            url = url[: -len(seg)]
            break
    return url.rstrip('/')


def _resolve_mineru_model_version(explicit: str = '') -> str:
    return (explicit or os.getenv('MINERU_MODEL_VERSION', '') or _MINERU_DEFAULT_MODEL_VERSION).strip()


def _resolve_sf_key(explicit: str = '') -> str:
    if explicit:
        return explicit
    return os.getenv('OCR_API_KEY', '') or os.getenv('SILICONFLOW_API_KEY', '')


def _resolve_sf_base(explicit: str = '') -> str:
    return (explicit or os.getenv('OCR_BASE_URL', '') or os.getenv('SILICONFLOW_BASE_URL', '') or _SF_DEFAULT_BASE).rstrip('/')


def _resolve_sf_model(explicit: str = '') -> str:
    return (explicit or os.getenv('OCR_MODEL', '') or _SF_DEFAULT_MODEL).strip()


def _sf_endpoint(api_url: str = '') -> str:
    """构建 SF OCR 完整 endpoint：显式 api_url 优先，否则 base + /images/ocr。"""
    if api_url:
        return api_url
    return _resolve_sf_base() + _SF_OCR_PATH


def _is_fail_marker(text: str) -> bool:
    """判定 OCR 结果是否为失败标记（含空内容）。"""
    return (not text) or text.startswith(_FAIL_PREFIX)


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
# 本地 OCR 兜底（仅当云端 MinerU + SiliconFlow 全部失败后触发；可选离线）
# ---------------------------------------------------------------------------
# 说明：PaddleOCR 已移除（未进 requirements、与已装版本不兼容、价值低于云端 OCR）。
#       本地仅保留 Tesseract 作为离线兜底，中文病历需 chi_sim+eng。

def _ocr_with_tesseract(image_path: Path, *, lang: str = 'chi_sim+eng') -> str:
    """使用 Tesseract 识别图片（中文+英文）。缺失时静默降级为失败标记。"""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip() or '[OCR未识别到文字]'
    except Exception as exc:
        logger.warning("Tesseract OCR 失败 %s: %s", image_path, exc)
        return '[OCR失败-需人工确认]'


def _ocr_image(image_path: Path) -> str:
    """对图片执行本地 OCR（Tesseract 离线兜底）。"""
    return _ocr_with_tesseract(image_path)


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
# SiliconFlow DeepSeek OCR（最后云端托底）
# ---------------------------------------------------------------------------

def ocr_via_siliconflow(
    file_path: Path,
    *,
    api_key: str = '',
    api_url: str = '',
    model: str = '',
    extract_dir: Optional[Path] = None,
) -> str:
    """调用 SiliconFlow DeepSeek OCR 识别图片或 PDF（最后云端托底）。

    配置解析（显式参数 > env）：
      api_key → OCR_API_KEY / SILICONFLOW_API_KEY
      api_url → 显式 endpoint 优先；否则 OCR_BASE_URL/SILICONFLOW_BASE_URL + /images/ocr
      model   → OCR_MODEL（默认 deepseek-ai/DeepSeek-OCR）

    失败标记结果不写入成功缓存，避免瞬时故障缓存中毒。
    """
    key = _resolve_sf_key(api_key)
    endpoint = _sf_endpoint(api_url)
    use_model = _resolve_sf_model(model)

    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding='utf-8')
            if cached and not _is_fail_marker(cached):
                return cached
        except Exception:
            pass

    if not key:
        logger.warning("SiliconFlow OCR 跳过（未配置 OCR_API_KEY）：%s", file_path.name)
        return '[OCR失败-需人工确认]'

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests 未安装") from exc

    import base64
    b64 = base64.b64encode(file_path.read_bytes()).decode()
    suffix = file_path.suffix.lower()
    mime = _MIME_MAP.get(suffix, 'application/octet-stream')
    image_url = f"data:{mime};base64,{b64}"

    # DeepSeek-OCR 走 /chat/completions 多模态（实测确认）：
    # OpenAI 风格 messages，content 含 image_url + text 指令
    payload = {
        "model": use_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": _SF_OCR_INSTRUCTION},
                ],
            }
        ],
    }

    try:
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        # chat/completions 响应：choices[0].message.content
        choices = data.get("choices") or []
        text = ''
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or ''
        # 兼容旧响应结构
        if not text:
            text = data.get("text") or data.get("content") or data.get("result", "")
        if isinstance(text, list):
            text = "\n".join(text)
        text = (text or '').strip()
        if not text:
            text = '[OCR未识别到文字]'
    except Exception as exc:
        logger.warning("SiliconFlow OCR 失败 %s: %s", file_path.name, exc)
        text = '[OCR失败-需人工确认]'

    # 仅缓存成功结果，失败标记不落盘以便下次重试
    if not _is_fail_marker(text):
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
    api_key: str = '',
    api_url: str = '',
    model_version: str = '',
    extract_dir: Optional[Path] = None,
) -> str:
    """通过 MinerU API 提取文本（图片或 PDF），严格对齐 docs/mineru_batch_api.md。

    流程：申请上传链接(files 数组) → PUT 上传(无 Content-Type) → 路径参数轮询 → 下载 ZIP。
    配置解析（显式参数 > env）：api_key、api_url(base)、model_version。
    失败不缓存，便于下次重试。
    """
    key = _resolve_mineru_key(api_key)
    base = _resolve_mineru_base(api_url)
    mv = _resolve_mineru_model_version(model_version)

    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding='utf-8')
            if cached and not _is_fail_marker(cached):
                return cached
        except Exception:
            pass

    if not key:
        logger.warning("MinerU 跳过（未配置 MINERU_API_KEY/MINERU_TOKEN）：%s", file_path.name)
        return '[MinerU失败-需人工确认]'

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests 未安装") from exc

    apply_url = f"{base}{_MINERU_APPLY_PATH}"
    # HTML 文件需明确指定 MinerU-HTML
    if file_path.suffix.lower() == '.html':
        mv = 'MinerU-HTML'
    # 稳定的 data_id，便于追踪
    data_id = _file_hash(file_path)[:32]

    # MinerU 官方流程：申请上传链接 → 上传 → 轮询 → 下载 ZIP
    try:
        # 1. 申请上传链接（payload: files 数组 + model_version）
        apply_resp = requests.post(
            apply_url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "files": [{"name": file_path.name, "data_id": data_id}],
                "model_version": mv,
                "enable_formula": True,
                "enable_table": True,
                "language": "ch",
            },
            timeout=30,
        )
        apply_resp.raise_for_status()
        apply_data = apply_resp.json()
        # 官方要求校验 code == 0（HTTP 200 也可能 code != 0）
        if apply_data.get("code") != 0:
            raise RuntimeError(f"MinerU apply 失败：{apply_data.get('msg', '未知错误')}")
        batch_id = apply_data.get("data", {}).get("batch_id")
        upload_urls = apply_data.get("data", {}).get("file_urls", [])
        upload_url = upload_urls[0] if upload_urls else None
        if not upload_url:
            raise RuntimeError("MinerU 未返回上传链接")

        # 2. 上传文件（官方要求不设置 Content-Type）
        with open(file_path, 'rb') as f:
            upload_resp = requests.put(upload_url, data=f, timeout=120)
            upload_resp.raise_for_status()

        # 3. 轮询结果（路径参数：/api/v4/extract-results/batch/{batch_id}）
        for _ in range(30):
            poll_url = f"{base}{_MINERU_POLL_PATH_TMPL.format(batch_id=batch_id)}"
            poll_resp = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            if poll_data.get("code") != 0:
                logger.warning("MinerU 轮询错误 %s: %s", file_path.name, poll_data.get("msg"))
                break
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
                    if not _is_fail_marker(text):
                        cache_path.write_text(text, encoding='utf-8')
                    return text
                break
            elif state == "failed":
                err_msg = results[0].get("err_msg", "")
                logger.warning("MinerU 解析失败 %s: %s", file_path.name, err_msg)
                return f'[MinerU提取失败-需人工确认]'
            # waiting-file / pending / running / converting → 继续轮询
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
    1. 文字型 PDF（无图片且≤5页）→ local_pdf（PyMuPDF）
    2. PDF 含图片 或 超过5页 → mineru（深度解析）
    3. 图片 / 扫描件 PDF → mineru（首选）→ siliconflow_ocr（托底）
    """
    suffix = file_path.suffix.lower()

    if suffix == '.pdf':
        info = detect_pdf_type(file_path)
        # PDF 含图片或超过5页 → MinerU（即使有文字层，如基因报告38页+图表）
        if info.get('has_images') or info.get('page_count', 0) > 5:
            return 'mineru'
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
    sf_api_url: str = '',
    sf_model: str = '',
    mineru_api_key: str = '',
    mineru_api_url: str = '',
    extract_dir: Optional[Path] = None,
) -> str:
    """提取文件文本（带缓存和 fallback）。

    路由链：
      文本型 PDF → PyMuPDF 本地
      图片/扫描PDF → MinerU → SiliconFlow DeepSeek-OCR → Tesseract(离线)
    各引擎内部自行解析 env（显式参数优先）。失败标记不写入成功缓存。
    """
    cache_path = _cache_path(file_path, extract_dir)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding='utf-8')
            if cached and not _is_fail_marker(cached):
                logger.debug("命中缓存: %s", cache_path)
                return cached
        except Exception:
            pass

    engine = route_ocr(file_path)
    logger.info("文件 %s 路由到引擎: %s", file_path.name, engine)

    if engine == 'local_pdf':
        text = _extract_pdf_text(file_path)
    elif engine == 'mineru':
        # MinerU 首选（内部解析 env：MINERU_API_KEY/MINERU_TOKEN/MINERU_API_URL/MINERU_MODEL_VERSION）
        text = extract_via_mineru(
            file_path,
            api_key=mineru_api_key,
            api_url=mineru_api_url,
            extract_dir=extract_dir,
        )
        # MinerU 输出质量检测：对 PDF，若吐出了不含任何医疗关键词的乱码，回退 PyMuPDF
        if file_path.suffix.lower() == '.pdf' and not _is_fail_marker(text):
            pymupdf_text = _extract_pdf_text(file_path)
            # 如果 PyMuPDF 能提取到足够文字且 MinerU 反而更短或是乱码 → 保留 PyMuPDF 结果
            if (not _is_fail_marker(pymupdf_text)
                    and len(pymupdf_text) > len(text)
                    and len(pymupdf_text) > 200):
                logger.info("MinerU 输出质量异常(%d字)，PyMuPDF 提取更优(%d字)，取 PyMuPDF: %s",
                            len(text), len(pymupdf_text), file_path.name)
                text = pymupdf_text
        # MinerU 失败 → SiliconFlow DeepSeek OCR 托底
        if _is_fail_marker(text):
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

    # 最终兜底：本地 OCR（Tesseract 离线）
    if _is_fail_marker(text):
        logger.info("云端 OCR 失败，回退到本地 OCR: %s", file_path.name)
        if file_path.suffix.lower() == '.pdf':
            text = _extract_pdf_text(file_path)
        else:
            text = _ocr_image(file_path)

    # 仅缓存成功结果，失败标记不落盘以便下次重试
    if not _is_fail_marker(text):
        try:
            cache_path.write_text(text, encoding='utf-8')
        except Exception as exc:
            logger.warning("缓存写入失败 %s: %s", cache_path, exc)

    return text
