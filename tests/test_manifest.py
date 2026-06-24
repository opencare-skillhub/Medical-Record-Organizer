"""
T2 验收测试：scripts/manifest.py

覆盖：
  ① 新建 manifest 结构正确（包含 demographics / files / categories_summary）
  ② 相同文件哈希被跳过（增量去重）
  ③ append_files + write_manifest 后 updated_at 刷新、files 增加
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.manifest import (
    create_manifest,
    load_manifest,
    write_manifest,
    diff_files,
    append_files,
    init_or_load,
    sha256_of,
    _default_patient_dir,
)


@pytest.fixture
def patient_dir(tmp_dir) -> Path:
    d = tmp_dir / "patients" / "P001"
    d.mkdir(parents=True)
    return d


# ① 新建 manifest 结构正确
def test_create_manifest(patient_dir):
    m = create_manifest(
        "P001",
        name="张三",
        age=62,
        gender="男",
        primary_diagnosis="肺腺癌",
        patient_dir=patient_dir,
    )
    assert m["patient_id"] == "P001"
    assert m["demographics"]["name"] == "张三"
    assert m["demographics"]["age"] == 62
    assert m["files"] == []
    assert "created_at" in m
    assert "updated_at" in m
    # 落盘可读
    reloaded = json.loads((patient_dir / "manifest.json").read_text(encoding="utf-8"))
    assert reloaded["patient_id"] == "P001"


# ② 相同文件哈希被跳过
def test_diff_files_skip_duplicate(patient_dir):
    # 先写一个 manifest，里面已有 1 个文件
    f1 = patient_dir / "a.jpg"
    f1.write_bytes(b"content-a")
    h1 = sha256_of(f1)
    manifest = create_manifest("P001", patient_dir=patient_dir)
    manifest = append_files(manifest, [(str(f1), "image")])
    write_manifest(manifest, patient_dir=patient_dir)

    # 再 collect 到同样的文件 + 一个新文件
    f2 = patient_dir / "b.jpg"
    f2.write_bytes(b"content-b")
    collected = [(str(f1), "image"), (str(f2), "image")]
    new_only = diff_files(load_manifest("P001", patient_dir=patient_dir), collected)
    assert len(new_only) == 1
    assert new_only[0][0] == str(f2)


# ③ append + write 后 updated_at 刷新、files 增加
def test_append_and_write_refreshes(patient_dir):
    manifest = create_manifest("P001", patient_dir=patient_dir)
    old_updated = manifest["updated_at"]

    f = patient_dir / "note.txt"
    f.write_bytes(b"hello")
    new_files = [(str(f), "text")]
    manifest = append_files(manifest, new_files)
    write_manifest(manifest, patient_dir=patient_dir)

    reloaded = load_manifest("P001", patient_dir=patient_dir)
    assert len(reloaded["files"]) == 1
    assert reloaded["files"][0]["original_name"] == "note.txt"
    assert reloaded["updated_at"] >= old_updated


# ④ init_or_load：不存在时创建、存在时加载
def test_init_or_load_new(patient_dir):
    m, is_new = init_or_load("P001", patient_dir=patient_dir)
    assert is_new is True
    assert m["patient_id"] == "P001"


def test_init_or_load_existing(patient_dir):
    create_manifest("P001", patient_dir=patient_dir)
    m, is_new = init_or_load("P001", patient_dir=patient_dir)
    assert is_new is False
    assert m["patient_id"] == "P001"


# ⑤ sha256 一致性
def test_sha256():
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"hello")
        name = tf.name
    try:
        h = sha256_of(Path(name))
        assert len(h) == 64
        assert h == sha256_of(Path(name))
    finally:
        Path(name).unlink()


# Fix 1：categories_summary 在 append_files 和 write_manifest 后自动回写
def test_categories_summary_auto_updated(patient_dir):
    m = create_manifest("P001", patient_dir=patient_dir)
    # 模拟已分类的文件条目
    m["files"] = [
        {"hash": "a", "category": "lab_results"},
        {"hash": "b", "category": "imaging"},
        {"hash": "c", "category": "lab_results.blood_routine"},
    ]
    write_manifest(m, patient_dir=patient_dir)

    reloaded = load_manifest("P001", patient_dir=patient_dir)
    summary = reloaded["categories_summary"]
    assert summary.get("lab_results") == 2
    assert summary.get("imaging") == 1


def test_append_files_refreshes_summary(patient_dir):
    m = create_manifest("P001", patient_dir=patient_dir)
    f1 = patient_dir / "ct.txt"
    f1.write_bytes(b"CT report")
    m = append_files(m, [(str(f1), "text")])
    # category 为 None 的条目归入 "other"
    assert m["categories_summary"] == {"other": 1}

    # 模拟分类后更新 category
    m["files"][0]["category"] = "imaging"
    write_manifest(m, patient_dir=patient_dir)
    reloaded = load_manifest("P001", patient_dir=patient_dir)
    assert reloaded["categories_summary"].get("imaging") == 1
