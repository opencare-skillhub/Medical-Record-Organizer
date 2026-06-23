"""
记忆模块：记录每次处理的历史，支持溯源、版本回顾、反复修改。

存储结构（~/.patient-record-organizer/memory/ 或患者目录下）：
  memory/
    ├── index.json          → 全局索引（patient_id → 最新版本）
    ├── P_QINXQ/
    │   ├── versions.json   → 该患者所有版本列表
    │   ├── v001/
    │   │   ├── manifest.json
    │   │   ├── report.md
    │   │   ├── report.html
    │   │   └── audit.json  → 本次处理的详细审计
    │   ├── v002/
    │   │   └── ...
    │   └── current -> v002  → 软链接，指向当前版本
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 记忆根目录
MEMORY_ROOT = Path.home() / ".patient-record-organizer" / "memory"


def _ensure_memory_root():
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)


def _sha256_of(text: str) -> str:
    """对文本内容做 SHA256，用于快照去重"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_patient_memory_dir(patient_id: str) -> Path:
    """获取患者记忆目录"""
    _ensure_memory_root()
    d = MEMORY_ROOT / patient_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_versions_index(patient_id: str) -> List[Dict[str, Any]]:
    """读取患者版本索引"""
    idx_path = get_patient_memory_dir(patient_id) / "versions.json"
    if not idx_path.exists():
        return []
    return json.loads(idx_path.read_text(encoding="utf-8"))


def _write_versions_index(patient_id: str, versions: List[Dict[str, Any]]):
    idx_path = get_patient_memory_dir(patient_id) / "versions.json"
    idx_path.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8")


def record_run(
    patient_id: str,
    *,
    pipeline_result: Dict[str, Any],
    input_dir: str,
    files_processed: List[Dict[str, Any]],
    notes: str = "",
    operator: str = "",
) -> Dict[str, Any]:
    """记录一次 pipeline 运行，生成新版本。

    Parameters
    ----------
    patient_id : 患者ID
    pipeline_result : PipelineResult 的 dict 表示
    input_dir : 输入目录
    files_processed : 本次处理的文件列表
    notes : 操作备注（如"补充了6月化疗记录"）
    operator : 操作人（留空则为自动）

    Returns
    -------
    version_info : 新版本信息（含 version_id, created_at, snapshot_path 等）
    """
    _ensure_memory_root()
    p_dir = get_patient_memory_dir(patient_id)
    versions = get_versions_index(patient_id)

    # 生成版本号
    next_ver = len(versions) + 1
    version_id = f"v{next_ver:03d}"

    # 构建快照目录
    snap_dir = p_dir / version_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    # 计算本次处理的文件指纹（用于快速判断是否重复）
    files_fingerprint = hashlib.sha256(
        json.dumps(files_processed, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]

    # 检查是否与上一版本内容相同（避免无意义重复记录）
    if versions:
        last = versions[-1]
        if last.get("files_fingerprint") == files_fingerprint and not notes:
            logger.info("内容与上一版本相同，跳过记录")
            return last

    # 复制关键文件到快照
    output_dir = pipeline_result.get("output_dir")
    if output_dir:
        out = Path(output_dir)
        snap_output = snap_dir / "output"
        snap_output.mkdir(parents=True, exist_ok=True)
        for fname in ("case_report.md", "case_report.html", "case_report.pdf", "case_report.docx"):
            src = out / fname
            if src.exists():
                shutil.copy2(src, snap_output / fname)

    # 复制 manifest
    manifest_path = pipeline_result.get("manifest_path")
    if manifest_path and Path(manifest_path).exists():
        shutil.copy2(manifest_path, snap_dir / "manifest.json")

    # 写审计日志
    alerts_value = pipeline_result.get("critical_alerts", 0)
    if isinstance(alerts_value, int):
        critical_alerts_count = alerts_value
        critical_alerts: List[Any] = []
    else:
        critical_alerts = alerts_value or []
        critical_alerts_count = len(critical_alerts)

    audit = {
        "version_id": version_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operator": operator or os.getenv("USER", "auto"),
        "input_dir": str(input_dir),
        "files_total": pipeline_result.get("files_total", 0),
        "files_processed": pipeline_result.get("files_processed", 0),
        "files_pending_ocr": pipeline_result.get("files_pending_ocr", 0),
        "files_failed": pipeline_result.get("files_failed", 0),
        "timeline_events": pipeline_result.get("timeline_events", 0),
        "critical_alerts_count": critical_alerts_count,
        "critical_alerts": critical_alerts,
        "publish_url": pipeline_result.get("publish_url"),
        "publish_status": pipeline_result.get("publish_status"),
        "notes": notes,
        "files_fingerprint": files_fingerprint,
        "files_detail": files_processed,
    }
    (snap_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 更新版本索引
    version_info = {
        "version_id": version_id,
        "created_at": audit["created_at"],
        "operator": audit["operator"],
        "notes": notes,
        "files_total": audit["files_total"],
        "critical_alerts_count": critical_alerts_count,
        "publish_url": audit.get("publish_url"),
        "snapshot_path": str(snap_dir),
        "files_fingerprint": files_fingerprint,
    }
    versions.append(version_info)
    _write_versions_index(patient_id, versions)

    # 更新 current 软链接
    current_link = p_dir / "current"
    try:
        if current_link.exists() or current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(snap_dir.name)
    except OSError:
        pass  # 软链接失败不影响主流程

    logger.info("记忆已记录: %s → %s", patient_id, version_id)
    return version_info


def recall_version(patient_id: str, version_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """回溯某个版本的内容。

    Parameters
    ----------
    patient_id : 患者ID
    version_id : 版本号（如 "v001"），None 则取最新版本

    Returns
    -------
    该版本的 audit.json 内容，或 None
    """
    versions = get_versions_index(patient_id)
    if not versions:
        logger.warning("患者 %s 无历史版本", patient_id)
        return None

    if version_id is None:
        version_id = versions[-1]["version_id"]

    snap_dir = get_patient_memory_dir(patient_id) / version_id
    audit_path = snap_dir / "audit.json"
    if not audit_path.exists():
        logger.warning("版本 %s 的 audit.json 不存在", version_id)
        return None

    return json.loads(audit_path.read_text(encoding="utf-8"))


def list_versions(patient_id: str) -> List[Dict[str, Any]]:
    """列出患者所有版本摘要"""
    return get_versions_index(patient_id)


def diff_versions(patient_id: str, v1: str, v2: str) -> Dict[str, Any]:
    """对比两个版本的差异

    Returns
    -------
    { "files_added": [...], "files_removed": [...], "files_changed": [...], "alerts_diff": [...] }
    """
    snap = get_patient_memory_dir(patient_id)
    audit1 = json.loads((snap / v1 / "audit.json").read_text(encoding="utf-8"))
    audit2 = json.loads((snap / v2 / "audit.json").read_text(encoding="utf-8"))

    files1 = {f["path"]: f for f in audit1.get("files_detail", [])}
    files2 = {f["path"]: f for f in audit2.get("files_detail", [])}

    added = [f for p, f in files2.items() if p not in files1]
    removed = [f for p, f in files1.items() if p not in files2]
    changed = [f for p, f in files2.items() if p in files1 and files1[p].get("hash") != f.get("hash")]

    def _alerts(value: Any) -> List[Dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [a for a in value if isinstance(a, dict)]
        if isinstance(value, int):
            return []
        return []

    alerts1 = {a.get("item_name"): a for a in _alerts(audit1.get("critical_alerts")) if a.get("item_name")}
    alerts2 = {a.get("item_name"): a for a in _alerts(audit2.get("critical_alerts")) if a.get("item_name")}
    alerts_diff = {
        "new": [a for k, a in alerts2.items() if k not in alerts1],
        "resolved": [a for k, a in alerts1.items() if k not in alerts2],
        "changed": [a for k, a in alerts2.items() if k in alerts1 and a != alerts1[k]],
    }

    return {
        "v1": v1,
        "v2": v2,
        "files_added": added,
        "files_removed": removed,
        "files_changed": changed,
        "alerts_diff": alerts_diff,
    }


def rollback(patient_id: str, target_version: str) -> Dict[str, Any]:
    """回滚到指定版本（将目标版本的文件恢复到当前工作目录）

    Returns
    -------
    回滚操作的结果信息
    """
    snap = get_patient_memory_dir(patient_id)
    target_dir = snap / target_version
    if not target_dir.exists():
        return {"status": "error", "message": f"版本 {target_version} 不存在"}

    # 找到患者实际工作目录（从 manifest 中读取）
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "error", "message": "目标版本无 manifest.json"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    patient_id_actual = manifest.get("patient_id", patient_id)
    patient_dir = Path.home() / "patients" / patient_id_actual

    # 恢复 manifest
    dst_manifest = patient_dir / "manifest.json"
    shutil.copy2(manifest_path, dst_manifest)

    # 恢复 output 目录
    snap_output = target_dir / "output"
    dst_output = patient_dir / "output"
    if snap_output.exists():
        if dst_output.exists():
            shutil.rmtree(dst_output)
        shutil.copytree(snap_output, dst_output)

    return {
        "status": "success",
        "patient_id": patient_id_actual,
        "patient_dir": str(patient_dir),
        "restored_version": target_version,
        "manifest_restored": True,
        "output_restored": snap_output.exists(),
    }
