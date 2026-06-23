"""
端到端集成测试（E1-E10 简化版）

模拟完整工作流：
  1. 资料接入（ingest）
  2. manifest 初始化
  3. 内容提取（OCR/ASR 占位）
  4. 两层分类 + 日期提取
  5. 时间线构建
  6. 报告生成（MD + HTML + PDF + DOCX）

使用 tests/fixtures/ 下的模拟文件。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

# 在导入 render_report 前 mock markdown / weasyprint
class _FakeMarkdown:
    @staticmethod
    def markdown(text, extensions=None):
        return "<html><body> mocked </body></html>"

class _FakeHTML:
    def __init__(self, *args, **kwargs):
        pass
    def write_pdf(self, path):
        Path(path).write_bytes(b"%PDF-1.4 fake")

class _FakeDocx:
    class Document:
        def __init__(self):
            self.paragraphs = []
        def add_heading(self, text, level=1):
            self.paragraphs.append(f"H{level}: {text}")
        def add_paragraph(self, text, style=None):
            self.paragraphs.append(text)
        def save(self, path):
            Path(path).write_bytes(b"fake-docx")

_fake_md = type(sys)("markdown")
_fake_md.markdown = _FakeMarkdown.markdown
sys.modules.setdefault("markdown", _fake_md)

_fake_weasy = type(sys)("weasyprint")
_fake_weasy.HTML = _FakeHTML
sys.modules.setdefault("weasyprint", _fake_weasy)

_fake_docx = type(sys)("docx")
_fake_docx.Document = _FakeDocx.Document
sys.modules.setdefault("docx", _fake_docx)


import scripts.ingest as ingest_mod
import scripts.manifest as manifest_mod
import scripts.classify as classify_mod
import scripts.render_report as render_mod


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def patient_workspace(tmp_dir):
    """为每个测试准备独立患者工作区"""
    ws = tmp_dir / "workspace"
    ws.mkdir()
    # 复制 fixtures 到工作区
    for fp in FIXTURES_DIR.iterdir():
        if fp.is_file():
            shutil.copy(fp, ws / fp.name)
    return ws


def test_e2e_first_archive(patient_workspace, tmp_dir):
    """E1 简化：首次建档全流程"""
    # ① 收集资料
    collected = ingest_mod.collect([str(patient_workspace)])
    assert len(collected) >= 3  # 至少 blood_test / ct_report / genetic_test / discharge

    # ② 初始化 manifest（使用独立目录避免跨测试污染）
    patient_dir = tmp_dir / "patients" / "P_E2E"
    patient_dir.mkdir(parents=True)
    m, is_new = manifest_mod.init_or_load(
        "P_E2E",
        patient_dir=patient_dir,
        name="张三",
        age=62,
        gender="男",
        primary_diagnosis="右肺上叶浸润性腺癌",
    )
    assert is_new is True

    # ③ 模拟提取 + 分类
    timeline = []
    for file_path, file_type in collected:
        text = Path(file_path).read_text(encoding="utf-8")
        primary, secondary_json, confidence = classify_mod.classify(text)
        dates = classify_mod._extract_dates(text)

        # 追加到 manifest（模拟提取后回写）
        m = manifest_mod.append_files(m, [(file_path, file_type)])
        # 更新最后一条文件的分类信息
        m["files"][-1]["category"] = primary
        m["files"][-1]["date_detected"] = dates[0] if dates else None
        m["files"][-1]["title"] = Path(file_path).stem

        # 构建时间线
        entry = classify_mod.build_timeline_entry(file_path, primary, dates, title=Path(file_path).stem)
        timeline.append(entry)

    # 更新分类汇总
    cat_summary: dict = {}
    for fe in m["files"]:
        cat = fe.get("category") or "other"
        top = cat.split(".")[0]
        cat_summary[top] = cat_summary.get(top, 0) + 1
    m["categories_summary"] = cat_summary
    manifest_mod.write_manifest(m, patient_dir=patient_dir)

    # ④ 断言分类结果
    cats = [fe["category"] for fe in m["files"]]
    assert "lab_results" in cats
    assert "imaging" in cats
    # genetics 现在有独立分类，gene_test.txt 归入 genetics
    assert "genetics" in cats or "pathology" in cats
    assert len(cats) >= 3

    # ⑤ 断言时间线
    assert len(timeline) == len(collected)

    # ⑥ 生成报告
    md_out = tmp_dir / "e2e_report.md"
    html_out = tmp_dir / "e2e_report.html"
    pdf_out = tmp_dir / "e2e_report.pdf"
    docx_out = tmp_dir / "e2e_report.docx"

    render_mod.render_md(m, timeline=timeline, output_path=md_out)
    render_mod.render_html(m, timeline=timeline, output_path=html_out)
    render_mod.render_pdf(m, timeline=timeline, output_path=pdf_out)
    render_mod.render_docx(m, timeline=timeline, output_path=docx_out)

    assert md_out.exists()
    assert html_out.exists()
    assert pdf_out.exists()
    assert docx_out.exists()

    md_text = md_out.read_text(encoding="utf-8")
    assert "张三" in md_text
    assert "免责" in md_text or "诊断" in md_text

    html_text = html_out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text


def test_e2e_incremental_update(patient_workspace, tmp_dir):
    """E4 简化：增量更新（已处理文件不重复处理）"""
    patient_dir = tmp_dir / "patients" / "P_INC"
    patient_dir.mkdir(parents=True)
    # 首次建档
    m, is_new = manifest_mod.init_or_load("P_INC", patient_dir=patient_dir, name="测试患者")
    collected1 = ingest_mod.collect([str(patient_workspace)])
    m = manifest_mod.append_files(m, collected1)
    manifest_mod.write_manifest(m, patient_dir=patient_dir)

    # 二次扫描（模拟用户追加文件：复制一个新文件到工作区）
    new_file = patient_workspace / "new_blood_test.txt"
    new_file.write_text("血常规：白细胞 5.6，血红蛋白 118，血小板 198", encoding="utf-8")
    collected2 = ingest_mod.collect([str(patient_workspace)])

    # diff 应只包含新文件
    new_only = manifest_mod.diff_files(m, collected2)
    names = [Path(p).name for p, _ in new_only]
    assert "new_blood_test.txt" in names
    assert "blood_test.txt" not in names


# E3：zip 压缩包解压后处理
def test_e2e_zip_archive(patient_workspace, tmp_dir):
    """E3：上传 zip 压缩包，自动解压后递归处理"""
    import io, zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ct_report.txt", (patient_workspace / "ct_report.txt").read_text(encoding="utf-8"))
        zf.writestr("blood_test.txt", (patient_workspace / "blood_test.txt").read_text(encoding="utf-8"))
    buf.seek(0)

    zip_path = tmp_dir / "medical_data.zip"
    zip_path.write_bytes(buf.getvalue())

    collected = ingest_mod.collect([str(zip_path)], extract_dir=str(tmp_dir / "extracted"))
    types = {t for _, t in collected}
    assert "text" in types
    assert len(collected) >= 2


# E5：分类修正（用户指出某文件分类错误，重新分类后刷新）
def test_e2e_reclassification(tmp_dir):
    """E5：用户反馈"第3个文件分类不对"，Agent 重新分类并更新"""
    patient_dir = tmp_dir / "patients" / "P_RECLS"
    patient_dir.mkdir(parents=True)
    m, _ = manifest_mod.init_or_load("P_RECLS", patient_dir=patient_dir, name="测试")

    # 直接创建单一测试文件，避免 fixture 文件顺序不确定问题
    test_file = tmp_dir / "blood_test.txt"
    test_file.write_text("血常规：白细胞 5.6，血红蛋白 118，血小板 198", encoding="utf-8")
    m = manifest_mod.append_files(m, [(str(test_file), "text")])

    # 模拟第一次分类：被误分为 imaging
    m["files"][0]["category"] = "imaging"
    manifest_mod.write_manifest(m, patient_dir=patient_dir)

    # 用户指出错误，重新分类
    text = test_file.read_text(encoding="utf-8")
    primary, _, _ = classify_mod.classify(text)
    m["files"][0]["category"] = primary
    manifest_mod.write_manifest(m, patient_dir=patient_dir)

    reloaded = manifest_mod.load_manifest("P_RECLS", patient_dir=patient_dir)
    # 修正后应为 lab_results（血常规关键词命中）
    assert reloaded["files"][0]["category"] == "lab_results"
    # categories_summary 也应同步刷新
    assert reloaded["categories_summary"].get("lab_results") == 1


# E7：危急值提醒（上传含危急值的化验单，报告中应标注异常）
def test_e2e_critical_values_alert(patient_workspace, tmp_dir):
    """E7：上传含危急值（如血红蛋白 55 g/L）的化验单，报告含危急值横幅"""
    patient_dir = tmp_dir / "patients" / "P_CRIT"
    patient_dir.mkdir(parents=True)
    m, _ = manifest_mod.init_or_load("P_CRIT", patient_dir=patient_dir, name="危急值患者")

    # 使用 critical fixture
    crit_file = patient_workspace / "blood_test_critical.txt"
    collected = ingest_mod.collect([str(crit_file)])
    m = manifest_mod.append_files(m, collected)

    text = crit_file.read_text(encoding="utf-8")
    primary, _, _ = classify_mod.classify(text)
    dates = classify_mod._extract_dates(text)
    m["files"][0]["category"] = primary
    m["files"][0]["date_detected"] = dates[0] if dates else None
    manifest_mod.write_manifest(m, patient_dir=patient_dir)

    # 生成报告（extra 中传入提取文本，让危急值引擎工作）
    md_out = tmp_dir / "crit_report.md"
    render_mod.render_md(m, timeline=[], output_path=md_out, extra={"extracted_texts": [text]})
    md_text = md_out.read_text(encoding="utf-8")
    # 应包含危急值提示
    assert "危急" in md_text or "警报" in md_text or "血红蛋白" in md_text
