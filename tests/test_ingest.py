"""
T1 验收测试：scripts/ingest.py

覆盖：
  ① 混合格式目录扫描
  ② zip 解压后扫描
  ③ 遇到 .dcm 等不支持格式：不报错、只提示、跳过
  ④ 空目录返回空列表
  ⑤ 直接上传文件列表（含 image / pdf / audio / docx / txt）
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from scripts.ingest import collect, _scan_directory, _extract_zip, _detect_type


@pytest.fixture
def mixed_dir(tmp_dir):
    """混合格式目录：jpg / pdf / mp3 / docx / txt / dcm"""
    files = {
        "blood_test.jpg": "image",
        "report.pdf": "pdf",
        "voice.mp3": "audio",
        "note.txt": "text",
        "unexpected.dcm": None,
    }
    for name, _ in files.items():
        (tmp_dir / name).write_bytes(b"dummy")
    return tmp_dir


@pytest.fixture
def zip_file(tmp_dir):
    """包含混合文件的 zip"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("scan1.jpg", b"img")
        zf.writestr("result.pdf", b"pdf")
        zf.writestr("chat.wav", b"audio")
    buf.seek(0)
    return buf


# ① 混合格式目录扫描
def test_scan_mixed_dir(mixed_dir, caplog):
    caplog.set_level("INFO")
    results = _scan_directory(mixed_dir)
    types = {t for _, t in results}
    assert "image" in types
    assert "pdf" in types
    assert "audio" in types
    assert "text" in types
    # dcm 不出现
    assert all(not p.endswith(".dcm") for p, _ in results)
    assert "跳过不支持的文件" in caplog.text


# ② zip 解压
def test_extract_zip(zip_file, tmp_dir, caplog):
    caplog.set_level("INFO")
    zip_path = tmp_dir / "data.zip"
    zip_path.write_bytes(zip_file.getvalue())
    results = _extract_zip(zip_path, tmp_dir)
    types = {t for _, t in results}
    assert "image" in types
    assert "pdf" in types
    assert "audio" in types
    assert "解压 zip" in caplog.text


# ③ dcm 等不支持的格式不报错、只提示、跳过
def test_unsupported_skipped(mixed_dir, caplog):
    caplog.set_level("INFO")
    _scan_directory(mixed_dir)
    assert "跳过不支持的文件" in caplog.text


# ④ 空目录返回空列表
def test_empty_dir(tmp_dir):
    results = _scan_directory(tmp_dir)
    assert results == []


# ⑤ 直接上传文件列表
def test_collect_file_list(tmp_dir):
    (tmp_dir / "a.jpg").write_bytes(b"img")
    (tmp_dir / "b.mp3").write_bytes(b"audio")
    (tmp_dir / "c.dcm").write_bytes(b"dicom")
    results = collect([str(tmp_dir / "a.jpg"), str(tmp_dir / "b.mp3"), str(tmp_dir / "c.dcm")])
    assert len(results) == 2
    assert all(not p.endswith(".dcm") for p, _ in results)


# 辅助：_detect_type
def test_detect_type():
    assert _detect_type(type("P", (), {"suffix": ".jpg"})()) == "image"
    assert _detect_type(type("P", (), {"suffix": ".PDF"})()) == "pdf"
    assert _detect_type(type("P", (), {"suffix": ".MP3"})()) == "audio"
    assert _detect_type(type("P", (), {"suffix": ".TXT"})()) == "text"
    assert _detect_type(type("P", (), {"suffix": ".DOCX"})()) == "docx"
    assert _detect_type(type("P", (), {"suffix": ".DCM"})()) is None


# Fix 5：多个 zip 分别解压到独立子目录，避免同名文件覆盖
def test_multiple_zips_extracted_to_separate_dirs(tmp_dir, caplog):
    caplog.set_level("INFO")
    import io
    import zipfile

    # 创建两个 zip，内含同名文件
    buf1 = io.BytesIO()
    with zipfile.ZipFile(buf1, "w") as zf:
        zf.writestr("report.txt", "report from zip1")
    buf1.seek(0)

    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("report.txt", "report from zip2")
    buf2.seek(0)

    zip1 = tmp_dir / "data1.zip"
    zip2 = tmp_dir / "data2.zip"
    zip1.write_bytes(buf1.getvalue())
    zip2.write_bytes(buf2.getvalue())

    results = collect([str(zip1), str(zip2)], extract_dir=str(tmp_dir / "extracted"))
    names = {Path(p).name for p, _ in results}
    # 两个同名文件都应存在（因为各自在独立子目录）
    assert "report.txt" in names
    # 验证子目录确实存在
    assert (tmp_dir / "extracted" / "data1" / "report.txt").exists()
    assert (tmp_dir / "extracted" / "data2" / "report.txt").exists()


# 安全：拒绝 Zip Slip 路径穿越
@pytest.mark.parametrize("member_name", ["../evil.txt", "nested/../../evil.txt", "/tmp/evil.txt", "C:/evil.txt", "C:\\evil.txt"])
def test_extract_zip_rejects_path_traversal(member_name, tmp_dir):
    zip_path = tmp_dir / "evil.zip"
    dest_dir = tmp_dir / "dest"
    outside = tmp_dir / "evil.txt"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member_name, "pwned")
        zf.writestr("safe/report.txt", "ok")

    with pytest.raises(ValueError):
        _extract_zip(zip_path, dest_dir)

    assert not outside.exists()
    assert not (tmp_dir / "pwned").exists()
