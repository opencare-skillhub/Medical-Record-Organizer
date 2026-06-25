"""
v2 pipeline 测试
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.v2.pipeline_v2 import run_pipeline


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    """桩掉所有 LLM 调用，保证测试离线快速且不触发真实 API。"""
    monkeypatch.setattr(
        'scripts.v2.map_extract.extract_batch',
        lambda sanitized_dir, output_dir, **kw: [
            {'report_type': 'basic_info', 'confidence': 0.9, '_source_file': f.name,
             'document_date': '2025-01-01', 'demographics': {'name': '张三', 'gender': '男', 'age': 60}}
            for f in sorted(Path(sanitized_dir).glob('*.md'))
        ],
    )
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.reduce_lab_trends',
        lambda trends, **kw: {k: {'alert_level': 'normal', 'trend_summary': '稳定'} for k in trends},
    )
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.reduce_medication_history',
        lambda med_group, **kw: {'timeline': [], 'regimens': [], 'cycles': [], 'response_assessments': [], 'toxicities': []},
    )
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.reduce_imaging_narrative',
        lambda imaging_group, **kw: {'primary_lesion_timeline': [], 'metastasis_timeline': [], 'overall_response': ''},
    )
    monkeypatch.setattr(
        'scripts.mdt_analysis.run_mdt_analysis',
        lambda profile, groups, **kw: {
            'specialty_reports': {},
            'concerns': [],
            'fallback_used': {'synthesis': True},
            'error': None,
        },
    )


def test_run_pipeline_generates_profile(tmp_dir, monkeypatch):
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'a.md').write_text('姓名：张三，性别：男', encoding='utf-8')
    (input_dir / 'b.md').write_text('检验报告：CEA 5.2 ng/ml', encoding='utf-8')

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    assert profile['patient_id'] == 'P001'
    assert profile['file_count'] == 2
    assert profile['map_count'] == 2
    assert (output_dir / 'profile.json').exists()
    assert (output_dir / 'mdt_analysis.json').exists()
    mdt = json.loads((output_dir / 'mdt_analysis.json').read_text(encoding='utf-8'))
    assert {'specialty_reports', 'concerns', 'fallback_used', 'error'} <= set(mdt)
    assert (output_dir / 'report.html').exists()
    assert (output_dir / 'report.html').stat().st_size > 0
    assert (output_dir / 'case_report.md').exists()
    assert (output_dir / 'mappings.json').exists()


def test_run_pipeline_no_input(tmp_dir):
    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(tmp_dir), str(output_dir), patient_id='P001')
    assert profile['status'] == 'no_input'
    assert profile['files'] == 0


def test_run_pipeline_creates_sanitized_and_map_dirs(tmp_dir, monkeypatch):
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'a.md').write_text('姓名：张三', encoding='utf-8')

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    assert (output_dir / 'sanitized').exists()
    assert (output_dir / 'map').exists()
    assert (output_dir / 'report.html').exists()
    assert (output_dir / 'sanitized' / 'a.md').exists()


def test_run_pipeline_raw_files_trigger_ocr_preprocessing(tmp_dir, monkeypatch):
    """原始图片/PDF 应触发 OCR 预处理并写 extracted/*.md，再进 v2 流程。"""
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'scan.jpg').write_bytes(b'fake-jpg')
    (input_dir / 'report.pdf').write_bytes(b'fake-pdf')

    ocr_calls = []

    def fake_extract_text(file_path, *, extract_dir=None, **kw):
        ocr_calls.append(Path(file_path).name)
        return f"OCR文本 {Path(file_path).name}"

    monkeypatch.setattr('scripts.route_ocr.extract_text', fake_extract_text)

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    # OCR 被调用了两次（两个原始文件）
    assert sorted(ocr_calls) == ['report.pdf', 'scan.jpg']
    # extracted/*.md 生成
    assert (output_dir / 'extracted' / 'scan.md').exists()
    assert (output_dir / 'extracted' / 'report.md').exists()
    assert 'OCR文本' in (output_dir / 'extracted' / 'scan.md').read_text(encoding='utf-8')
    # 进了 v2 流程：profile 生成
    assert profile['patient_id'] == 'P001'
    assert profile['file_count'] == 2
    assert (output_dir / 'profile.json').exists()
    assert (output_dir / 'report.html').exists()


def test_run_pipeline_skip_ocr_writes_empty_md(tmp_dir, monkeypatch):
    """--skip-ocr 时原始文件写空 md，不调用 OCR。"""
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'scan.jpg').write_bytes(b'fake-jpg')

    def boom(*a, **kw):
        raise AssertionError("skip_ocr 不应调用 extract_text")

    monkeypatch.setattr('scripts.route_ocr.extract_text', boom)

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001', skip_ocr=True)

    assert (output_dir / 'extracted' / 'scan.md').exists()
    assert (output_dir / 'extracted' / 'scan.md').read_text(encoding='utf-8') == ''
    assert profile['file_count'] == 1


def test_run_pipeline_mixed_md_and_raw(tmp_dir, monkeypatch):
    """混合 .md + 图片：原始文件 OCR，.md 直接进流程。"""
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'a.md').write_text('姓名：张三', encoding='utf-8')
    (input_dir / 'b.jpg').write_bytes(b'fake-jpg')

    monkeypatch.setattr(
        'scripts.route_ocr.extract_text',
        lambda fp, **kw: f"OCR {Path(fp).name}"
    )

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    # a.md 原样进 sanitized，b.jpg 经 OCR 产出 extracted/b.md 后进 sanitized
    assert (output_dir / 'sanitized' / 'a.md').exists()
    assert (output_dir / 'sanitized' / 'b.md').exists()
    assert profile['file_count'] == 2
