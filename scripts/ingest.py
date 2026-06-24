"""
资料接入层（T1）

支持三种接入方式：
  1. 直接上传文件列表
  2. 本地目录绝对路径递归扫描
  3. zip 压缩包解压后展开

统一返回 List[Tuple[str, str]]：[(文件绝对路径, 文件类型标签), ...]

不支持的格式（如 .dcm）会跳过并打印提示，不会中断流程。
"""
from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# 支持的文件扩展名（小写）
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".webp",  # 图片
    ".pdf",  # PDF
    ".txt", ".md",  # 文本
    ".mp3", ".m4a", ".wav", ".ogg",  # 录音
    ".docx",  # Word
}

# 扩展名 → 类型标签
EXT_TO_TYPE = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".heic": "image",
    ".webp": "image",
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "text",
    ".mp3": "audio",
    ".m4a": "audio",
    ".wav": "audio",
    ".ogg": "audio",
    ".docx": "docx",
}


def _detect_type(path: Path) -> str | None:
    """根据扩展名返回类型标签，不支持的返回 None"""
    ext = path.suffix.lower()
    if ext in EXT_TO_TYPE:
        return EXT_TO_TYPE[ext]
    return None


def _scan_directory(root: Path) -> List[Tuple[str, str]]:
    """递归扫描目录，返回 (绝对路径, 类型标签) 列表"""
    results: List[Tuple[str, str]] = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            file_type = _detect_type(p)
            if file_type is None:
                logger.info("跳过不支持的文件: %s", p)
                continue
            results.append((str(p.resolve()), file_type))
    return results


def _is_safe_zip_member(name: str) -> bool:
    """校验 zip 成员路径，拒绝 Zip Slip 与 Windows 绝对路径。"""
    normalized = name.replace("\\", "/")
    member_path = Path(normalized)
    if member_path.is_absolute():
        return False
    if len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/":
        return False
    return ".." not in member_path.parts


def _extract_zip(zip_path: Path, dest_dir: Path) -> List[Tuple[str, str]]:
    """解压 zip 到 dest_dir，并递归扫描解压后的文件。"""
    target_dir = dest_dir / zip_path.stem
    logger.info("解压 zip: %s -> %s", zip_path, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if not _is_safe_zip_member(member.filename):
                raise ValueError(f"zip 包含不安全路径: {member.filename}")
        zf.extractall(target_dir)
    return _scan_directory(target_dir)


def collect(
    sources: List[str],
    *,
    extract_dir: str | None = None,
) -> List[Tuple[str, str]]:
    """统一入口：收集资料，返回 [(path, type), ...]

    Parameters
    ----------
    sources : List[str]
        来源列表，每个元素可以是：
        - 文件绝对路径（任意支持格式，或 .zip）
        - 目录绝对路径（递归扫描）
    extract_dir : str | None
        zip 解压目标目录，默认系统临时目录。

    Returns
    -------
    List[Tuple[str, str]]
        (文件绝对路径, 类型标签) 列表。类型标签包括：
        image / pdf / text / audio / docx
    """
    if not sources:
        return []

    if extract_dir is None:
        import tempfile
        extract_dir = tempfile.mkdtemp(prefix="patient_record_ingest_")

    results: List[Tuple[str, str]] = []

    for src in sources:
        src_path = Path(src)
        if not src_path.exists():
            logger.warning("来源不存在，跳过: %s", src)
            continue

        if src_path.is_file():
            if src_path.suffix.lower() == ".zip":
                results.extend(_extract_zip(src_path, Path(extract_dir)))
            else:
                file_type = _detect_type(src_path)
                if file_type is None:
                    logger.info("跳过不支持的文件: %s", src_path)
                else:
                    results.append((str(src_path.resolve()), file_type))

        elif src_path.is_dir():
            results.extend(_scan_directory(src_path))

        else:
            logger.warning("无法识别的来源类型，跳过: %s", src)

    return results
