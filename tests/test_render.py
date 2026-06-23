"""
T5 验收测试：scripts/render_report.py

覆盖：
  ① MD 模板字段全部填充
  ② 危急值触发免责声明（1 期简化：输出含 disclaimer）
  ③ 缺口提示正确识别缺失分类
  ④ HTML 文件可生成（非空、含 <html> 标签）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.render_report import render_md, render_html, compute_report_context, _build_context


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
            {
                "original_name": "ct_report.pdf",
                "title": "胸部CT报告",
                "date_detected": "2024-03-15",
                "category": "imaging.ct",
            },
        ],
        "categories_summary": {
            "lab_results": 1,
            "imaging": 1,
        },
    }


@pytest.fixture
def timeline() -> list:
    return [
        {
            "dates": ["2024-03-15"],
            "title": "首诊，肺腺癌确诊",
            "category": "basic_info",
        },
        {
            "dates": ["2024-03-20"],
            "title": "基因检测报告",
            "category": "pathology",
        },
    ]


def test_build_context(manifest, timeline):
    ctx = _build_context(manifest, timeline=timeline)
    assert ctx["demographics"]["name"] == "张三"
    assert len(ctx["timeline"]) == 2
    assert ctx["timeline"][0]["title"] == "首诊，肺腺癌确诊"


def test_render_md_outputs_file(manifest, timeline, tmp_dir):
    out = tmp_dir / "report.md"
    path = render_md(manifest, timeline=timeline, output_path=out)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "张三" in text
    assert "肺腺癌" in text
    assert "血常规检验报告" in text


def test_render_md_contains_disclaimer(manifest, timeline, tmp_dir):
    out = tmp_dir / "report.md"
    render_md(manifest, timeline=timeline, output_path=out)
    text = out.read_text(encoding="utf-8")
    assert "免责" in text or "诊断" in text


def test_render_md_gaps_detected(manifest, timeline, tmp_dir):
    # 当前 manifest 缺少 pathology / medication，应触发缺口提示
    out = tmp_dir / "report.md"
    render_md(manifest, timeline=timeline, output_path=out)
    text = out.read_text(encoding="utf-8")
    assert "缺少" in text or "缺口" in text


def test_render_html_non_empty(manifest, timeline, tmp_dir, monkeypatch):
    import sys

    # Mock the markdown module
    class FakeMarkdown:
        @staticmethod
        def markdown(text, extensions=None):
            return "<html><body>" + text + "</body></html>"

    monkeypatch.setitem(sys.modules, "markdown", FakeMarkdown())
    out = tmp_dir / "report.html"
    path = render_html(manifest, timeline=timeline, output_path=out)
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "张三" in html


def test_compute_report_context_is_json_serializable(manifest, timeline):
    import json

    ctx = compute_report_context(
        manifest,
        timeline=timeline,
        extracted_texts=[
            "血钾：7.2 mmol/L\nEGFR 19del 突变，VAF 15%，建议使用 EGFR-TKI。"
        ],
    )

    dumped = json.dumps(ctx, ensure_ascii=False)
    loaded = json.loads(dumped)

    assert loaded["critical_alerts"]
    assert isinstance(loaded["critical_alerts"][0], dict)
    assert loaded["critical_alerts"][0]["item_name"]
    assert loaded["genetic_highlights"]
    assert isinstance(loaded["genetic_highlights"][0], dict)


def test_render_html_accepts_json_loaded_report_context(manifest, timeline, tmp_dir, monkeypatch):
    import json
    import sys

    class FakeMarkdown:
        @staticmethod
        def markdown(text, extensions=None):
            return "<html><body>" + text + "</body></html>"

    monkeypatch.setitem(sys.modules, "markdown", FakeMarkdown())

    ctx = compute_report_context(
        manifest,
        timeline=timeline,
        extracted_texts=["血钾：7.2 mmol/L\nEGFR 19del 突变，VAF 15%。"],
    )
    ctx = json.loads(json.dumps(ctx, ensure_ascii=False))

    out = tmp_dir / "report.html"
    render_html(manifest, timeline=timeline, output_path=out, report_context=ctx)

    html = out.read_text(encoding="utf-8")
    assert "alert-banner" in html or "critical-banner" in html
    assert "EGFR" in html


def test_render_html_escapes_public_dynamic_fields(manifest, timeline, tmp_dir, monkeypatch):
    import sys

    class FakeMarkdown:
        @staticmethod
        def markdown(text, extensions=None):
            return "<main>" + text + "</main>"

    monkeypatch.setitem(sys.modules, "markdown", FakeMarkdown())

    manifest = dict(manifest)
    manifest["demographics"] = dict(manifest["demographics"])
    manifest["demographics"]["name"] = "<script>alert(1)</script>"
    manifest["files"] = [dict(manifest["files"][0])]
    manifest["files"][0]["title"] = '<img src=x onerror="alert(1)">'
    ctx = compute_report_context(manifest, timeline=timeline)
    ctx["consultation_questions"] = ['<img src=x onerror="alert(1)">']

    out = tmp_dir / "report.html"
    render_html(manifest, timeline=timeline, output_path=out, report_context=ctx)

    html = out.read_text(encoding="utf-8")
    assert "<script" not in html
    assert "onerror" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html or "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;" in html
    assert "Content-Security-Policy" in html
    assert "noindex,nofollow" in html
