"""
V2 渲染器测试：PDF / DOCX（可选格式）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def manifest() -> dict:
    return {
        "patient_id": "P001",
        "created_at": "2024-03-15T10:00:00+00:00",
        "updated_at": "2024-09-10T14:30:00+00:00",
        "demographics": {
            "name": "张三",
            "gender": "男",
            "age": 62,
            "primary_diagnosis": "肺腺癌",
        },
        "files": [
            {
                "original_name": "blood_test.jpg",
                "title": "血常规检验报告",
                "date_detected": "2024-03-15",
                "category": "lab_results.blood_routine",
            },
        ],
        "categories_summary": {"lab_results": 1},
    }


def test_render_pdf_mocked(manifest, tmp_dir, monkeypatch):
    """Mock weasyprint 和 markdown，验证 PDF 输出流程"""
    class FakeHTML:
        def __init__(self, *args, **kwargs):
            pass
        def write_pdf(self, path):
            Path(path).write_bytes(b"%PDF-1.4 fake")

    class FakeMarkdown:
        @staticmethod
        def markdown(text, extensions=None):
            return "<html><body> mocked </body></html>"

    fake_md = type(sys)("markdown")
    fake_md.markdown = FakeMarkdown.markdown
    monkeypatch.setitem(sys.modules, "markdown", fake_md)

    fake_mod = type(sys)("weasyprint")
    fake_mod.HTML = FakeHTML
    monkeypatch.setitem(sys.modules, "weasyprint", fake_mod)

    # 重新加载 render_report 以获取新的模块
    import importlib
    import scripts.render_report as rr
    importlib.reload(rr)

    out = tmp_dir / "report.pdf"
    path = rr.render_pdf(manifest, output_path=out)
    assert path.exists()
    assert path.suffix == ".pdf"


def test_render_docx_mocked(manifest, tmp_dir, monkeypatch):
    """Mock python-docx，验证 DOCX 输出流程"""
    class FakeDocx:
        class Document:
            def __init__(self):
                self.paragraphs = []
            def add_heading(self, text, level=1):
                self.paragraphs.append(f"H{level}: {text}")
            def add_paragraph(self, text, style=None):
                self.paragraphs.append(text)
            def save(self, path):
                Path(path).write_bytes(b"fake-docx")

    monkeypatch.setitem(sys.modules, "docx", FakeDocx)

    from scripts.render_report import render_docx
    out = tmp_dir / "report.docx"
    path = render_docx(manifest, output_path=out)
    assert path.exists()
    assert path.suffix == ".docx"
