"""
scripts/memory.py 回归测试

覆盖：
  ① diff_versions 兼容旧版 int 类型 critical_alerts
  ② diff_versions 支持新版 list 类型 critical_alerts 并正确 diff
"""
from __future__ import annotations

import json

import pytest

import scripts.memory as memory


@pytest.fixture(autouse=True)
def _patch_memory_root(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_ROOT", tmp_path / "memory")


def _write_audit(patient_id, version, alerts, files_detail):
    snap = memory.get_patient_memory_dir(patient_id) / version
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "audit.json").write_text(
        json.dumps({
            "version_id": version,
            "files_detail": files_detail,
            "critical_alerts": alerts,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_diff_versions_handles_legacy_int_critical_alerts():
    patient = "P001"
    files = [{"path": "/tmp/a.txt", "hash": "aaa"}]
    _write_audit(patient, "v001", 1, files)
    _write_audit(patient, "v002", 2, files)

    diff = memory.diff_versions(patient, "v001", "v002")
    assert diff["files_added"] == []
    assert diff["files_removed"] == []
    assert diff["files_changed"] == []
    assert diff["alerts_diff"]["new"] == []
    assert diff["alerts_diff"]["resolved"] == []
    assert diff["alerts_diff"]["changed"] == []


def test_diff_versions_alerts_list_schema():
    patient = "P001"
    files_v1 = [{"path": "/tmp/a.txt", "hash": "aaa"}]
    files_v2 = [
        {"path": "/tmp/a.txt", "hash": "aaa"},
        {"path": "/tmp/b.txt", "hash": "bbb"},
    ]
    alerts_v1 = [{"item_name": "血钾", "value": 7.2, "level": 5}]
    alerts_v2 = [
        {"item_name": "血钾", "value": 5.0, "level": 2},
        {"item_name": "白细胞", "value": 0.8, "level": 5},
    ]
    _write_audit(patient, "v001", alerts_v1, files_v1)
    _write_audit(patient, "v002", alerts_v2, files_v2)

    diff = memory.diff_versions(patient, "v001", "v002")

    assert len(diff["files_added"]) == 1
    assert diff["files_added"][0]["path"] == "/tmp/b.txt"
    assert diff["alerts_diff"]["new"][0]["item_name"] == "白细胞"
    assert diff["alerts_diff"]["changed"][0]["item_name"] == "血钾"
