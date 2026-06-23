"""
manifest 管理（T2）

职责：
- 初始化新患者 manifest（含基本信息）
- 读取已有 manifest，进入增量模式
- 计算文件 SHA256，跳过已处理文件
- 回写更新字段
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from scripts.security import ensure_private_dir, write_private_text


def _default_patient_dir(patient_id: str) -> Path:
    return Path.home() / "patients" / patient_id


def sha256_of(path: Path) -> str:
    """计算文件 SHA256"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_manifest(
    patient_id: str,
    *,
    name: str = "",
    age: int | None = None,
    gender: str = "",
    primary_diagnosis: str = "",
    patient_dir: Path | None = None,
) -> Dict[str, Any]:
    """创建新 manifest 结构"""
    if patient_dir is None:
        patient_dir = _default_patient_dir(patient_id)
    ensure_private_dir(patient_dir)

    manifest: Dict[str, Any] = {
        "patient_id": patient_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "demographics": {
            "name": name,
            "age": age,
            "gender": gender,
            "primary_diagnosis": primary_diagnosis,
        },
        "files": [],
        "categories_summary": {},
        "report_context": None,  # 缓存 compute_report_context 的结果，增量更新时复用
    }

    path = patient_dir / "manifest.json"
    write_private_text(path, json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_manifest(patient_id: str, patient_dir: Path | None = None) -> Optional[Dict[str, Any]]:
    """读取已有 manifest；不存在返回 None"""
    if patient_dir is None:
        patient_dir = _default_patient_dir(patient_id)
    path = patient_dir / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(manifest: Dict[str, Any], patient_dir: Path | None = None) -> Path:
    """回写 manifest（写入前刷新 categories_summary 与 updated_at）"""
    if patient_dir is None:
        patient_id = manifest.get("patient_id", "unknown")
        patient_dir = _default_patient_dir(patient_id)
    path = patient_dir / "manifest.json"
    manifest["updated_at"] = now_iso()
    # 每次写回前重新统计分类汇总，保证报告缺口检测准确
    from scripts.classify import update_categories_summary
    update_categories_summary(manifest)
    write_private_text(path, json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def diff_files(
    manifest: Dict[str, Any],
    collected: List[tuple[str, str]],
) -> List[tuple[str, str]]:
    """对比已收集文件列表与 manifest 中已有哈希，返回需要处理的新文件列表"""
    seen_hashes = {entry["hash"] for entry in manifest.get("files", [])}
    new_files: List[tuple[str, str]] = []
    for file_path, file_type in collected:
        h = sha256_of(Path(file_path))
        if h in seen_hashes:
            continue
        new_files.append((file_path, file_type))
    return new_files


def append_files(
    manifest: Dict[str, Any],
    new_files: List[tuple[str, str]],
) -> Dict[str, Any]:
    """将新文件条目追加进 manifest（不处理内容，只登记索引）"""
    for file_path, file_type in new_files:
        h = sha256_of(Path(file_path))
        entry = {
            "hash": h,
            "original_name": Path(file_path).name,
            "source_path": file_path,
            "extracted_path": None,
            "category": None,
            "date_detected": None,
            "title": None,
            "confidence": None,
            "needs_review": False,
        }
        manifest.setdefault("files", []).append(entry)
    # 新增文件后立即刷新分类汇总（此时 category 为 None，summary 会清零新条目）
    from scripts.classify import update_categories_summary
    update_categories_summary(manifest)
    return manifest


def init_or_load(patient_id: str, **kwargs) -> tuple[Dict[str, Any], bool]:
    """便捷函数：不存在则创建，存在则加载；返回 (manifest, is_new)"""
    patient_dir = kwargs.get("patient_dir")
    manifest = load_manifest(patient_id, patient_dir=patient_dir)
    if manifest is None:
        manifest = create_manifest(patient_id, **kwargs)
        return manifest, True
    return manifest, False
